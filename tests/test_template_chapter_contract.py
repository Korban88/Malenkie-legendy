"""Offline regression: the four actual chapters must match four scene slots."""
import pytest

from backend.app.services import text_service


@pytest.mark.parametrize("episode", [1, 2])
def test_actual_template_has_four_chapters_and_cover(episode, monkeypatch):
    monkeypatch.setattr(text_service.settings, "text_provider", "template")
    def forbidden(*args, **kwargs):
        pytest.fail("The offline template must not call a model")
    monkeypatch.setattr(text_service, "_call_openrouter", forbidden)
    monkeypatch.setattr(text_service, "_call_openai_direct", forbidden)
    result = text_service.generate_story_payload({
        "child_name": "Нина", "age": 7, "gender": "female",
        "style": "nature", "episode_number": episode, "favorite_animal": "кот",
        "favorite_place": "лес", "hobby": "рисование",
    })
    headings = [p for p in result["story_text"].split("\n\n") if p.startswith("Глава")]
    assert len(headings) == 4
    assert [p.split(".")[0] for p in headings] == [
        "Глава первая", "Глава вторая", "Глава третья", "Глава четвёртая",
    ]
    assert len(result["image_prompts"]) == 5
    assert result["image_prompts"][0].startswith("storybook cover:")
    assert len(set(result["image_prompts"])) == 5
    if "Мост Молчания" in headings[1]:
        assert "meeting the talking" in result["image_prompts"][1]
        assert "wooden bridge" in result["image_prompts"][2]
        assert "wise old man" in result["image_prompts"][3]
        assert "waking the enormous" in result["image_prompts"][4]
    else:
        assert "faded grey" in result["image_prompts"][1]
        assert "misty guardian" in result["image_prompts"][2]
        assert "colourless creature" in result["image_prompts"][3]
        assert "golden colour" in result["image_prompts"][4]


def make_chapters(numbers):
    return "\n\n".join(f"Глава {n}. Заголовок\n\nТекст главы." for n in numbers)


@pytest.mark.parametrize("story", [
    make_chapters([1, 2, 3]),
    make_chapters([1, 2, 3, 4, 5]),
    make_chapters([1, 3, 2, 4]),
    "Предисловие.\n\n" + make_chapters([1, 2, 3, 4]),
    make_chapters([1, 2, 3]) + "\n\nГлава 4. Без текста",
])
def test_five_prompts_do_not_make_wrong_chapter_structure_valid(story, monkeypatch):
    monkeypatch.setattr(text_service.settings, "text_provider", "template")
    monkeypatch.setattr(text_service, "_template_fallback", lambda _: {
        "story_text": story,
        "image_prompts": ["cover", "first", "second", "third", "fourth"],
    })
    with pytest.raises(ValueError, match="four ordered chapters"):
        text_service.generate_story_payload({
            "child_name": "Нина", "age": 7, "style": "nature", "episode_number": 1,
        })


def test_four_numbered_chapters_are_valid():
    text_service._require_four_chapters(make_chapters([1, 2, 3, 4]))
