"""Read-only access to previously purchased Telegram books."""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..book_release import require_complete_pdf
from ..models import Child, Order, Story, User


PAGE_SIZE = 8
log = logging.getLogger(__name__)


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


def _checked_digest(row) -> str | None:
    try:
        return require_complete_pdf(row.pdf_url)
    except Exception as exc:
        # A PDF decoder can reject malformed files with library-specific errors.
        # Only isolate validation of this file, never mask a database error.
        log.warning('Library PDF unavailable for story %d (%s)', row.id, type(exc).__name__)
        return None


def list_books(db: Session, external_user_id: str, before_story_id: int | None) -> dict:
    books = []
    while True:
        query = _owned_books(external_user_id)
        if before_story_id is not None:
            query = query.where(Story.id < before_story_id)
        rows = db.execute(query.order_by(Story.id.desc()).limit(PAGE_SIZE + 1)).all()
        for row in rows:
            if _checked_digest(row) is None:
                continue
            if len(books) == PAGE_SIZE:
                return {'books': books, 'next_before_story_id': books[-1]['story_id']}
            books.append({'story_id': row.id, 'episode_number': row.episode_number, 'title': row.title})
        if len(rows) <= PAGE_SIZE:
            return {'books': books, 'next_before_story_id': None}
        before_story_id = rows[-1].id


def find_book(db: Session, external_user_id: str, story_id: int) -> dict | None:
    row = db.execute(_owned_books(external_user_id).where(Story.id == story_id)).one_or_none()
    if row is None:
        return None
    digest = _checked_digest(row)
    if digest is None:
        return None
    return {'episode_number': row.episode_number, 'pdf_url': row.pdf_url, 'pdf_sha256': digest}
