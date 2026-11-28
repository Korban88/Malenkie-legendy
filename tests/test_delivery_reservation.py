"""Local reservation regressions; no bot, provider, or real payment calls."""
import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles, deregister
from sqlalchemy.orm import sessionmaker

from backend.app import book_release
from backend.app.services import telegram_delivery
from backend.app.db import Base
from backend.app.models import Child, Order, Story, User
from backend.app.services.telegram_delivery import (
    DeliveryReservation, acknowledge_delivery, reserve_ready_delivery,
)
from backend.app.services.telegram_library import find_book


@pytest.fixture
def paid(tmp_path, monkeypatch):
    @compiles(JSONB, 'sqlite')
    def jsonb(type_, compiler, **kw):
        return 'JSON'
    monkeypatch.setattr(book_release, 'get_settings', lambda: SimpleNamespace(stories_dir=str(tmp_path)))
    engine = create_engine('sqlite:///' + (tmp_path / 'synthetic.db').as_posix())
    factory = sessionmaker(bind=engine)
    path = tmp_path / ('a' * 32 + '.pdf')
    pdf = Canvas(str(path))
    for i in range(5):
        pdf.drawString(40, 700, 'Synthetic page')
        with Image.new('RGB', (32, 24), (i * 40, 100, 150)) as picture:
            pdf.drawImage(ImageReader(picture), 40, 500, width=120, height=90)
        pdf.showPage()
    pdf.save()
    try:
        Base.metadata.create_all(engine)
        with factory.begin() as db:
            buyer = User(channel='telegram', external_id='101')
            db.add(buyer); db.flush()
            child = Child(user_id=buyer.id, name='Synthetic', age=7)
            db.add(child); db.flush()
            order = Order(user_id=buyer.id, child_id=child.id, provider='telegram_stars',
                          provider_payment_id='synthetic-receipt', tariff='story', amount_rub=150, status='paid')
            db.add(order); db.flush()
            stories = [Story(order_id=order.id, child_id=child.id, episode_number=i,
                             status='ready', pdf_url='/files/stories/' + path.name) for i in (1, 2)]
            db.add_all(stories); db.flush()
            args = dict(order_id=order.id, story_id=stories[0].id, external_user_id='101')
            second = stories[1].id
        yield factory, args, second, path, engine
    finally:
        engine.dispose()
        deregister(JSONB)


def test_reservation_survives_restart_and_unknown_outcome(paid):
    factory, args, second, path, engine = paid
    claim = reserve_ready_delivery(factory, **args)
    assert claim.recipient == '101'
    assert claim.pdf_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    # A separate engine/session simulates another process opening persisted DB.
    engine.dispose()
    reopened = create_engine(engine.url)
    try:
        next_factory = sessionmaker(bind=reopened)
        assert reserve_ready_delivery(next_factory, **args) is None
        assert reserve_ready_delivery(next_factory, **dict(args, story_id=second)) is None
        with next_factory() as db:
            assert db.get(DeliveryReservation, args['order_id']).telegram_message_id is None
            assert find_book(db, '101', args['story_id'])['pdf_sha256'] == claim.pdf_sha256
            assert find_book(db, '202', args['story_id']) is None
            assert db.scalar(select(func.count(Order.id))) == 1
    finally:
        reopened.dispose()


def test_ack_is_idempotent_and_cannot_be_overwritten(paid):
    factory, args, _, _, _ = paid
    claim = reserve_ready_delivery(factory, **args)
    receipt = dict(order_id=claim.order_id, token=claim.token, message_id=123)
    assert not acknowledge_delivery(factory, **dict(receipt, token='bad'))
    assert not acknowledge_delivery(factory, **dict(receipt, message_id=True))
    assert acknowledge_delivery(factory, **receipt)
    assert acknowledge_delivery(factory, **receipt)
    assert not acknowledge_delivery(factory, **dict(receipt, message_id=124))
    assert reserve_ready_delivery(factory, **args) is None
    with factory() as db:
        assert db.get(DeliveryReservation, claim.order_id).telegram_message_id == 123


@pytest.mark.parametrize('bad', ['buyer', 'order', 'group', 'unpaid', 'no_receipt', 'not_ready', 'bad_pdf'])
def test_ineligible_book_cannot_be_reserved(paid, bad):
    factory, args, _, path, _ = paid
    if bad == 'buyer': args['external_user_id'] = '202'
    if bad == 'order': args['order_id'] += 100
    if bad == 'group': args['external_user_id'] = '-101'
    if bad == 'bad_pdf': path.write_bytes(b'broken pdf')
    with factory.begin() as db:
        if bad == 'unpaid': db.get(Order, args['order_id']).status = 'created'
        if bad == 'no_receipt': db.get(Order, args['order_id']).provider_payment_id = None
        if bad == 'not_ready': db.get(Story, args['story_id']).status = 'queued'
    assert reserve_ready_delivery(factory, **args) is None
    with factory() as db:
        assert db.scalar(select(func.count(DeliveryReservation.order_id))) == 0


def test_two_workers_claim_one_order_once(paid, monkeypatch):
    factory, args, second, _, _ = paid
    # Both workers must reach the digest gate after seeing an unreserved order.
    barrier = Barrier(2, timeout=5)
    original = telegram_delivery._checked_digest
    def synchronized_digest(row):
        digest = original(row)
        barrier.wait()
        return digest
    monkeypatch.setattr(telegram_delivery, '_checked_digest', synchronized_digest)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda sid: reserve_ready_delivery(factory, **dict(args, story_id=sid)),
                                (args['story_id'], second)))
    assert sum(r is not None for r in results) == 1
    with factory() as db:
        assert db.scalar(select(func.count(DeliveryReservation.order_id))) == 1
