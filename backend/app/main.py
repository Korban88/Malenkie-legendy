import logging
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .config import get_settings
from .db import Base, engine, get_db
from .routers.payment import router as payment_router
from .routers.story import router as story_router
from .services.cost_guard import ALLOWED_MODELS, BLOCKED_SUBSTRINGS
from .services.story_service import health_db

log = logging.getLogger("malenkie_legendy")

settings = get_settings()
Base.metadata.create_all(bind=engine)

# ── Startup cost-safety model validation ──────────────────────────────────────
_configured_model = settings.openrouter_model
_model_lower = _configured_model.lower()
_blocked = next((b for b in BLOCKED_SUBSTRINGS if b in _model_lower), None)
if _blocked:
    raise RuntimeError(
        f"[STARTUP SAFETY] OPENROUTER_MODEL='{_configured_model}' matches "
        f"blocked pattern '{_blocked}'. Fix your .env before starting the server."
    )
if _configured_model not in ALLOWED_MODELS:
    raise RuntimeError(
        f"[STARTUP SAFETY] OPENROUTER_MODEL='{_configured_model}' is not in allowlist. "
        f"Allowed: {sorted(ALLOWED_MODELS)}. Fix your .env before starting the server."
    )
log.info("[STARTUP] Model validated: %s", _configured_model)

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
