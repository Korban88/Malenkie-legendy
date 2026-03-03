from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.payment_service import confirm_order, create_order

router = APIRouter(prefix='/api/payments', tags=['payments'])


class OrderCreateRequest(BaseModel):
    external_user_id: str
    channel: str = 'telegram'
    child_id: int
    tariff: str = Field(pattern='^(story|story_with_photo)$')
    provider: str = Field(pattern='^(telegram|link)$')


class OrderConfirmRequest(BaseModel):
    provider_payment_id: str | None = None


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
        'payment_url': order.metadata.get('payment_url'),
        'instructions': order.metadata.get('instructions'),
    }


@router.post('/orders/{order_id}/confirm')
def confirm_order_endpoint(order_id: int, payload: OrderConfirmRequest, db: Session = Depends(get_db)):
    try:
        order = confirm_order(db, order_id, payload.provider_payment_id)
        return {'order_id': order.id, 'status': order.status}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
