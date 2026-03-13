from pydantic import BaseModel, Field


class StoryGenerateRequest(BaseModel):
    external_user_id: str = Field(..., description='Telegram/VK/Web user id')
    channel: str = 'telegram'
    child_id: int | None = None
    child_name: str | None = None
    age: int | None = Field(default=None, ge=2, le=12)
    gender: str = 'neutral'
    style: str = 'auto'
    image_style: str = 'watercolor'
    parent_note: str | None = None
    photo_enabled: bool = False
    photo_base64: str | None = None
    photo_consent: bool = False
    order_id: int | None = None
    episode_number: int | None = None
    favorite_animal: str | None = None
    favorite_color: str | None = None
    hobby: str | None = None
    favorite_place: str | None = None


class StoryGenerateResponse(BaseModel):
    story_id: int
    child_id: int
    episode_number: int
    status: str
    title: str | None
    story_text: str | None
    recap: list[str]
    memory: dict
    next_hook: str | None
    images_urls: list[str]
    pdf_url: str | None


class StoryListResponse(BaseModel):
    child_id: int
    stories: list[StoryGenerateResponse]
