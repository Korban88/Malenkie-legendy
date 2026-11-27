"""Durable pre-payment questionnaire and receipts, with no live charges/providers."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from threading import Barrier
from unittest.mock import Mock
import uuid

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url
from sqlalchemy.ext.compiler import compiles, deregister
from sqlalchemy.orm import Session

from backend.app.db import Base
from backend.app.models import Child, Order, Story, User
from backend.app.services.telegram_checkout import (
    accept_telegram_receipt,
    check_telegram_invoice,
    create_telegram_invoice,
)


def questionnaire(**overrides):
    return {
        'external_user_id': 'synthetic-checkout-buyer',
        'child_name': 'Тест',
        'age': 7,
        'purpose': 'friendship',
        'favorite_animal': 'лиса',
        'favorite_color': 'зелёный',
        'favorite_place': 'озеро',
        'client_request_id': 'a' * 32,
        **overrides,
    }


def payment(invoice, **overrides):
    return {
        'invoice_payload': invoice['invoice_payload'],
        'external_user_id': 'synthetic-checkout-buyer',
        'currency': 'XTR',
        'total_amount': invoice['total_amount'],
        **overrides,
    }


@pytest.fixture
def checkout_engine(tmp_path):
    @compiles(JSONB, 'sqlite')
    def jsonb(type_, compiler, **kw):
        return 'JSON'

    engine = create_engine('sqlite:///' + (tmp_path / 'checkout.db').as_posix())
    try:
        Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()
        deregister(JSONB)


def test_invoice_and_paid_snapshot_survive_new_sessions(checkout_engine):
    with Session(checkout_engine) as db:
        invoice = create_telegram_invoice(db, questionnaire())
    assert invoice['currency'] == 'XTR'
    assert invoice['total_amount'] == 150
    assert len(invoice['invoice_payload'].encode()) < 128

    with Session(checkout_engine) as restarted:
        order = restarted.get(Order, invoice['order_id'])
        assert order.status == 'created'
        assert order.provider_payment_id is None
        snapshot = dict(order.meta['questionnaire_v1'])
        assert snapshot['purpose'] == 'friendship'
        child = restarted.get(Child, order.child_id)
        child.favorite_animal = 'изменено после счёта'
        restarted.commit()
        assert check_telegram_invoice(restarted, payment(invoice)) == {
            'ok': True, 'order_id': order.id,
        }

    paid = {**payment(invoice), 'telegram_payment_charge_id': 'synthetic-charge-checkout'}
    with Session(checkout_engine) as restarted:
        receipt = accept_telegram_receipt(restarted, paid)
        assert receipt['replayed'] is False
    with Session(checkout_engine) as observer:
        order = observer.get(Order, invoice['order_id'])
        assert order.status == 'paid'
        assert order.provider_payment_id == paid['telegram_payment_charge_id']
        assert order.meta['questionnaire_v1'] == snapshot
        assert receipt['generation_payload']['favorite_animal'] == 'лиса'
        assert receipt['generation_payload']['purpose'] == 'friendship'
        assert receipt['generation_payload']['child_id'] == order.child_id
        assert receipt['generation_payload']['order_id'] == order.id
        assert receipt['photo_file_id'] is None
        assert 'version' not in receipt['generation_payload']
        assert observer.scalar(select(func.count()).select_from(Order)) == 1


def test_invoice_creation_replay_is_idempotent_and_cannot_change_snapshot(checkout_engine):
    with Session(checkout_engine) as db:
        first = create_telegram_invoice(db, questionnaire())
    with Session(checkout_engine) as restarted:
        assert create_telegram_invoice(restarted, questionnaire()) == first
        with pytest.raises(ValueError, match='cannot change'):
            create_telegram_invoice(restarted, questionnaire(favorite_animal='тигр'))
    with Session(checkout_engine) as observer:
        assert observer.scalar(select(func.count()).select_from(Order)) == 1
        assert observer.scalar(select(func.count()).select_from(Child)) == 1


@pytest.mark.parametrize('changes', [
    {'external_user_id': 'other-buyer'},
    {'total_amount': 1},
    {'currency': 'RUB'},
    {'invoice_payload': 'lk1:1:' + '0' * 32},
    {'invoice_payload': 'not-an-invoice'},
    {'invoice_payload': 'lk1:9999999999999999999:' + '0' * 32},
    {'total_amount': True},
    {'total_amount': 150.0},
    {'total_amount': '150'},
])
def test_invalid_payment_cannot_mark_invoice_paid(checkout_engine, changes):
    with Session(checkout_engine) as db:
        invoice = create_telegram_invoice(db, questionnaire())
    request = payment(invoice, **changes)
    with Session(checkout_engine) as db:
        with pytest.raises(ValueError):
            check_telegram_invoice(db, request)
    with Session(checkout_engine) as db:
        with pytest.raises(ValueError):
            accept_telegram_receipt(db, {
                **request, 'telegram_payment_charge_id': 'synthetic-invalid-charge',
            })
    with Session(checkout_engine) as db:
        order = db.get(Order, invoice['order_id'])
        assert order.status == 'created'
        assert order.provider_payment_id is None


def test_receipt_replay_and_charge_binding(checkout_engine):
    with Session(checkout_engine) as db:
        first = create_telegram_invoice(db, questionnaire())
        second = create_telegram_invoice(db, questionnaire(client_request_id='b' * 32))
    first_payment = {**payment(first), 'telegram_payment_charge_id': 'synthetic-bound-charge'}
    with Session(checkout_engine) as db:
        receipt = accept_telegram_receipt(db, first_payment)
    with Session(checkout_engine) as db:
        replay = accept_telegram_receipt(db, first_payment)
        assert replay == {**receipt, 'replayed': True}
        with pytest.raises(ValueError, match='already paid'):
            check_telegram_invoice(db, payment(first))
    with Session(checkout_engine) as db:
        with pytest.raises(ValueError, match='different payment'):
            accept_telegram_receipt(db, {
                **first_payment, 'telegram_payment_charge_id': 'different-charge',
            })
    with Session(checkout_engine) as db:
        with pytest.raises(ValueError, match='different invoice'):
            accept_telegram_receipt(db, {
                **payment(second), 'telegram_payment_charge_id': 'synthetic-bound-charge',
            })
    with Session(checkout_engine) as db:
        assert db.get(Order, first['order_id']).status == 'paid'
        assert db.get(Order, second['order_id']).status == 'created'


def test_photo_reference_with_consent_survives_without_raw_bytes(checkout_engine):
    with Session(checkout_engine) as db:
        invoice = create_telegram_invoice(db, questionnaire(
            photo_enabled=True, photo_consent=True, photo_file_id='synthetic-telegram-file',
        ))
    assert invoice['total_amount'] == 200
    with Session(checkout_engine) as db:
        receipt = accept_telegram_receipt(db, {
            **payment(invoice), 'telegram_payment_charge_id': 'synthetic-photo-charge',
        })
    with Session(checkout_engine) as db:
        stored = db.get(Order, invoice['order_id']).meta
        assert stored['telegram_invoice_v1']['photo_file_id'] == 'synthetic-telegram-file'
        assert 'photo_base64' not in json.dumps(stored)
    assert receipt['photo_file_id'] == 'synthetic-telegram-file'
    assert receipt['generation_payload']['photo_enabled'] is True
    assert receipt['generation_payload']['photo_consent'] is True
    assert 'photo_file_id' not in receipt['generation_payload']


@pytest.mark.parametrize('changes', [
    {'photo_enabled': True},
    {'photo_enabled': True, 'photo_file_id': 'ref', 'photo_consent': False},
    {'photo_file_id': 'ref'},
    {'photo_base64': 'RAW_PHOTO_BYTES_MUST_NOT_PERSIST'},
])
def test_invalid_photo_request_fails_before_database_work(changes):
    db = Mock(spec=Session)
    with pytest.raises(ValueError):
        create_telegram_invoice(db, questionnaire(**changes))
    assert db.method_calls == []


def test_invoice_cannot_reuse_another_buyers_child(checkout_engine):
    with Session(checkout_engine) as db:
        first = create_telegram_invoice(db, questionnaire())
        child_id = db.get(Order, first['order_id']).child_id
    with Session(checkout_engine) as db:
        with pytest.raises(ValueError, match='does not belong'):
            create_telegram_invoice(db, questionnaire(
                external_user_id='other-buyer', child_id=child_id,
            ))
    with Session(checkout_engine) as db:
        assert db.scalar(select(func.count()).select_from(Order)) == 1
        assert db.scalar(select(func.count()).select_from(User)) == 1


@pytest.fixture
def checkout_postgres():
    dsn = os.environ.get('LEGENDKIDS_TEST_POSTGRES_DSN')
    if not dsn:
        pytest.skip('Dedicated PostgreSQL checkout fixture not configured')
    url = make_url(dsn)
    if (url.drivername != 'postgresql+psycopg'
            or url.host not in ('localhost', '127.0.0.1')
            or url.username != 'legendkids_test' or url.database != 'legendkids_test'
            or url.query):
        pytest.fail('Refusing a non-isolated PostgreSQL fixture')
    schema = 'lk_checkout_' + uuid.uuid4().hex
    admin = create_engine(url)
    engine = None
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(url, connect_args={
            'options': f'-csearch_path={schema} -cstatement_timeout=15000',
        })
        Base.metadata.create_all(engine)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        try:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            admin.dispose()


def test_postgres_concurrent_receipts_return_one_paid_order(checkout_postgres):
    with Session(checkout_postgres) as db:
        invoice = create_telegram_invoice(db, questionnaire())
    request = {**payment(invoice), 'telegram_payment_charge_id': 'synthetic-concurrent-charge'}
    barrier = Barrier(2)

    def accept():
        with Session(checkout_postgres) as db:
            barrier.wait(timeout=5)
            return accept_telegram_receipt(db, request)

    with ThreadPoolExecutor(max_workers=2) as workers:
        receipts = list(workers.map(lambda _: accept(), range(2)))
    assert {item['order_id'] for item in receipts} == {invoice['order_id']}
    assert sorted(item['replayed'] for item in receipts) == [False, True]
    with Session(checkout_postgres) as observer:
        assert observer.scalar(select(func.count()).select_from(Order)) == 1
        assert observer.get(Order, invoice['order_id']).status == 'paid'


def test_postgres_concurrent_invoice_retries_use_one_snapshot(checkout_postgres):
    barrier = Barrier(2)

    def create():
        with Session(checkout_postgres) as db:
            barrier.wait(timeout=5)
            return create_telegram_invoice(db, questionnaire())

    with ThreadPoolExecutor(max_workers=2) as workers:
        invoices = list(workers.map(lambda _: create(), range(2)))
    assert invoices[0] == invoices[1]
    with Session(checkout_postgres) as observer:
        assert observer.scalar(select(func.count()).select_from(Order)) == 1
        assert observer.scalar(select(func.count()).select_from(User)) == 1
        assert observer.scalar(select(func.count()).select_from(Child)) == 1


def test_ready_story_id_is_bound_to_validated_paid_invoice(checkout_engine):
    with Session(checkout_engine) as db:
        invoice = create_telegram_invoice(db, questionnaire())
        other = create_telegram_invoice(db, questionnaire(
            external_user_id='other-buyer', client_request_id='c' * 32,
        ))
        paid = {**payment(invoice), 'telegram_payment_charge_id': 'synthetic-ready-charge'}
        receipt = accept_telegram_receipt(db, paid)
        assert receipt['ready_story_id'] is None
        db.add(Story(order_id=other['order_id'],
                     child_id=db.get(Order, other['order_id']).child_id,
                     episode_number=1, status='ready'))
        db.add(Story(order_id=invoice['order_id'], child_id=receipt['child_id'],
                     episode_number=1, status='failed'))
        db.commit()
    with Session(checkout_engine) as db:
        assert accept_telegram_receipt(db, paid)['ready_story_id'] is None
        story = db.scalar(select(Story).where(Story.order_id == invoice['order_id']))
        story.status = 'ready'
        db.commit()
        story_id = story.id
    with Session(checkout_engine) as db:
        assert accept_telegram_receipt(db, paid)['ready_story_id'] == story_id
        with pytest.raises(ValueError):
            accept_telegram_receipt(db, {**paid, 'external_user_id': 'other-buyer'})
    with Session(checkout_engine) as db:
        with pytest.raises(ValueError, match='different payment'):
            accept_telegram_receipt(db, {**paid, 'telegram_payment_charge_id': 'wrong-charge'})
