"""The reference book and the paid product have a cover and four chapter scenes."""
import json

import pytest

from backend.app.book_release import EXPECTED_IMAGES
from backend.app.services import image_service, text_service


def questionnaire():
    return {"child_name": "Нина", "age": 7, "gender": "female",
            "style": "nature", "episode_number": 1}


def test_text_prompt_example_describes_each_slot_in_order():
    prompt = text_service._prompt(questionnaire())
    example = next(line for line in prompt.splitlines() if line.startswith('{"title":'))
    assert json.loads(example)["image_prompts"] == [
        "cover", "chapter 1 scene", "chapter 2 scene", "chapter 3 scene", "chapter 4 scene",
    ]


@pytest.mark.parametrize("prompts", [
    None, "wrong", ["scene"] * 4, ["scene"] * 6, ["cover", "one", "two", "three", "  "],
    ["cover", "one", "two", "three", None],
])
def test_incomplete_art_plan_is_rejected_before_illustration(monkeypatch, prompts):
    monkeypatch.setattr(text_service.settings, "text_provider", "template")
    monkeypatch.setattr(text_service, "_template_fallback", lambda data: {
        "story_text": "Нина шагнула на сцену.", "image_prompts": prompts,
    })
    with pytest.raises(ValueError, match="illustration prompts"):
        text_service.generate_story_payload(questionnaire())


def test_renderer_requests_cover_then_all_four_scenes_by_default(tmp_path, monkeypatch):
    names = ["cover", "first", "second", "third", "fourth"]
    calls = []
    monkeypatch.setattr(image_service.settings, "images_dir", str(tmp_path))
    monkeypatch.setattr(image_service.settings, "image_provider", "openai")
    monkeypatch.setattr(image_service, "_build_prompt", lambda scene, *args, **kwargs: scene)

    def fake_image(scene, *args, **kwargs):
        calls.append(scene)
        return f"{scene}.png"

    monkeypatch.setattr(image_service, "_generate_single", fake_image)
    urls, _ = image_service.generate_images("Нина", 7, "nature", None, scene_prompts=names)
    assert calls == names
    assert len(urls) == EXPECTED_IMAGES == 5


def test_missing_final_scene_never_reaches_an_image_provider(monkeypatch):
    def unexpected_request(*args, **kwargs):
        pytest.fail("An incomplete plan must not spend an image request")

    monkeypatch.setattr(image_service, "_generate_single", unexpected_request)
    with pytest.raises(ValueError, match="illustration prompts"):
        image_service.generate_images("Нина", 7, "nature", None,
                                      scene_prompts=["cover", "one", "two", "three"])
