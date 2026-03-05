from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Order, User


def create_order(
    db: Session,
    external_user_id: str,
    channel: str,
    child_id: int,
    tariff: str,
    amount_rub: int,
    provider: str,
) -> Order:
    user = db.scalar(select(User).where(User.external_id == external_user_id))
    if not user:
        user = User(external_id=external_user_id, channel=channel)
        db.add(user)
        db.flush()

    order = Order(
        user_id=user.id,
        child_id=child_id,
        tariff=tariff,
        amount_rub=amount_rub,
        provider=provider,
        status='created',
        meta={
            'payment_url': f'https://pay.example/{provider}/{user.id}/{child_id}/{tariff}',
            'instructions': 'После оплаты вызовите /api/payments/confirm',
        },
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def confirm_order(db: Session, order_id: int, provider_payment_id: str | None = None) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise ValueError('Order not found')
    order.status = 'paid'
    order.provider_payment_id = provider_payment_id
    db.commit()
    db.refresh(order)
    return order
