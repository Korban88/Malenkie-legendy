import errno
import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, or_, select, text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..book_release import require_complete_images, require_complete_pdf
from ..models import Child, Order, Story, User
from ..money import Money
from .image_service import generate_images
from .pdf_service import generate_pdf
from .text_service import choose_style, generate_story_payload


PDF_PENDING_STATES = ('pdf_pending', 'pdf_retry')
PDF_RETRY_DELAY = timedelta(seconds=30)
log = logging.getLogger(__name__)


def health_db(db: Session) -> list[str]:
    rows = db.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
    ).fetchall()
    return [r[0] for r in rows]


def get_or_create_user(db: Session, external_user_id: str, channel: str) -> User:
    user = db.scalar(select(User).where(User.external_id == external_user_id))
    if user:
        return user
    user = User(external_id=external_user_id, channel=channel)
    db.add(user)
    db.flush()
    return user


def get_or_create_child(db: Session, payload: dict, user_id: int, *, existing_only: bool = False) -> Child:
    if payload.get('child_id'):
        existing_child = db.get(Child, payload['child_id'])
        if not existing_child:
            raise ValueError('Child not found')
        if existing_child.user_id != user_id:
            raise ValueError('Child does not belong to this user')
    else:
        if not payload.get('child_name') or not payload.get('age'):
            raise ValueError('child_name and age are required for new child')
        existing_child = db.scalar(
            select(Child).where(
                Child.user_id == user_id,
                Child.name == payload['child_name'],
                Child.age == payload['age'],
            )
        )
    if existing_only:
        # Render the paid snapshot without overwriting preferences saved by
        # a later questionnaire for the same child.
        if existing_child is None:
            raise ValueError('Child not found for the paid order')
        return existing_child
    if existing_child:
        for field in ('favorite_animal', 'favorite_color', 'hobby', 'favorite_place'):
            val = payload.get(field)
            if val:
                setattr(existing_child, field, val)
        db.flush()
        return existing_child

    child = Child(
        user_id=user_id,
        name=payload['child_name'],
        age=payload['age'],
        gender=payload.get('gender', 'neutral'),
        preferred_style=payload.get('style', 'auto'),
        parent_note=payload.get('parent_note'),
        photo_consent=payload.get('photo_consent', False),
        favorite_animal=payload.get('favorite_animal'),
        favorite_color=payload.get('favorite_color'),
        hobby=payload.get('hobby'),
        favorite_place=payload.get('favorite_place'),
    )
    db.add(child)
    db.flush()
    return child


def _serialize_paid_generation(db: Session, payload: dict) -> None:
    """Serialize requests for a buyer and charge on PostgreSQL.

    Transaction-scoped advisory locks are released even on disconnect.
    Take both keys in a stable order to avoid deadlocks. SQLite is used only
    for isolated smoke tests; this is not a concurrency guarantee on SQLite.
    """
    if db.get_bind().dialect.name != "postgresql":
        return
    keys = ["legendkids:buyer:" + payload["external_user_id"]]
    charge = payload.get("telegram_payment_charge_id")
    if charge:
        keys.append("legendkids:charge:" + charge)
    for key in sorted(keys):
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})


def _checkpoint_paid_order(db: Session, payload: dict, order_id: int, user_id: int, child_id: int) -> Order:
    """Persist the receipt before provider work; reacquire generation locks.

    A killed generation transaction must not erase an acknowledged paid order.
    The paid receipt includes the generation questionnaire snapshot. Telegram's
    pre-payment questionnaire, retry scheduling and delivery outbox remain separate.
    """
    db.commit()
    _serialize_paid_generation(db, payload)
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update()
                      .execution_options(populate_existing=True))
    if not order or order.status != "paid":
        raise ValueError("Paid order no longer available")
    if order.user_id != user_id or order.child_id != child_id:
        raise ValueError("Order does not belong to this user and child")
    charge = payload.get('telegram_payment_charge_id')
    if charge and order.provider_payment_id != charge:
        raise ValueError("Payment ID does not match order")
    return order


def _paid_questionnaire(order: Order, child: Child, payload: dict) -> dict:
    """Freeze generation inputs with the paid receipt, never raw photo bytes.

    Existing metadata JSON avoids a production schema mutation. Historic receipts
    without a snapshot acquire one on their first explicit recovery request.
    """
    meta = dict(getattr(order, 'meta', None) or {})
    existing = meta.get('questionnaire_v1')
    if existing is not None:
        if not isinstance(existing, dict) or existing.get('version') != 1:
            raise ValueError('Paid questionnaire snapshot is invalid')
        return dict(existing)
    defaults = {'child_name': getattr(child, 'name', payload.get('child_name')),
                'age': getattr(child, 'age', payload.get('age')),
                'gender': getattr(child, 'gender', 'neutral'),
                'style': getattr(child, 'preferred_style', 'auto'),
                'image_style': 'watercolor', 'purpose': 'bedtime',
                'parent_note': getattr(child, 'parent_note', None),
                'favorite_animal': getattr(child, 'favorite_animal', None) or 'кот',
                'favorite_color': getattr(child, 'favorite_color', None) or 'синий',
                'hobby': getattr(child, 'hobby', None) or 'рисование',
                'favorite_place': getattr(child, 'favorite_place', None) or 'лес',
                'episode_number': None, 'photo_enabled': False}
    snapshot = {'version': 1, **{key: payload.get(key) if payload.get(key) is not None else value
                                 for key, value in defaults.items()}}
    order.meta = {**meta, 'questionnaire_v1': snapshot}
    return dict(snapshot)


def _finish_paid_pdf(db: Session, story: Story, questionnaire: dict | None, *, background: bool = False) -> Story:
    """Render only saved assets under the paid order lock. A replay may have finished first."""
    if story.status not in PDF_PENDING_STATES:
        return story
    try:
        if not isinstance(questionnaire, dict) or questionnaire.get('version') != 1:
            raise ValueError('Saved paid questionnaire is invalid')
        require_complete_images(story.images_urls)
        pdf_url = generate_pdf(
            title=story.title, story_text=story.story_text, image_urls=story.images_urls,
            episode_number=story.episode_number, child_name=questionnaire['child_name'],
            next_hook=story.next_hook or '', gender=questionnaire['gender'],
        )
        require_complete_pdf(pdf_url)
    except Exception as exc:
        if (isinstance(exc, (FileNotFoundError, PermissionError, TimeoutError))
                or isinstance(exc, OSError) and errno.errorcode.get(exc.errno) in {
                    'EIO', 'ENOSPC', 'EDQUOT', 'EROFS', 'ESTALE', 'ENODEV', 'EBUSY', 'EAGAIN', 'EINTR', 'ENOTCONN',
                }):
            story.error_message = 'PDF storage temporarily unavailable'
        else:
            story.status = 'pdf_retry' if story.status == 'pdf_pending' else 'failed'
            story.error_message = 'PDF assembly failed'
        # Refresh the delay even when consecutive outages leave the same state.
        story.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        if background:
            log.warning('Staged PDF assembly deferred or failed (%s)', type(exc).__name__)
            return story
        raise
    story.pdf_url = pdf_url
    story.status = 'ready'
    story.error_message = None
    db.commit()
    db.refresh(story)
    return story


def recover_next_paid_pdf(session_factory: Callable[[], Session]) -> bool:
    """Assemble one staged Telegram book from disk under the normal paid-order lock."""
    with session_factory() as db:
        due = datetime.now(timezone.utc).replace(tzinfo=None) - PDF_RETRY_DELAY
        candidate = db.execute(
            select(Story, Order)
            .join(Order, Story.order_id == Order.id)
            .join(Child, Story.child_id == Child.id)
            .join(User, Child.user_id == User.id)
            .where(
                Story.status.in_(PDF_PENDING_STATES),
                or_(Story.error_message.is_(None), Story.updated_at <= due),
                Order.status == 'paid', Order.provider == 'telegram_stars',
                Order.provider_payment_id != '',
                Order.child_id == Child.id, Order.user_id == Child.user_id, User.channel == 'telegram',
            )
            .order_by(Story.updated_at, Story.id)
            .limit(1)
            .with_for_update(of=Order, skip_locked=True)
        ).one_or_none()
        if candidate is None:
            return False
        story, order = candidate
        # A foreground replay may finish between our initial snapshot and lock.
        db.refresh(story)
        if story.status in PDF_PENDING_STATES and (story.error_message is None or story.updated_at <= due):
            snapshot = order.meta.get('questionnaire_v1') if isinstance(order.meta, dict) else None
            _finish_paid_pdf(db, story, snapshot, background=True)
        return True


def generate_story(db: Session, payload: dict) -> Story:
    if payload.get('resume_pdf_only') and not payload.get('order_id'):
        raise ValueError('A saved paid order is required for PDF recovery')
    _serialize_paid_generation(db, payload)
    user = get_or_create_user(db, payload['external_user_id'], payload.get('channel', 'telegram'))

    # Every production generation requires a paid order. Telegram payment IDs
    # are trusted only through the authenticated internal bot-to-backend channel.
    order_id = payload.get('order_id')
    charge_id = payload.get('telegram_payment_charge_id')
    if not order_id and not charge_id:
        raise ValueError('Paid order is required before story generation')
    existing_payment = None
    if not order_id:
        existing_payment = db.scalar(
            select(Order).where(
                Order.provider == 'telegram_stars',
                Order.provider_payment_id == charge_id,
            )
        )
    child = get_or_create_child(
        db, payload, user.id, existing_only=bool(order_id or existing_payment is not None),
    )
    if not order_id:
        if existing_payment is not None:
            if existing_payment.user_id != user.id or existing_payment.child_id != child.id:
                raise ValueError('Payment belongs to another user or child')
            if existing_payment.status != 'paid':
                raise ValueError('Payment is not marked as paid')
            order_id = existing_payment.id
        else:
            photo_enabled = payload.get('photo_enabled', False)
            money = Money(currency='XTR', minor_units=200 if photo_enabled else 150)
            order = Order(
                user_id=user.id,
                child_id=child.id,
                tariff='story_with_photo' if photo_enabled else 'story',
                amount_rub=money.minor_units,  # XTR in legacy column; schema migration required
                provider='telegram_stars',
                status='paid',
                provider_payment_id=charge_id,
                meta={'currency': 'XTR', 'money_v1': money.to_metadata()},
            )
            db.add(order)
            db.flush()
            order_id = order.id

    paid_order = db.get(Order, order_id)
    if not paid_order or paid_order.status != 'paid':
        raise ValueError('Order must be paid before story generation')
    if paid_order.user_id != user.id or paid_order.child_id != child.id:
        raise ValueError('Order does not belong to this user and child')
    if charge_id and paid_order.provider_payment_id != charge_id:
        raise ValueError('Payment ID does not match order')

    # Commit the paid receipt before expensive provider requests. Recheck ownership
    # after the transaction boundary while holding the paid-order lock.
    questionnaire = _paid_questionnaire(paid_order, child, payload)
    user_id, child_id = user.id, child.id
    _checkpoint_paid_order(db, payload, order_id, user_id, child_id)

    # A paid order is an idempotency key: never create a second story for it.
    story_for_order = db.scalar(select(Story).where(Story.order_id == order_id)
                                .execution_options(populate_existing=True))
    if story_for_order is not None:
        if story_for_order.child_id != child_id:
            raise ValueError('Saved story does not belong to this paid child')
        return _finish_paid_pdf(db, story_for_order, questionnaire)
    if payload.get('resume_pdf_only'):
        raise ValueError('Saved PDF inputs are unavailable')

    max_episode = db.scalar(select(func.max(Story.episode_number)).where(Story.child_id == child.id)) or 0
    if get_settings().force_episode_one:
        episode_number = 1
    else:
        episode_number = questionnaire.get('episode_number') or (max_episode + 1)

    existing = db.scalar(select(Story).where(Story.child_id == child.id, Story.episode_number == episode_number))
    if existing:
        # Never use another paid order's story as the result of a new payment.
        raise ValueError('Requested episode already exists; resolve continuation or refund this order')

    latest_story = db.scalar(
        select(Story)
        .where(Story.child_id == child.id, Story.status == 'ready')
        .order_by(desc(Story.episode_number))
        .limit(1)
    )
    previous_memory = latest_story.memory if latest_story else {}
    previous_recap = latest_story.recap if latest_story else []

    style = choose_style(questionnaire['age'], questionnaire['style'])
    image_style = questionnaire['image_style']
    purpose = questionnaire['purpose']

    story = Story(
        child_id=child.id,
        order_id=order_id,
        episode_number=episode_number,
        style=style,
        status='generating',
    )
    db.add(story)
    db.flush()

    try:
        text_payload = generate_story_payload(
            {
                'child_name': questionnaire['child_name'],
                'age': questionnaire['age'],
                'gender': questionnaire['gender'],
                'style': style,
                'episode_number': episode_number,
                'parent_note': questionnaire['parent_note'],
                'previous_memory': previous_memory,
                'previous_recap': previous_recap,
                'image_style': image_style,
                'purpose': purpose,
                'favorite_animal': questionnaire['favorite_animal'],
                'favorite_color': questionnaire['favorite_color'],
                'hobby': questionnaire['hobby'],
                'favorite_place': questionnaire['favorite_place'],
            }
        )

        images_urls: list[str | None] = []
        photo_hash = None
        try:
            images_urls, photo_hash = generate_images(
                child_name=questionnaire['child_name'],
                age=questionnaire['age'],
                style=style,
                photo_base64=payload.get('photo_base64') if questionnaire['photo_enabled'] else None,
                char_desc=text_payload.get('char_desc', ''),
                scene_prompts=text_payload.get('image_prompts', []),
                count=5,
                image_style=image_style,
            )
            if photo_hash:
                child.photo_hash = photo_hash
        except Exception as img_exc:
            raise RuntimeError('Illustration generation failed') from img_exc

        require_complete_images(images_urls)

        story.title = text_payload['title']
        story.story_text = text_payload['story_text']
        story.recap = text_payload.get('recap', [])
        story.memory = text_payload.get('memory', {})
        story.next_hook = text_payload.get('next_hook')
        story.images_urls = images_urls
        story.status = 'pdf_pending'
    except Exception as exc:
        story.status = 'failed'
        story.error_message = str(exc)
        db.commit()
        db.refresh(story)
        raise

    # Commit complete inputs before rendering. Competing replays serialize on
    # the same order. Refresh even if the session keeps objects on commit.
    _checkpoint_paid_order(db, payload, order_id, user_id, child_id)
    db.refresh(story)
    return _finish_paid_pdf(db, story, questionnaire)


def list_child_stories(db: Session, child_id: int, limit: int = 10) -> list[Story]:
    return list(
        db.scalars(
            select(Story)
            .where(Story.child_id == child_id)
            .order_by(desc(Story.episode_number))
            .limit(limit)
        )
    )
