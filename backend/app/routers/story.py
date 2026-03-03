from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import StoryGenerateRequest, StoryGenerateResponse
from ..services.story_service import generate_story, list_child_stories

router = APIRouter(prefix='/api', tags=['story'])


def to_response(story) -> StoryGenerateResponse:
    return StoryGenerateResponse(
        story_id=story.id,
        child_id=story.child_id,
        episode_number=story.episode_number,
        status=story.status,
        title=story.title,
        story_text=story.story_text,
        recap=story.recap or [],
        memory=story.memory or {},
        next_hook=story.next_hook,
        images_urls=story.images_urls or [],
        pdf_url=story.pdf_url,
    )


@router.post('/story/generate', response_model=StoryGenerateResponse)
def generate_story_endpoint(payload: StoryGenerateRequest, db: Session = Depends(get_db)):
    try:
        story = generate_story(db, payload.model_dump())
        return to_response(story)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'Generation failed: {exc}') from exc


@router.get('/story/{story_id}', response_model=StoryGenerateResponse)
def get_story(story_id: int, db: Session = Depends(get_db)):
    from ..models import Story

    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(status_code=404, detail='Story not found')
    return to_response(story)


@router.get('/child/{child_id}/stories')
def get_child_stories(child_id: int, db: Session = Depends(get_db)):
    stories = list_child_stories(db, child_id, limit=10)
    return {'child_id': child_id, 'stories': [to_response(s).model_dump() for s in stories]}
