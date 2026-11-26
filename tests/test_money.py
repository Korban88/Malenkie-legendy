"""Typed amounts and persisted receipt metadata, with no network or payment calls."""
from dataclasses import FrozenInstanceError
from decimal import Decimal
import json
import operator
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles, deregister
from sqlalchemy.orm import Session

from backend.app.db import Base
from backend.app.models import Child, Order, Story, User
from backend.app.money import Money
from backend.app.services import payment_service, story_service


INVALID_AMOUNTS = [True, False, 1.0, 1.5, float('nan'), float('inf'),
                   Decimal('1'), '150', None, Money('XTR', 150)]


@pytest.mark.parametrize('currency', ['RUB', 'XTR'])
@pytest.mark.parametrize('amount', INVALID_AMOUNTS)
def test_money_rejects_non_integer_amounts(currency, amount):
    with pytest.raises(TypeError, match='integer'):
        Money(currency, amount)


@pytest.mark.parametrize('currency', ['RUB', 'XTR'])
@pytest.mark.parametrize('amount', [0, -1, -150])
def test_money_rejects_non_positive_amounts(currency, amount):
    with pytest.raises(ValueError, match='positive'):
        Money(currency, amount)


@pytest.mark.parametrize('currency', ['USD', 'rub', 'xtr', '', None, 1, True])
def test_money_rejects_unknown_currencies(currency):
    with pytest.raises(ValueError, match='currency'):
        Money(currency, 150)


@pytest.mark.parametrize('amount', INVALID_AMOUNTS + [0, -1])
def test_legacy_adapter_rejects_invalid_amount_before_scaling(amount):
    with pytest.raises((TypeError, ValueError)):
        Money.from_rubles(amount)


def test_money_is_immutable_and_metadata_is_independent():
    money = Money('XTR', 150)
    for field, value in [('currency', 'RUB'), ('minor_units', 200)]:
        with pytest.raises(FrozenInstanceError):
            setattr(money, field, value)
    metadata = money.to_metadata()
    metadata['currency'] = 'RUB'
    assert money == Money('XTR', 150)
    assert hash(money) == hash(Money('XTR', 150))
    assert money.to_metadata() == {'version': 1, 'currency': 'XTR', 'minor_units': 150}


@pytest.mark.parametrize('operation', [operator.add, operator.sub, operator.mul, operator.truediv])
def test_units_cannot_be_mixed_or_converted(operation):
    rub, xtr = Money('RUB', 150), Money('XTR', 150)
    assert rub != xtr
    assert Money.from_rubles(150) == Money('RUB', 15000)
    for left, right in [(rub, xtr), (xtr, rub), (xtr, 100)]:
        with pytest.raises(TypeError):
            operation(left, right)


@pytest.fixture
def receipt_engine():
    @compiles(JSONB, 'sqlite')
    def jsonb(type_, compiler, **kw):
        return 'JSON'

    engine = create_engine('sqlite:///:memory:')
    try:
        Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()
        deregister(JSONB)


@pytest.mark.parametrize('amount_rub', [1, 150, 200])
def test_legacy_order_persists_kopeks_and_preserves_fields(receipt_engine, amount_rub):
    with Session(receipt_engine) as db:
        user = User(external_id='synthetic-rub-buyer', channel='web')
        db.add(user)
        db.flush()
        child = Child(user_id=user.id, name='Synthetic', age=7)
        db.add(child)
        db.commit()
        order = payment_service.create_order(
            db, user.external_id, 'web', child.id, 'story', amount_rub, 'legacy-test',
        )
        order_id, user_id, child_id = order.id, user.id, child.id

    with Session(receipt_engine) as restarted:
        receipt = restarted.get(Order, order_id)
        money = receipt.meta['money_v1']
        assert money == {'version': 1, 'currency': 'RUB', 'minor_units': amount_rub * 100}
        assert type(money['minor_units']) is int
        assert receipt.amount_rub == amount_rub
        assert (receipt.user_id, receipt.child_id) == (user_id, child_id)
        assert (receipt.provider, receipt.tariff, receipt.status) == ('legacy-test', 'story', 'created')
        assert receipt.meta['payment_url'] == f'https://pay.example/legacy-test/{user_id}/{child_id}/story'
        assert receipt.meta['instructions'].endswith('/api/payments/confirm')


@pytest.mark.parametrize('amount_rub', INVALID_AMOUNTS + [0, -1])
def test_invalid_legacy_amount_is_rejected_before_database_work(amount_rub):
    db = Mock(spec=Session)
    with pytest.raises((TypeError, ValueError)):
        payment_service.create_order(db, 'synthetic', 'web', 1, 'story', amount_rub, 'legacy-test')
    assert not db.method_calls


@pytest.mark.parametrize('photo_enabled, amount, tariff', [
    (False, 150, 'story'), (True, 200, 'story_with_photo'),
])
def test_stars_receipt_persists_whole_xtr_before_generation_and_survives_replay(
    receipt_engine, monkeypatch, photo_enabled, amount, tariff,
):
    def stop_generation(_):
        raise RuntimeError('synthetic generation stop')

    monkeypatch.setattr(story_service, 'get_settings', lambda: SimpleNamespace(force_episode_one=False))
    monkeypatch.setattr(story_service, 'generate_story_payload', stop_generation)
    images = Mock(side_effect=AssertionError('Unexpected image provider call'))
    pdf = Mock(side_effect=AssertionError('Unexpected PDF call'))
    monkeypatch.setattr(story_service, 'generate_images', images)
    monkeypatch.setattr(story_service, 'generate_pdf', pdf)
    payload = {'external_user_id': 'synthetic-stars-buyer', 'child_name': 'Synthetic',
               'age': 7, 'photo_enabled': photo_enabled,
               'telegram_payment_charge_id': 'synthetic-stars-charge'}
    with Session(receipt_engine) as db:
        with pytest.raises(RuntimeError, match='synthetic generation stop'):
            story_service.generate_story(db, payload)

    with Session(receipt_engine) as restarted:
        receipt = restarted.scalar(select(Order))
        meta = json.loads(json.dumps(receipt.meta))
        assert meta['money_v1'] == {'version': 1, 'currency': 'XTR', 'minor_units': amount}
        assert type(meta['money_v1']['minor_units']) is int
        assert meta['currency'] == 'XTR'
        assert meta['questionnaire_v1']['version'] == 1
        assert meta['questionnaire_v1']['photo_enabled'] is photo_enabled
        assert receipt.amount_rub == amount
        assert (receipt.provider, receipt.status, receipt.tariff) == ('telegram_stars', 'paid', tariff)
        assert receipt.provider_payment_id == payload['telegram_payment_charge_id']
        replay = story_service.generate_story(restarted, {**payload, 'photo_enabled': not photo_enabled})
        assert replay.order_id == receipt.id
        restarted.refresh(receipt)
        assert receipt.meta == meta
        assert restarted.scalar(select(func.count()).select_from(Order)) == 1
        assert restarted.scalar(select(func.count()).select_from(Story)) == 1
    images.assert_not_called()
    pdf.assert_not_called()
