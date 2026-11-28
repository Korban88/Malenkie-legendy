"""Durable reservation for a single automatic document attempt per paid order.

This is a storage primitive, not a worker or a backfill. The caller must opt in
an exact order/story, preflight its transport, and compare the downloaded bytes
with the reserved digest before sending to the verified private recipient.
Once reserved, an unknown transport outcome (including a crash before send)
never becomes eligible automatically. Explicit /books retrieval stays separate.
"""
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..models import Order, Story
from .telegram_library import _checked_digest, _owned_books


class DeliveryReservation(Base):
    __tablename__ = 'telegram_delivery_reservations'

    order_id: Mapped[int] = mapped_column(ForeignKey('orders.id'), primary_key=True)
    story_id: Mapped[int] = mapped_column(ForeignKey('stories.id'), unique=True)
    token: Mapped[str] = mapped_column(String(32))
    pdf_sha256: Mapped[str] = mapped_column(String(64))
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


@dataclass(frozen=True)
class ReservedDocument:
    order_id: int
    story_id: int
    token: str
    recipient: str
    pdf_url: str
    pdf_sha256: str


def reserve_ready_delivery(session_factory, *, order_id: int, story_id: int,
                           external_user_id: str) -> ReservedDocument | None:
    """Use a dedicated transaction; return a reservation only after commit."""
    if (type(order_id) is not int or order_id <= 0 or type(story_id) is not int
            or story_id <= 0 or not isinstance(external_user_id, str)
            or not external_user_id.isascii() or not external_user_id.isdecimal()
            or external_user_id.startswith('0')):
        return None
    with session_factory() as db:
        existing = select(DeliveryReservation.order_id).where(or_(
            DeliveryReservation.order_id == order_id,
            DeliveryReservation.story_id == story_id,
        ))
        if db.scalar(existing) is not None:
            return None
        row = db.execute(_owned_books(external_user_id).where(
            Story.id == story_id, Order.id == order_id,
        )).one_or_none()
        if row is None:
            return None
        digest = _checked_digest(row)
        if digest is None:
            return None
        token = uuid4().hex
        db.add(DeliveryReservation(order_id=order_id, story_id=story_id,
                                   token=token, pdf_sha256=digest))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            # Only a competing reservation is a harmless duplicate; do not
            # mask a foreign-key failure or unrelated storage problem.
            if db.scalar(existing) is not None:
                return None
            raise
        return ReservedDocument(order_id, story_id, token, external_user_id,
                                row.pdf_url, digest)


def acknowledge_delivery(session_factory, *, order_id: int, token: str,
                         message_id: int) -> bool:
    """Persist a positive receipt; never overwrite it with another message ID.

    The transport adapter must first verify the returned private chat and
    document identity. No error or timeout may call this function as success.
    """
    if type(message_id) is not int or not 0 < message_id <= 2147483647:
        return False
    with session_factory() as db:
        match = (DeliveryReservation.order_id == order_id,
                 DeliveryReservation.token == token)
        changed = db.execute(update(DeliveryReservation).where(
            *match, DeliveryReservation.telegram_message_id.is_(None),
        ).values(telegram_message_id=message_id)).rowcount
        if changed != 1:
            stored = db.scalar(select(DeliveryReservation.telegram_message_id).where(*match))
            return stored == message_id
        db.commit()
        return True
