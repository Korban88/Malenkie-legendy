from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from ..models import Child, Story, User
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
        # Update preferences if provided for existing child
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
        # Update preferences if provided
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


def generate_story(db: Session, payload: dict) -> Story:
    user = get_or_create_user(db, payload['external_user_id'], payload.get('channel', 'telegram'))
    child = get_or_create_child(db, payload, user.id)

    max_episode = db.scalar(select(func.max(Story.episode_number)).where(Story.child_id == child.id)) or 0
    episode_number = payload.get('episode_number') or (max_episode + 1)

    existing = db.scalar(select(Story).where(Story.child_id == child.id, Story.episode_number == episode_number))
    if existing:
        return existing

    latest_story = db.scalar(
        select(Story)
        .where(Story.child_id == child.id, Story.status == 'ready')
        .order_by(desc(Story.episode_number))
        .limit(1)
    )
    previous_memory = latest_story.memory if latest_story else {}
    previous_recap = latest_story.recap if latest_story else []

    style = choose_style(child.age, payload.get('style') or child.preferred_style)

    story = Story(
        child_id=child.id,
        order_id=payload.get('order_id'),
        episode_number=episode_number,
        style=style,
        status='generating',
    )
    db.add(story)
    db.flush()

    try:
        text_payload = generate_story_payload(
            {
                'child_name': child.name,
                'age': child.age,
                'gender': child.gender,
                'style': style,
                'episode_number': episode_number,
                'parent_note': payload.get('parent_note') or child.parent_note,
                'previous_memory': previous_memory,
                'previous_recap': previous_recap,
                # Child preferences for personalization
                'favorite_animal': child.favorite_animal or payload.get('favorite_animal') or 'кот',
                'favorite_color': child.favorite_color or payload.get('favorite_color') or 'синий',
                'hobby': child.hobby or payload.get('hobby') or 'рисование',
                'favorite_place': child.favorite_place or payload.get('favorite_place') or 'лес',
            }
        )

        images_urls: list[str] = []
        photo_hash = None
        try:
            images_urls, photo_hash = generate_images(
                child_name=child.name,
                age=child.age,
                style=style,
                photo_base64=payload.get('photo_base64') if payload.get('photo_enabled') else None,
                scene_prompts=text_payload.get('image_prompts', []),
                count=8,
                image_style=payload.get('image_style', 'watercolor'),
            )
            if photo_hash:
                child.photo_hash = photo_hash
        except Exception as img_exc:
            story.error_message = f'images_failed: {img_exc}'

        pdf_url = generate_pdf(
            title=text_payload['title'],
            story_text=text_payload['story_text'],
            image_urls=images_urls,
            episode_number=episode_number,
            child_name=child.name,
            next_hook=text_payload.get('next_hook', ''),
            gender=child.gender,
        )

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
