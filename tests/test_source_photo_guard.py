"""Synthetic image adapter regressions. All provider boundaries are mocked."""
import base64
from pathlib import Path
from io import BytesIO
from PIL import Image
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from backend.app.services import image_service as service

PHOTO = base64.b64encode(b'synthetic-source-photo').decode()
SCENES = ['cover', 'one', 'two', 'three', 'four']

@pytest.fixture
def isolated(tmp_path, monkeypatch):
    cfg = SimpleNamespace(image_provider='stability', backup_image_provider='openai',
        stability_api_key='synthetic-only', openai_api_key='synthetic-only',
        keep_uploaded_photo=False, images_dir=str(tmp_path), public_base_url='https://test.invalid')
    monkeypatch.setattr(service, 'settings', cfg)
    monkeypatch.setattr(service, '_build_prompt', lambda scene, *a, **k: scene)
    monkeypatch.setattr(service, 'sign_cover_reference', Mock(return_value='https://test.invalid/signed'))
    # Fail on accidental real provider access, including optional vision.
    for name in ('_together_generate', '_openai_generate', '_openai_edit_generate',
                 '_pollinations_generate', '_extract_character_appearance', '_extract_style_fingerprint'):
        monkeypatch.setattr(service, name, Mock(side_effect=RuntimeError('unexpected provider')))
    post = Mock(side_effect=RuntimeError('unexpected HTTP'))
    monkeypatch.setattr(service, 'httpx', SimpleNamespace(post=post))
    return cfg, post

def run():
    return service.generate_images('synthetic', 7, 'nature', PHOTO, scene_prompts=SCENES)

@pytest.mark.parametrize('provider', ['together', 'openai', 'pollinations'])
def test_unsupported_source_photo_rejected_before_provider_or_storage(isolated, monkeypatch, provider):
    cfg, post = isolated
    cfg.image_provider = provider
    cfg.keep_uploaded_photo = True
    save = Mock()
    monkeypatch.setattr(service, '_save_image_bytes', save)
    with pytest.raises(RuntimeError, match='source photo'):
        run()
    post.assert_not_called()
    save.assert_not_called()
    service._together_generate.assert_not_called()
    service._openai_generate.assert_not_called()
    service._pollinations_generate.assert_not_called()

def test_missing_reference_key_rejected_before_provider(isolated):
    cfg, post = isolated
    cfg.stability_api_key = ''
    with pytest.raises(RuntimeError, match='source photo'):
        run()
    post.assert_not_called()
    service._openai_generate.assert_not_called()

@pytest.mark.parametrize('status', [401, 429, 503])
def test_reference_failure_no_second_request(isolated, status):
    _, post = isolated
    post.side_effect = None
    post.return_value = httpx.Response(status, request=httpx.Request('POST','https://test.invalid'))
    with pytest.raises(httpx.HTTPStatusError):
        service._stability_generate('cover', PHOTO)
    assert post.call_count == 1
    assert '/control/style' in post.call_args.args[0]


def test_failed_photo_cover_stops_batch(isolated):
    _, post = isolated
    post.side_effect = httpx.ReadTimeout('synthetic timeout')
    urls, _ = run()
    assert urls == [None] * 5
    assert post.call_count == 1
    service._openai_generate.assert_not_called()
    service._openai_edit_generate.assert_not_called()


def test_photo_batch_uses_saved_cover_without_hidden_provider(isolated, monkeypatch):
    cfg, post = isolated
    post.side_effect = None
    buffer = BytesIO()
    Image.new('RGB', (32, 24), 'navy').save(buffer, format='PNG')
    cover_bytes = buffer.getvalue()
    post.return_value = httpx.Response(200, content=cover_bytes, request=httpx.Request('POST','https://test.invalid'))
    index = iter(range(1,6))
    def save(data, directory):
        name = f'{next(index):032x}.png'
        (Path(directory) / name).write_bytes(data)
        return name
    monkeypatch.setattr(service, '_save_image_bytes', save)
    urls, _ = run()
    assert all(urls) and len(set(urls)) == 5
    assert post.call_count == 5
    assert all('/control/style' in c.args[0] for c in post.call_args_list)
    assert post.call_args_list[0].kwargs['files']['image'][1] == base64.b64decode(PHOTO)
    assert all(c.kwargs['files']['image'][1] == cover_bytes for c in post.call_args_list[1:])
    service._extract_character_appearance.assert_not_called()
    service._extract_style_fingerprint.assert_not_called()
    service._openai_edit_generate.assert_not_called()


def test_missing_saved_cover_stops_batch(isolated, monkeypatch):
    _, post = isolated
    post.side_effect = None
    post.return_value = httpx.Response(200, content=b'synthetic', request=httpx.Request('POST','https://test.invalid'))
    monkeypatch.setattr(service, '_save_image_bytes', Mock(return_value='1'*32+'.png'))
    urls, _ = run()
    assert urls == [None]*5
    assert post.call_count == 1
