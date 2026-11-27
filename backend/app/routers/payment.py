from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..internal_auth import require_internal_token
from ..services.payment_service import confirm_order, create_order
from ..services.telegram_checkout import (
    accept_telegram_receipt,
    check_telegram_invoice,
    create_telegram_invoice,
)
from ..telegram_checkout_schemas import (
    TelegramCheckoutCheck,
    TelegramInvoiceCreate,
    TelegramInvoiceResponse,
    TelegramPrecheckoutResponse,
    TelegramReceiptCreate,
    TelegramReceiptResponse,
)

router = APIRouter(prefix='/api/payments', tags=['payments'], dependencies=[Depends(require_internal_token)])


class OrderCreateRequest(BaseModel):
    external_user_id: str
    channel: str = 'telegram'
    child_id: int
    tariff: str = Field(pattern='^(story|story_with_photo)$')
    provider: str = Field(pattern='^(telegram|link)$')


class OrderConfirmRequest(BaseModel):
    provider_payment_id: str | None = None


@router.post('/telegram/invoices', response_model=TelegramInvoiceResponse)
def create_telegram_invoice_endpoint(payload: TelegramInvoiceCreate, db: Session = Depends(get_db)):
    try:
        return create_telegram_invoice(db, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='Invoice request is invalid') from exc


@router.post('/telegram/precheckout', response_model=TelegramPrecheckoutResponse)
def check_telegram_invoice_endpoint(payload: TelegramCheckoutCheck, db: Session = Depends(get_db)):
    try:
        return check_telegram_invoice(db, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='Invoice or payment details do not match') from exc


@router.post('/telegram/receipts', response_model=TelegramReceiptResponse)
def accept_telegram_receipt_endpoint(payload: TelegramReceiptCreate, db: Session = Depends(get_db)):
    try:
        return accept_telegram_receipt(db, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='Invoice or payment details do not match') from exc


@router.post('/orders')
def create_order_endpoint(payload: OrderCreateRequest, db: Session = Depends(get_db)):
    amount = 350 if payload.tariff == 'story' else 500
    order = create_order(
        db,
        external_user_id=payload.external_user_id,
        channel=payload.channel,
        child_id=payload.child_id,
        tariff=payload.tariff,
        amount_rub=amount,
        provider=payload.provider,
    )
    return {
        'order_id': order.id,
        'status': order.status,
        'amount_rub': order.amount_rub,
        'provider': order.provider,
        'payment_url': order.meta.get('payment_url'),
        'instructions': order.meta.get('instructions'),
    }


@router.post('/orders/{order_id}/confirm')
def confirm_order_endpoint(order_id: int, payload: OrderConfirmRequest, db: Session = Depends(get_db)):
    # No payment-provider signature is verified here. This legacy endpoint
    # must not mark an order as paid until a verified webhook is implemented.
    raise HTTPException(status_code=503, detail="Manual payment confirmation is disabled")
