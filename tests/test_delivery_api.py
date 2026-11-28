"""Authenticated ASGI boundary, real isolated SQLite and synthetic PDF; no Telegram."""
import hashlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles, deregister
from sqlalchemy.orm import sessionmaker

from backend.app import book_release, internal_auth
from backend.app.db import Base
from backend.app.models import Child, Order, Story, User
from backend.app.routers.delivery import delivery_sessions, router
from backend.app.services.telegram_delivery import DeliveryReservation
from backend.app.services.telegram_library import find_book

HEADER = {'X-Legend-Internal-Key': 'synthetic-only-' + 'x' * 40}
ROOT = '/api/payments/telegram/delivery'


@pytest.fixture
def api(tmp_path, monkeypatch):
    @compiles(JSONB, 'sqlite')
    def jsonb(type_, compiler, **kw):
        return 'JSON'
    monkeypatch.setattr(book_release, 'get_settings', lambda: SimpleNamespace(stories_dir=str(tmp_path)))
    monkeypatch.setattr(internal_auth, 'get_settings', lambda: SimpleNamespace(backend_internal_token=HEADER['X-Legend-Internal-Key']))
    engine = create_engine('sqlite:///' + (tmp_path / 'isolated.db').as_posix())
    factory = sessionmaker(bind=engine)
    path = tmp_path / ('b' * 32 + '.pdf')
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
            story = Story(order_id=order.id, child_id=child.id, episode_number=1,
                          status='ready', pdf_url='/files/stories/' + path.name)
            db.add(story); db.flush()
            request = dict(order_id=order.id, story_id=story.id, external_user_id='101',
                           expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[delivery_sessions] = lambda: factory
        with TestClient(app) as client:
            yield client, factory, request
    finally:
        engine.dispose()
        deregister(JSONB)


def test_authenticated_reservation_and_receipt(api):
    client, factory, request = api
    result = client.post(ROOT + '/reserve', json=request, headers=HEADER)
    assert result.status_code == 200
    claim = result.json()['reservation']
    assert claim['recipient'] == '101' and claim['pdf_sha256'] == request['expected_sha256']
    assert client.post(ROOT + '/reserve', json=request, headers=HEADER).json() == {'reservation': None}
    receipt = dict(order_id=request['order_id'], token=claim['token'], message_id=42)
    assert client.post(ROOT + '/acknowledge', json=receipt, headers=HEADER).json() == {'acknowledged': True}
    assert client.post(ROOT + '/acknowledge', json=receipt, headers=HEADER).json() == {'acknowledged': True}
    assert client.post(ROOT + '/acknowledge', json=dict(receipt, message_id=43), headers=HEADER).json() == {'acknowledged': False}
    with factory() as db:
        assert db.get(DeliveryReservation, request['order_id']).telegram_message_id == 42
        assert find_book(db, '101', request['story_id'])['pdf_sha256'] == claim['pdf_sha256']


@pytest.mark.parametrize('bad,status', [('no_auth',401), ('wrong_auth',401), ('wrong_buyer',200),
    ('wrong_digest',200), ('wrong_order',200), ('group',422), ('bool_id',422), ('extra',422)])
def test_rejected_claim_leaves_no_reservation(api, bad, status):
    client, factory, request = api
    headers = HEADER
    if bad == 'no_auth': headers = {}
    if bad == 'wrong_auth': headers = {'X-Legend-Internal-Key':'wrong'}
    if bad == 'wrong_buyer': request['external_user_id'] = '202'
    if bad == 'wrong_digest': request['expected_sha256'] = '0' * 64
    if bad == 'wrong_order': request['order_id'] += 100
    if bad == 'group': request['external_user_id'] = '-101'
    if bad == 'bool_id': request['order_id'] = True
    if bad == 'extra': request['force'] = True
    response = client.post(ROOT + '/reserve', json=request, headers=headers)
    assert response.status_code == status
    if status == 200: assert response.json() == {'reservation': None}
    with factory() as db:
        assert db.scalar(select(func.count(DeliveryReservation.order_id))) == 0


def test_unknown_transport_and_receipt_auth(api):
    client, factory, request = api
    claim = client.post(ROOT + '/reserve', json=request, headers=HEADER).json()['reservation']
    receipt = dict(order_id=request['order_id'], token=claim['token'], message_id=42)
    assert client.post(ROOT + '/acknowledge', json=receipt).status_code == 401
    assert client.post(ROOT + '/acknowledge', json=dict(receipt, token='f'*32), headers=HEADER).json() == {'acknowledged': False}
    assert client.post(ROOT + '/acknowledge', json=dict(receipt, message_id=True), headers=HEADER).status_code == 422
    assert client.post(ROOT + '/reserve', json=request, headers=HEADER).json() == {'reservation': None}
    with factory() as db:
        assert db.get(DeliveryReservation, request['order_id']).telegram_message_id is None
        assert find_book(db, '101', request['story_id']) is not None
        assert find_book(db, '202', request['story_id']) is None


def enable_recovery(factory, request):
    with factory.begin() as db:
        db.get(Order, request['order_id']).meta = {'telegram_auto_delivery_v1': 'enabled'}


def test_recovery_endpoints_auth_and_cursor(api):
    client, factory, request = api
    enable_recovery(factory, request)
    assert client.post(ROOT + '/pending', json={}).status_code == 401
    assert client.post(ROOT + '/reserve-recovered', json=request).status_code == 401
    for cursor in (-1, True, '1', 2147483648):
        assert client.post(ROOT + '/pending', json={'after_story_id': cursor}, headers=HEADER).status_code == 422
    assert client.post(ROOT + '/pending', json={'force': True}, headers=HEADER).status_code == 422
    with factory() as db:
        assert db.scalar(select(func.count(DeliveryReservation.order_id))) == 0


def test_recovered_delivery_opt_in_and_shared_reservation(api):
    client, factory, request = api
    assert client.post(ROOT + '/pending', json={}, headers=HEADER).json()['candidates'] == []
    assert client.post(ROOT + '/reserve-recovered', json=request, headers=HEADER).json() == {'reservation': None}
    enable_recovery(factory, request)
    page = client.post(ROOT + '/pending', json={}, headers=HEADER).json()
    assert len(page['candidates']) == 1 and page['next_after_story_id'] is None
    assert page['candidates'][0]['pdf_sha256'] == request['expected_sha256']
    assert page['candidates'][0]['recipient'] == '101'
    assert client.post(ROOT + '/pending', json={'after_story_id': request['story_id']}, headers=HEADER).json()['candidates'] == []
    claim = client.post(ROOT + '/reserve-recovered', json=request, headers=HEADER).json()['reservation']
    assert claim['recipient'] == '101' and claim['pdf_sha256'] == request['expected_sha256']
    assert client.post(ROOT + '/reserve', json=request, headers=HEADER).json() == {'reservation': None}
    assert client.post(ROOT + '/reserve-recovered', json=request, headers=HEADER).json() == {'reservation': None}
    assert client.post(ROOT + '/pending', json={}, headers=HEADER).json()['candidates'] == []
    with factory() as db:
        assert db.get(DeliveryReservation, request['order_id']).telegram_message_id is None
        assert find_book(db, '101', request['story_id']) is not None


@pytest.mark.parametrize('change', ['revoke', 'sibling', 'unpaid', 'wrong_owner', 'changed_digest'])
def test_recovery_rechecks_stale_candidate(api, change):
    client, factory, request = api
    enable_recovery(factory, request)
    assert len(client.post(ROOT + '/pending', json={}, headers=HEADER).json()['candidates']) == 1
    with factory.begin() as db:
        order = db.get(Order, request['order_id'])
        story = db.get(Story, request['story_id'])
        if change == 'revoke': order.meta = {}
        if change == 'sibling':
            db.add(Story(order_id=order.id, child_id=story.child_id, episode_number=2, status='queued'))
        if change == 'unpaid': order.status = 'created'
        if change == 'wrong_owner': request['external_user_id'] = '202'
        if change == 'changed_digest': request['expected_sha256'] = '0' * 64
    assert client.post(ROOT + '/reserve-recovered', json=request, headers=HEADER).json() == {'reservation': None}
    with factory() as db:
        assert db.scalar(select(func.count(DeliveryReservation.order_id))) == 0


def test_initial_claim_excludes_recovery(api):
    client, factory, request = api
    enable_recovery(factory, request)
    assert client.post(ROOT + '/reserve', json=request, headers=HEADER).json()['reservation'] is not None
    assert client.post(ROOT + '/reserve-recovered', json=request, headers=HEADER).json() == {'reservation': None}
    assert client.post(ROOT + '/pending', json={}, headers=HEADER).json()['candidates'] == []
