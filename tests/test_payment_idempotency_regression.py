"""Regression checks for duplicate Telegram Stars charges and story access.

This is a narrow service-level regression; a live Telegram test bot and PostgreSQL
transaction/concurrency tests remain mandatory before the draft PR can merge.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.app.models import Order
from backend.app.services import story_service


class FakeSession:
    def __init__(self, scalar_results=(), order=None, child=None):
        self._scalar_results = iter(scalar_results)
        self.order = order
        self.child = child
        self.added = []

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name='sqlite'))

    def commit(self):
        pass

    def scalar(self, stmt):
        return next(self._scalar_results)

    def get(self, model, pk):
        if model is Order:
            return self.order
        if model.__name__ == 'Child':
            return self.child
        raise AssertionError(f'unexpected get: {model.__name__}')

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        for obj in self.added:
            if isinstance(obj, Order) and obj.id is None:
                obj.id = 991


def _user_child():
    return SimpleNamespace(id=10), SimpleNamespace(id=99, user_id=10)


def test_repeat_paid_charge_reuses_order_and_story_without_new_order():
    user, child = _user_child()
    order = SimpleNamespace(
        id=71, provider='telegram_stars', provider_payment_id='tg-charge-1',
        user_id=10, child_id=99, status='paid',
    )
    story = SimpleNamespace(id=881, order_id=71, child_id=99, status='ready')
    db = FakeSession(scalar_results=[order, order, story], order=order)

    with patch.object(story_service, 'get_or_create_user', return_value=user), \
         patch.object(story_service, 'get_or_create_child', return_value=child):
        actual = story_service.generate_story(db, {
            'external_user_id': 'telegram-user-10',
            'child_name': 'Тест',
            'age': 8,
            'telegram_payment_charge_id': 'tg-charge-1',
        })

    assert actual is story
    assert not db.added, 'duplicate payment charge must not create another Order'


def test_replayed_charge_cannot_be_claimed_by_another_customer():
    user, child = _user_child()
    somebody_elses_order = SimpleNamespace(
        id=73, provider='telegram_stars', provider_payment_id='tg-charge-2',
        user_id=999, child_id=99, status='paid',
    )
    db = FakeSession(scalar_results=[somebody_elses_order], order=somebody_elses_order)
    with patch.object(story_service, 'get_or_create_user', return_value=user), \
         patch.object(story_service, 'get_or_create_child', return_value=child):
        with pytest.raises(ValueError, match='another user or child'):
            story_service.generate_story(db, {
                'external_user_id': 'telegram-user-10',
                'child_name': 'Тест',
                'age': 8,
                'telegram_payment_charge_id': 'tg-charge-2',
            })
    assert not db.added


def test_child_id_cannot_be_used_by_other_owner():
    stranger_child = SimpleNamespace(id=99, user_id=123)
    db = FakeSession(child=stranger_child)
    with pytest.raises(ValueError, match='does not belong'):
        story_service.get_or_create_child(db, {'child_id': 99}, user_id=10)


def test_payment_pair_has_schema_uniqueness_constraint():
    names = {c.name for c in Order.__table__.constraints}
    assert 'uq_order_provider_payment' in names
