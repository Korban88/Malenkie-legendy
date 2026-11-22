"""ASGI integration test for anonymous access and authenticated PDF delivery.

No actual PostgreSQL, Telegram, AI calls or customer data.
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.config import get_settings
from backend.app.private_media import sign_cover_reference


def test_private_file_routes_fail_closed(monkeypatch, tmp_path):
    # Set an explicit synthetic environment before FastAPI imports modules.
    images = tmp_path / "images"
    books = tmp_path / "stories"
    images.mkdir()
    books.mkdir()
    image_name = "a" * 32 + ".png"
    pdf_name = "b" * 32 + ".pdf"
    (images / image_name).write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 24)
    (books / pdf_name).write_bytes(b"%PDF-1.7\n% synthetic test only\n")
    secret = "test-private-media-" + "z" * 50
    monkeypatch.setenv("BACKEND_INTERNAL_TOKEN", secret)
    monkeypatch.setenv("IMAGES_DIR", str(images))
    monkeypatch.setenv("STORIES_DIR", str(books))
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://books.example.test")
    get_settings.cache_clear()

    # The existing legacy module creates all tables at import time.
    # Patch only that unsafe import-time DB action; live PG is tested separately.
    with patch("backend.app.db.Base.metadata.create_all"):
        from backend.app.main import app

    with TestClient(app) as client:
        # Old public PDF endpoint must be entirely absent.
        assert client.get(f"/files/stories/{pdf_name}").status_code == 404

        internal_pdf = f"/api/internal/files/stories/{pdf_name}"
        assert client.get(internal_pdf).status_code == 401
        assert client.get(internal_pdf, headers={"X-Legend-Internal-Key": "wrong"}).status_code == 401
        ok = client.get(internal_pdf, headers={"X-Legend-Internal-Key": secret})
        assert ok.status_code == 200
        assert ok.content.startswith(b"%PDF-")
        assert ok.headers.get("cache-control") == "no-store"

        internal_image = f"/api/internal/files/images/{image_name}"
        assert client.get(internal_image).status_code == 401
        assert client.get(internal_image, headers={"X-Legend-Internal-Key": secret}).status_code == 200

        # Images are only available to a provider through an expiring HMAC URL.
        public_image = f"/files/images/{image_name}"
        assert client.get(public_image).status_code == 404
        signed = sign_cover_reference(image_name)
        assert client.get(signed.replace("https://books.example.test", "")).status_code == 200
        assert client.get(signed.replace("https://books.example.test", "").replace("signature=", "signature=0")).status_code == 404
        assert client.get(f"/files/images/{'c'*32}.png").status_code == 404

        # Internal operational info should not be anonymously accessible.
        assert client.get("/health_db").status_code == 401

    get_settings.cache_clear()
