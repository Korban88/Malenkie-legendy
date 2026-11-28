import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .config import get_settings
from .db import Base, SessionLocal, engine, get_db
from .internal_auth import require_internal_token
from .private_media import locate_media, verify_cover_reference
from .routers.delivery import router as delivery_router
from .routers.payment import router as payment_router
from .routers.story import router as story_router
from .services.cost_guard import ALLOWED_MODELS, BLOCKED_SUBSTRINGS
from .services.story_service import health_db, recover_next_paid_pdf

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

PDF_RECOVERY_INTERVAL = 30


async def _recover_staged_books(stop: asyncio.Event):
    while not stop.is_set():
        try:
            if await asyncio.to_thread(recover_next_paid_pdf, SessionLocal):
                continue
        except Exception as exc:
            # DB and renderer exceptions may contain private parameters or paths.
            log.warning('Paid PDF recovery attempt failed (%s)', type(exc).__name__)
        try:
            await asyncio.wait_for(stop.wait(), timeout=PDF_RECOVERY_INTERVAL)
        except asyncio.TimeoutError:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = asyncio.Event()
    worker = asyncio.create_task(_recover_staged_books(stop))
    try:
        yield
    finally:
        stop.set()
        await worker


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(story_router)
app.include_router(payment_router)
app.include_router(delivery_router)


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.get('/health_db', dependencies=[Depends(require_internal_token)])
def health_database(db: Session = Depends(get_db)):
    return {'status': 'ok', 'tables': health_db(db)}


def _checked_file(directory: str, filename: str, kind: str, media_type: str) -> FileResponse:
    try:
        path = locate_media(directory, filename, kind=kind)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="Media not found")
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-store"})


@app.get('/api/internal/files/stories/{filename}', dependencies=[Depends(require_internal_token)])
def internal_story_pdf(filename: str):
    """Only the authenticated Telegram bot may fetch purchased PDFs."""
    return _checked_file(settings.stories_dir, filename, 'stories', 'application/pdf')


@app.get('/api/internal/files/images/{filename}', dependencies=[Depends(require_internal_token)])
def internal_story_image(filename: str):
    """Images are sent by the Telegram bot as attachments, not public URLs."""
    return _checked_file(settings.images_dir, filename, 'images', 'image/png')


@app.get('/files/images/{filename}')
def temporary_cover_reference(
    filename: str,
    expires: int | None = Query(default=None),
    signature: str | None = Query(default=None),
):
    """A narrow 30-minute URL for Together AI to fetch the cover for subsequent images."""
    if not verify_cover_reference(filename, expires, signature):
        raise HTTPException(status_code=404, detail="Media not found")
    return _checked_file(settings.images_dir, filename, 'images', 'image/png')

# Intentionally no public /files/stories route: all customer books stay private.
