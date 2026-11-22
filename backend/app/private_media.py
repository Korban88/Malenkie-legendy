"""Short-lived, signed cover references plus private customer media delivery.

The media URLs returned in story records are *locators*, not public capabilities.
Only the trusted backend-to-bot header may retrieve a finished customer book.
Together AI may retrieve one specific cover image through a short-lived,
HMAC-authenticated URL if the service is served over HTTPS.
"""
import hashlib
import hmac
import re
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

from .config import get_settings

_IMAGE_NAME = re.compile(r"^[a-f0-9]{32}\.(?:png|jpg|jpeg|webp)$", re.I)
_PDF_NAME = re.compile(r"^[a-f0-9]{32}\.pdf$", re.I)
_COVER_TTL = 1800


def locate_media(directory: str, filename: str, *, kind: str) -> Path:
    """Never permit traversal, hidden files, directories or arbitrary extensions."""
    pattern = _PDF_NAME if kind == "stories" else _IMAGE_NAME if kind == "images" else None
    if pattern is None or not pattern.fullmatch(filename):
        raise ValueError("Invalid media filename")
    root = Path(directory).resolve()
    candidate = (root / filename).resolve()
    if candidate.parent != root or not candidate.is_file():
        raise FileNotFoundError("Media not found")
    return candidate


def _signed_message(filename: str, expires: int) -> bytes:
    return f"image-cover:v1:{filename}:{expires}".encode("utf-8")


def sign_cover_reference(filename: str, *, now: int | None = None) -> str:
    """For a third-party image provider, not for a customer-facing link."""
    settings = get_settings()
    if not _IMAGE_NAME.fullmatch(filename):
        raise ValueError("Invalid cover name")
    if len(settings.backend_internal_token) < 32:
        raise RuntimeError("Internal secret is not configured")
    parsed = urlsplit(settings.public_base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise RuntimeError("HTTPS PUBLIC_BASE_URL is required for a signed cover reference")
    expires = int(time.time() if now is None else now) + _COVER_TTL
    signature = hmac.new(
        settings.backend_internal_token.encode("utf-8"),
        _signed_message(filename, expires),
        hashlib.sha256,
    ).hexdigest()
    base = settings.public_base_url.rstrip("/")
    return f"{base}/files/images/{quote(filename)}?expires={expires}&signature={signature}"


def verify_cover_reference(
    filename: str, expires: int | None, signature: str | None, *, now: int | None = None
) -> bool:
    settings = get_settings()
    if not _IMAGE_NAME.fullmatch(filename) or len(settings.backend_internal_token) < 32:
        return False
    if expires is None or not signature or not re.fullmatch(r"[a-f0-9]{64}", signature):
        return False
    current = int(time.time() if now is None else now)
    if expires < current or expires > current + _COVER_TTL:
        return False
    expected = hmac.new(
        settings.backend_internal_token.encode("utf-8"),
        _signed_message(filename, expires),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)
