"""Real PostgreSQL regression: durable receipts and competing generation requests.

Only a dedicated loopback CI database is allowed. No provider calls, Telegram,
actual charges, or production data. Synthetic failures model disconnect/rollback
and competing threads, not an operating-system restart or delivery outbox.
"""
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.app.db import Base
from backend.app.models import Child, Order, Story, User
from backend.app.services import story_service


@pytest.fixture
def postgres():
    dsn = os.getenv("LEGENDKIDS_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("Dedicated PostgreSQL CI fixture is required")
    url = make_url(dsn)
    if (url.drivername != "postgresql+psycopg"
            or url.host not in {"127.0.0.1", "localhost"}
            or url.database != "legendkids_test"
            or url.username != "legendkids_test" or url.query):
        raise RuntimeError("Only the dedicated loopback legendkids_test DB is allowed")
    schema = "lk_payment_" + uuid.uuid4().hex
    admin = create_engine(url)
    engine = None
    try:
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(url, connect_args={
            "options": f"-csearch_path={schema} -cstatement_timeout=15000",
        })
        Base.metadata.create_all(engine)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


def payload():
    return {
        "external_user_id": "synthetic-buyer-42",
        "channel": "telegram",
        "child_name": "Тест",
        "age": 7,
        "gender": "neutral",
        "style": "auto",
        "telegram_payment_charge_id": "synthetic-charge-42",
    }


def test_paid_receipt_survives_interrupted_generation_transaction(postgres, monkeypatch):
    # BaseException deliberately bypasses the normal generation error handler:
    # closing the Session rolls back the in-flight story transaction.
    class SimulatedDisconnect(BaseException):
        pass

    def interrupt(_):
        with Session(postgres) as observer:
            order = observer.scalar(select(Order))
            assert order is not None and order.status == "paid"
        raise SimulatedDisconnect()

    monkeypatch.setattr(story_service, "generate_story_payload", interrupt)
    with Session(postgres) as session:
        with pytest.raises(SimulatedDisconnect):
            story_service.generate_story(session, payload())
    with Session(postgres) as recovered:
        order = recovered.scalar(select(Order))
        assert order.provider_payment_id == "synthetic-charge-42"
        assert order.status == "paid"
        assert order.meta['questionnaire_v1']['version'] == 1
        assert order.meta['questionnaire_v1']['child_name'] == 'Тест'
        assert recovered.scalar(select(func.count()).select_from(Order)) == 1
        assert recovered.scalar(select(func.count()).select_from(Story)) == 0


def test_two_simultaneous_requests_create_one_paid_order_and_one_story(postgres, monkeypatch):
    barrier = threading.Barrier(2)
    calls = []
    calls_lock = threading.Lock()

    def synthetic_text(_):
        with calls_lock:
            calls.append("provider-called")
        time.sleep(0.15)
        return {"title": "Синтетическая проверка", "story_text": "Тестовая история."}

    monkeypatch.setattr(story_service, "generate_story_payload", synthetic_text)
    monkeypatch.setattr(story_service, "generate_images", lambda **kw: (
        ["synthetic-image-" + str(i) for i in range(5)], None
    ))
    monkeypatch.setattr(story_service, "require_complete_images", lambda _: None)
    monkeypatch.setattr(story_service, "generate_pdf", lambda **kw: "synthetic-pdf")
    monkeypatch.setattr(story_service, "require_complete_pdf", lambda _: None)

    def worker():
        with Session(postgres) as session:
            barrier.wait(timeout=5)
            result = story_service.generate_story(session, payload())
            return result.id, result.order_id, result.status

    with ThreadPoolExecutor(max_workers=2) as executor:
        a, b = executor.submit(worker), executor.submit(worker)
        first, second = a.result(timeout=25), b.result(timeout=25)

    assert first == second
    assert first[2] == "ready"
    assert calls == ["provider-called"]
    with Session(postgres) as session:
        for model in (User, Child, Order, Story):
            assert session.scalar(select(func.count()).select_from(model)) == 1
