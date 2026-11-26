from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..book_release import require_complete_images, require_complete_pdf
from ..models import Child, Order, Story, User
from ..money import Money
from .image_service import generate_images
from .pdf_service import generate_pdf
from .text_service import choose_style, generate_story_payload


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


def get_or_create_child(db: Session, payload: dict, user_id: int) -> Child:
    if payload.get('child_id'):
        child = db.get(Child, payload['child_id'])
        if not child:
            raise ValueError('Child not found')
        if child.user_id != user_id:
            raise ValueError('Child does not belong to this user')
        for field in ('favorite_animal', 'favorite_color', 'hobby', 'favorite_place'):
            val = payload.get(field)
            if val:
                setattr(child, field, val)
        db.flush()
        return child

    if not payload.get('child_name') or not payload.get('age'):
        raise ValueError('child_name and age are required for new child')

    existing_child = db.scalar(
        select(Child).where(
            Child.user_id == user_id,
            Child.name == payload['child_name'],
            Child.age == payload['age'],
        )
    )
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


def _checkpoint_paid_order(db: Session, payload: dict, order_id: int) -> Order:
    """Persist the receipt before provider work; reacquire generation locks.

    A killed generation transaction must not erase an acknowledged paid order.
    The paid receipt includes the generation questionnaire snapshot. Telegram's
    pre-payment questionnaire, retry scheduling and delivery outbox remain separate.
    """
    db.commit()
    _serialize_paid_generation(db, payload)
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if not order or order.status != "paid":
        raise ValueError("Paid order no longer available")
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


def generate_story(db: Session, payload: dict) -> Story:
    _serialize_paid_generation(db, payload)
    user = get_or_create_user(db, payload['external_user_id'], payload.get('channel', 'telegram'))
    child = get_or_create_child(db, payload, user.id)

    # Every production generation requires a paid order. Telegram payment IDs
    # are trusted only through the authenticated internal bot-to-backend channel.
    order_id = payload.get('order_id')
    charge_id = payload.get('telegram_payment_charge_id')
    if not order_id and not charge_id:
        raise ValueError('Paid order is required before story generation')
    if not order_id and charge_id:
        existing_payment = db.scalar(
            select(Order).where(
                Order.provider == 'telegram_stars',
                Order.provider_payment_id == charge_id,
            )
        )
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
    paid_order = _checkpoint_paid_order(db, payload, order_id)
    if paid_order.user_id != user.id or paid_order.child_id != child.id:
        raise ValueError("Order does not belong to this user and child")
    if charge_id and paid_order.provider_payment_id != charge_id:
        raise ValueError("Payment ID does not match order")

    # A paid order is an idempotency key: never create a second story for it.
    # A failed existing story needs a separate explicit retry/recovery flow.
    story_for_order = db.scalar(select(Story).where(Story.order_id == order_id))
    if story_for_order is not None:
        return story_for_order

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

        pdf_url = generate_pdf(
            title=text_payload['title'],
            story_text=text_payload['story_text'],
            image_urls=images_urls,
            episode_number=episode_number,
            child_name=questionnaire['child_name'],
            next_hook=text_payload.get('next_hook', ''),
            gender=questionnaire['gender'],
        )

        require_complete_pdf(pdf_url)

        story.title = text_payload['title']
        story.story_text = text_payload['story_text']
        story.recap = text_payload.get('recap', [])
        story.memory = text_payload.get('memory', {})
        story.next_hook = text_payload.get('next_hook')
        story.images_urls = images_urls
        story.pdf_url = pdf_url
        story.status = 'ready'
        db.commit()
        db.refresh(story)
        return story
    except Exception as exc:
        story.status = 'failed'
        story.error_message = str(exc)
        db.commit()
        db.refresh(story)
        raise


def list_child_stories(db: Session, child_id: int, limit: int = 10) -> list[Story]:
    return list(
        db.scalars(
            select(Story)
            .where(Story.child_id == child_id)
            .order_by(desc(Story.episode_number))
            .limit(limit)
        )
    )
