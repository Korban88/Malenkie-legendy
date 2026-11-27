"""Persist a Telegram invoice before displaying it and a receipt before generation.

Only the authenticated bot may submit a successful-payment event. This module
does not call providers or Telegram, start generation, or provide a delivery
outbox. Existing Order metadata keeps this change free of schema migrations.
"""

import hashlib
import hmac
import json
import re
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Order, Story, User
from ..money import Money
from ..telegram_checkout_schemas import (
    TelegramCheckoutCheck,
    TelegramInvoiceCreate,
    TelegramReceiptCreate,
)
from .story_service import (
    PDF_PENDING_STATES,
    _paid_questionnaire,
    _serialize_paid_generation,
    get_or_create_child,
    get_or_create_user,
)


_PAYLOAD = re.compile(r'^lk1:([1-9][0-9]{0,18}):([a-f0-9]{32})$')
_PRICES_XTR = {False: 150, True: 200}


def _metadata(order: Order) -> tuple[dict, dict, Money]:
    meta = order.meta or {}
    invoice = meta.get('telegram_invoice_v1')
    snapshot = meta.get('questionnaire_v1')
    money_data = meta.get('money_v1')
    if (not isinstance(invoice, dict) or invoice.get('version') != 1
            or not isinstance(snapshot, dict) or snapshot.get('version') != 1
            or not isinstance(money_data, dict) or money_data.get('version') != 1):
        raise ValueError('Invoice metadata is invalid')
    nonce = invoice.get('nonce')
    if not isinstance(nonce, str) or not re.fullmatch(r'[a-f0-9]{32}', nonce):
        raise ValueError('Invoice metadata is invalid')
    money = Money(money_data.get('currency'), money_data.get('minor_units'))
    if money.currency != 'XTR' or order.amount_rub != money.minor_units:
        raise ValueError('Invoice money is invalid')
    return invoice, snapshot, money


def _invoice_response(order: Order) -> dict:
    invoice, snapshot, money = _metadata(order)
    return {
        'order_id': order.id,
        'invoice_payload': f"lk1:{order.id}:{invoice['nonce']}",
        'currency': 'XTR',
        'total_amount': money.minor_units,
        'child_name': snapshot['child_name'],
        'photo_enabled': snapshot['photo_enabled'],
    }


def create_telegram_invoice(db: Session, payload: dict) -> dict:
    request = TelegramInvoiceCreate.model_validate(payload)
    data = request.model_dump()
    # Match generation's buyer lock so invoice creation and recovery cannot race
    # the creation of the same User or Child on PostgreSQL.
    _serialize_paid_generation(db, data)
    user = get_or_create_user(db, request.external_user_id, 'telegram')
    if user.channel != 'telegram':
        raise ValueError('Invoice owner is invalid')
    digest = hashlib.sha256(json.dumps(
        {key: value for key, value in data.items() if key != 'client_request_id'},
        sort_keys=True, ensure_ascii=False, separators=(',', ':'),
    ).encode('utf-8')).hexdigest()
    if request.client_request_id:
        existing = db.scalar(select(Order).where(
            Order.user_id == user.id,
            Order.provider == 'telegram_stars',
            Order.meta['telegram_invoice_v1']['client_request_id'].as_string()
            == request.client_request_id,
        ).with_for_update())
        if existing is not None:
            invoice, _, _ = _metadata(existing)
            if not hmac.compare_digest(invoice.get('request_sha256', ''), digest):
                raise ValueError('Invoice request cannot change after it is saved')
            if existing.status not in ('created', 'paid'):
                raise ValueError('Invoice is no longer available')
            response = _invoice_response(existing)
            db.commit()
            return response

    child = get_or_create_child(db, data, user.id)
    money = Money('XTR', _PRICES_XTR[request.photo_enabled])
    order = Order(
        user_id=user.id,
        child_id=child.id,
        provider='telegram_stars',
        tariff='story_with_photo' if request.photo_enabled else 'story',
        amount_rub=money.minor_units,  # Compatibility: legacy column stores XTR.
        status='created',
        provider_payment_id=None,
        meta={
            'currency': 'XTR',
            'money_v1': money.to_metadata(),
            'telegram_invoice_v1': {
                'version': 1,
                'nonce': uuid.uuid4().hex,
                'client_request_id': request.client_request_id,
                'request_sha256': digest,
                'photo_file_id': request.photo_file_id,
                'photo_consent': request.photo_consent,
            },
        },
    )
    db.add(order)
    db.flush()
    snapshot = _paid_questionnaire(order, child, data)
    snapshot['photo_consent'] = request.photo_consent
    order.meta = {**order.meta, 'questionnaire_v1': snapshot}
    response = _invoice_response(order)
    # Sending an invoice is only permitted after this commit succeeds.
    db.commit()
    return response


def _checked_invoice(db: Session, request: TelegramCheckoutCheck) -> Order:
    match = _PAYLOAD.fullmatch(request.invoice_payload)
    if match is None or int(match.group(1)) > 2_147_483_647:
        raise ValueError('Invoice or payment details do not match')
    order = db.scalar(select(Order).where(
        Order.id == int(match.group(1)),
        Order.provider == 'telegram_stars',
    ).with_for_update())
    if order is None:
        raise ValueError('Invoice or payment details do not match')
    invoice, _, money = _metadata(order)
    owner = db.get(User, order.user_id)
    if (owner is None or owner.channel != 'telegram'
            or owner.external_id != request.external_user_id
            or not hmac.compare_digest(invoice['nonce'], match.group(2))
            or money.currency != request.currency
            or money.minor_units != request.total_amount):
        raise ValueError('Invoice or payment details do not match')
    return order


def check_telegram_invoice(db: Session, payload: dict) -> dict:
    request = TelegramCheckoutCheck.model_validate(payload)
    order = _checked_invoice(db, request)
    if order.status != 'created' or order.provider_payment_id is not None:
        raise ValueError('Invoice is already paid or no longer available')
    return {'ok': True, 'order_id': order.id}


def accept_telegram_receipt(db: Session, payload: dict) -> dict:
    request = TelegramReceiptCreate.model_validate(payload)
    data = request.model_dump()
    # Charge lock also serializes attempts to bind one charge to two invoices,
    # including invoices of different buyers. The lock ordering matches generate.
    _serialize_paid_generation(db, data)
    order = _checked_invoice(db, request)
    charge = request.telegram_payment_charge_id
    if order.status not in ('created', 'paid'):
        raise ValueError('Invoice is no longer available')
    replayed = order.status == 'paid'
    if replayed:
        if order.provider_payment_id != charge:
            raise ValueError('Invoice is bound to a different payment')
    else:
        if order.provider_payment_id is not None:
            raise ValueError('Invoice payment state is invalid')
        other = db.scalar(select(Order.id).where(
            Order.provider == 'telegram_stars',
            Order.provider_payment_id == charge,
            Order.id != order.id,
        ))
        if other is not None:
            raise ValueError('Payment is bound to a different invoice')
        order.provider_payment_id = charge
        order.status = 'paid'

    invoice, snapshot, _ = _metadata(order)
    generation = {key: value for key, value in snapshot.items() if key != 'version'}
    generation.update({
        'external_user_id': request.external_user_id,
        'channel': 'telegram',
        'child_id': order.child_id,
        'order_id': order.id,
        'telegram_payment_charge_id': charge,
    })
    # Only the validated paid invoice may identify its ready story.
    # Recovery must not require the original photo or provider work.
    saved_story = db.execute(select(Story.id, Story.status).where(
        Story.order_id == order.id,
        Story.child_id == order.child_id,
        Story.status.in_(('ready', *PDF_PENDING_STATES)),
    )).one_or_none()
    if saved_story is not None and saved_story.status in PDF_PENDING_STATES:
        generation['resume_pdf_only'] = True
    response = {
        'order_id': order.id,
        'child_id': order.child_id,
        'status': 'paid',
        'ready_story_id': saved_story.id if saved_story is not None and saved_story.status == 'ready' else None,
        'replayed': replayed,
        'generation_payload': generation,
        'photo_file_id': invoice.get('photo_file_id'),
    }
    try:
        # Receipt commit precedes any provider request or success acknowledgement.
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError('Payment is bound to a different invoice') from exc
    return response
