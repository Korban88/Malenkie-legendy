"""Offline technical image gate checks, not artistic QA."""
from types import SimpleNamespace
from PIL import Image, PngImagePlugin
import pytest
from backend.app import book_release as gate

@pytest.fixture
def slots(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, 'get_settings', lambda: SimpleNamespace(images_dir=str(tmp_path)))
    paths = [tmp_path / (f'{i+1:032x}.png') for i in range(5)]
    for i, path in enumerate(paths):
        Image.new('RGB', (64, 48), (i*40, 100, 150)).save(path)
    return paths, ['https://test.invalid/files/images/' + p.name for p in paths]

@pytest.mark.parametrize('variant', ['same_bytes', 'different_metadata', 'different_mode'])
def test_duplicate_picture_is_not_five_distinct_illustrations(slots, variant):
    paths, urls = slots
    if variant == 'same_bytes':
        paths[4].write_bytes(paths[0].read_bytes())
    else:
        with Image.open(paths[0]) as source:
            metadata = PngImagePlugin.PngInfo()
            metadata.add_text('Comment', 'synthetic alternate file')
            source.convert('RGBA' if variant == 'different_mode' else 'RGB').save(paths[4], pnginfo=metadata)
        assert paths[0].read_bytes() != paths[4].read_bytes()
    with pytest.raises(ValueError, match='distinct'):
        gate.require_complete_images(urls)

def test_truncated_jpeg_rejected_even_if_header_verifies(slots):
    paths, urls = slots
    path = paths[4].with_suffix('.jpg')
    Image.new('RGB', (128, 128), (12, 34, 56)).save(path, format='JPEG')
    path.write_bytes(path.read_bytes()[:-10])
    urls[4] = 'https://test.invalid/files/images/' + path.name
    with pytest.raises((ValueError, OSError)):
        gate.require_complete_images(urls)

def test_distinct_illustrations_allowed(slots):
    _, urls = slots
    gate.require_complete_images(urls)

def test_valid_jpeg_allowed(slots):
    paths, urls = slots
    path = paths[4].with_suffix('.jpg')
    Image.new('RGB', (64, 48), (1, 2, 3)).save(path)
    urls[4] = 'https://test.invalid/files/images/' + path.name
    gate.require_complete_images(urls)
