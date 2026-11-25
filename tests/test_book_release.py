"""Technical release gates, exercised without provider requests or customer data."""
import uuid
from types import SimpleNamespace
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfWriter

from backend.app import book_release as gate


@pytest.fixture
def assets(tmp_path, monkeypatch):
    images = tmp_path / "images"
    stories = tmp_path / "stories"
    images.mkdir()
    stories.mkdir()
    monkeypatch.setattr(gate, "get_settings", lambda: SimpleNamespace(
        images_dir=str(images), stories_dir=str(stories)
    ))
    urls = []
    for i in range(5):
        filename = uuid.uuid4().hex + ".png"
        Image.new("RGB", (40, 30), (30 * i, 90, 180)).save(images / filename)
        urls.append("https://test.invalid/files/images/" + filename)
    return images, stories, urls


def test_five_valid_images(assets):
    gate.require_complete_images(assets[2])


@pytest.mark.parametrize("case", ["missing", "duplicate", "none", "broken", "absent"])
def test_incomplete_images_are_rejected(assets, case):
    images, _, urls = assets
    urls = list(urls)
    if case == "missing":
        urls.pop()
    elif case == "duplicate":
        urls[4] = urls[0]
    elif case == "none":
        urls[4] = None
    elif case == "broken":
        (images / urls[4].rsplit("/", 1)[-1]).write_bytes(b"invalid")
    elif case == "absent":
        (images / urls[4].rsplit("/", 1)[-1]).unlink()
    with pytest.raises((ValueError, OSError)):
        gate.require_complete_images(urls)


def test_pdf_without_illustrations_is_rejected(assets):
    _, stories, _ = assets
    filename = uuid.uuid4().hex + ".pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.write(str(stories / filename))
    with pytest.raises(ValueError, match="embedded illustrations"):
        gate.require_complete_pdf("https://test.invalid/files/stories/" + filename)
