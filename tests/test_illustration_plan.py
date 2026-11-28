"""The reference book and the paid product have a cover and four chapter scenes."""
import json

import pytest

from backend.app.book_release import EXPECTED_IMAGES
from backend.app.services import image_service, text_service
from backend.app.story_structure import story_sections


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


@pytest.mark.parametrize("episode", [1, 2])
def test_real_fallback_pairs_each_of_four_chapters_with_a_scene(monkeypatch, episode):
    monkeypatch.setattr(text_service.settings, "text_provider", "template")
    result = text_service.generate_story_payload({**questionnaire(), "episode_number": episode})
    sections = story_sections(result["story_text"])
    assert [title.split(".")[0] for title, _ in sections] == [
        "Глава первая", "Глава вторая", "Глава третья", "Глава четвёртая",
    ]
    assert all(paragraphs for _, paragraphs in sections)
    cover, *scenes = result["image_prompts"]
    assert cover.startswith("book cover:") and len(scenes) == 4
    assert len(set(result["image_prompts"])) == 5


@pytest.mark.parametrize("story", [
    "Описание без глав.",
    "\n".join(f"Глава {n}. Событие\nНина входит." for n in range(1, 6)),
    "\n".join(f"Глава {n}. Событие\nНина входит." for n in (1, 2, 4, 4)),
    "Глава 1. А\nТекст.\nГлава 2. Б\nТекст.\nГлава 3. В\nГлава 4. Г\nТекст.",
])
def test_invalid_chapter_structure_stops_before_art(monkeypatch, story):
    monkeypatch.setattr(text_service.settings, "text_provider", "template")
    monkeypatch.setattr(text_service, "_template_fallback", lambda _: {
        "story_text": story, "image_prompts": ["cover", "one", "two", "three", "four"],
    })
    with pytest.raises(ValueError, match="Four nonempty chapters"):
        text_service.generate_story_payload(questionnaire())
