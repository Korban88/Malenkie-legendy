"""No-network regressions for a legacy referenced-image batch."""
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

from backend.app import private_media
from backend.app.services import image_service


SCENES = ["cover", "chapter 1", "chapter 2", "chapter 3", "chapter 4"]
COVER = "1" * 32 + ".png"


@pytest.fixture
def configured(tmp_path, monkeypatch):
    config = SimpleNamespace(
        image_provider="together", backup_image_provider="openai",
        images_dir=str(tmp_path), keep_uploaded_photo=False,
        public_base_url="https://test.invalid", backend_internal_token="x" * 40,
    )
    monkeypatch.setattr(image_service, "settings", config)
    monkeypatch.setattr(private_media, "get_settings", lambda: config)
    monkeypatch.setattr(image_service, "_build_prompt", lambda scene, *a, **kw: scene)
    return config


def run_batch():
    return image_service.generate_images("Тест", 7, "nature", None, scene_prompts=SCENES)


@pytest.mark.parametrize("field, value", [
    ("public_base_url", "http://test.invalid"),
    ("backend_internal_token", "short"),
])
def test_invalid_reference_configuration_spends_no_requests(configured, monkeypatch, field, value):
    setattr(configured, field, value)
    generate = Mock(return_value=COVER)
    monkeypatch.setattr(image_service, "_generate_single", generate)
    with pytest.raises(RuntimeError):
        run_batch()
    generate.assert_not_called()


def test_cover_failure_stops_sequence(configured, monkeypatch):
    generate = Mock(side_effect=RuntimeError("synthetic cover failure"))
    monkeypatch.setattr(image_service, "_generate_single", generate)
    urls, _ = run_batch()
    assert urls == [None] * 5
    assert generate.call_count == 1


def test_signing_failure_after_cover_stops_sequence(configured, monkeypatch):
    generate = Mock(return_value=COVER)
    monkeypatch.setattr(image_service, "_generate_single", generate)
    sign = private_media.sign_cover_reference

    def reject_actual_cover(filename, **kwargs):
        if filename == COVER:
            raise RuntimeError("synthetic signing failure")
        return sign(filename, **kwargs)

    monkeypatch.setattr(image_service, "sign_cover_reference", reject_actual_cover)
    urls, _ = run_batch()
    assert urls == [None] * 5
    assert generate.call_count == 1


def test_failed_first_chapter_does_not_spend_on_remaining_slots(configured, monkeypatch):
    generate = Mock(side_effect=[COVER, RuntimeError("synthetic chapter failure"),
                                 "3" * 32 + ".png", "4" * 32 + ".png", "5" * 32 + ".png"])
    monkeypatch.setattr(image_service, "_generate_single", generate)
    urls, _ = run_batch()
    assert urls[0].endswith(COVER)
    assert urls[1:] == [None] * 4
    assert generate.call_count == 2


def test_healthy_batch_passes_signed_reference_to_each_chapter(configured, monkeypatch):
    generate = Mock(side_effect=[str(i) * 32 + ".png" for i in range(1, 6)])
    monkeypatch.setattr(image_service, "_generate_single", generate)
    urls, _ = run_batch()
    assert len(urls) == 5 and all(urls)
    assert all("signature=" not in url for url in urls)
    assert generate.call_count == 5
    assert generate.call_args_list[0].kwargs["cover_url"] is None
    refs = [call.kwargs["cover_url"] for call in generate.call_args_list[1:]]
    assert len(set(refs)) == 1
    signed = urlsplit(refs[0])
    query = parse_qs(signed.query)
    assert signed.scheme == "https"
    assert signed.path.endswith(COVER)
    assert private_media.verify_cover_reference(COVER, int(query["expires"][0]), query["signature"][0])


@pytest.mark.parametrize("backup", ["openai", "pollinations"])
def test_referenced_chapter_does_not_fall_back_to_unreferenced_provider(configured, monkeypatch, backup):
    configured.backup_image_provider = backup
    primary = Mock(side_effect=RuntimeError("synthetic provider failure"))
    fallback = Mock(return_value=COVER)
    monkeypatch.setattr(image_service, "_together_generate", primary)
    monkeypatch.setattr(image_service, "_openai_generate", fallback)
    monkeypatch.setattr(image_service, "_pollinations_generate", fallback)
    signed = private_media.sign_cover_reference(COVER)
    with pytest.raises(RuntimeError, match="synthetic provider failure"):
        image_service._generate_single("chapter 1", None, cover_url=signed)
    primary.assert_called_once_with("chapter 1", reference_url=signed)
    fallback.assert_not_called()
