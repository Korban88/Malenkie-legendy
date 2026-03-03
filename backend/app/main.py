from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .config import get_settings
from .db import Base, engine, get_db
from .routers.payment import router as payment_router
from .routers.story import router as story_router
from .services.story_service import health_db

settings = get_settings()
Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.app_name)
app.include_router(story_router)
app.include_router(payment_router)


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.get('/health_db')
def health_database(db: Session = Depends(get_db)):
    return {'status': 'ok', 'tables': health_db(db)}


@app.get('/files/stories/{filename}')
def files_stories(filename: str):
    path = Path(settings.stories_dir) / filename
    return FileResponse(path)


@app.get('/files/images/{filename}')
def files_images(filename: str):
    path = Path(settings.images_dir) / filename
    return FileResponse(path)
