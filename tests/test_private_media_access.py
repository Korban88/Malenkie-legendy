"""No external calls: verify that bought books cannot be fetched anonymously.

Run: python -m pytest -q tests/test_private_media_access.py
Integration tests with a live reverse proxy and bot still required before deploy.
"""
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from backend.app import private_media as m


@pytest.fixture(autouse=True)
def isolated_media_settings(monkeypatch):
    monkeypatch.setattr(
        m, "get_settings",
        lambda: SimpleNamespace(
            backend_internal_token="test-secret-" + "x" * 50,
            public_base_url="https://books.example.test",
        ),
    )


def test_signed_cover_reference_expires_and_is_filename_scoped():
    filename = "a" * 32 + ".png"
    url = m.sign_cover_reference(filename, now=10000)
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    expires = int(query["expires"][0])
    signature = query["signature"][0]
    assert parsed.scheme == "https"
    assert parsed.path == "/files/images/" + filename
    assert expires == 11800
    assert m.verify_cover_reference(filename, expires, signature, now=10000)
    assert not m.verify_cover_reference(filename, expires, signature, now=11801)
    assert not m.verify_cover_reference("b" * 32 + ".png", expires, signature, now=10000)
    assert not m.verify_cover_reference(filename, expires, "0" * 64, now=10000)
    assert not m.verify_cover_reference(filename, expires, "", now=10000)


def test_no_anonymous_or_permanent_cover_access():
    filename = "c" * 32 + ".png"
    assert not m.verify_cover_reference(filename, None, None)
    assert not m.verify_cover_reference(filename, 12345, None)
    assert not m.verify_cover_reference(filename, 12345, "b" * 64, now=12346)


def test_cover_signature_rejects_http_and_invalid_name(monkeypatch):
    with pytest.raises(ValueError):
        m.sign_cover_reference("../child-photo.png", now=100)
    monkeypatch.setattr(m, "get_settings", lambda: SimpleNamespace(
        backend_internal_token="z" * 40, public_base_url="http://localhost:8010"))
    with pytest.raises(RuntimeError, match="HTTPS"):
        m.sign_cover_reference("a" * 32 + ".png", now=100)


def test_private_media_file_validation(tmp_path: Path):
    image = tmp_path / ("1" * 32 + ".png")
    image.write_bytes(b"safe-test-data")
    assert m.locate_media(str(tmp_path), image.name, kind="images") == image.resolve()
    for bad in ("../../etc/passwd", ".env", "other.png", "1" * 32 + ".pdf"):
        with pytest.raises((ValueError, FileNotFoundError)):
            m.locate_media(str(tmp_path), bad, kind="images")
    with pytest.raises(FileNotFoundError):
        m.locate_media(str(tmp_path), "2" * 32 + ".png", kind="images")


def test_no_public_book_endpoint_or_public_pdf_buttons():
    root = Path(__file__).resolve().parents[1]
    main = (root / "backend/app/main.py").read_text(encoding="utf-8")
    bot = (root / "bot/bot.py").read_text(encoding="utf-8")
    assert "@app.get('/files/stories/{filename}')" not in main
    assert "@app.get('/api/internal/files/stories/{filename}'" in main
    assert "dependencies=[Depends(require_internal_token)]" in main
    assert "url=pdf_url" not in bot
    assert "await _send_pdf(trigger_message, pdf_url, episode)" in bot
