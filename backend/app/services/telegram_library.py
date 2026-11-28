"""Read-only access to previously purchased Telegram books."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Child, Order, Story, User


PAGE_SIZE = 8


def _owned_books(external_user_id: str):
    return (
        select(Story.id, Story.episode_number, Story.title, Story.pdf_url)
        .join(Order, Story.order_id == Order.id)
        .join(Child, Story.child_id == Child.id)
        .join(User, Order.user_id == User.id)
        .where(
            User.channel == 'telegram',
            User.external_id == external_user_id,
            Child.user_id == User.id,
            Order.child_id == Child.id,
            Order.provider == 'telegram_stars',
            Order.status == 'paid',
            Order.provider_payment_id.is_not(None),
            Order.provider_payment_id != '',
            Story.status == 'ready',
            Story.pdf_url.is_not(None),
            Story.pdf_url != '',
        )
    )


def list_books(db: Session, external_user_id: str, before_story_id: int | None) -> dict:
    query = _owned_books(external_user_id)
    if before_story_id is not None:
        query = query.where(Story.id < before_story_id)
    rows = db.execute(query.order_by(Story.id.desc()).limit(PAGE_SIZE + 1)).all()
    return {
        'books': [
            {'story_id': row.id, 'episode_number': row.episode_number, 'title': row.title}
            for row in rows[:PAGE_SIZE]
        ],
        'next_before_story_id': rows[PAGE_SIZE - 1].id if len(rows) > PAGE_SIZE else None,
    }


def find_book(db: Session, external_user_id: str, story_id: int) -> dict | None:
    row = db.execute(_owned_books(external_user_id).where(Story.id == story_id)).one_or_none()
    if row is None:
        return None
    return {'episode_number': row.episode_number, 'pdf_url': row.pdf_url}
