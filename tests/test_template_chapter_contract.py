"""Check the scene pictured for each chapter in both offline storylines."""
import pytest

from backend.app.services import text_service
from backend.app.story_structure import story_sections


@pytest.mark.parametrize("episode,chapter,story_detail,prompt_details", [
    pytest.param(2, 1, "Из-за широкого дерева", ("talking кот", "broad tree"), id="guardian-meeting"),
    pytest.param(2, 2, "Они перешли молча", ("wooden bridge", "total silence"), id="guardian-bridge"),
    pytest.param(2, 3, "седой старичок", ("wise old man", "small house"), id="guardian-keeper"),
    pytest.param(2, 4, "Страж открыл глаза", ("waking guardian", "wooden door"), id="guardian-wakes"),
    pytest.param(1, 1, "Краски будто смыло", ("faded grey", "warmly glowing"), id="colours-lost"),
    pytest.param(1, 2, "дорогу перегородил Туманный Страж", ("misty guardian", "grey path"), id="colours-path"),
    pytest.param(1, 3, "сидело маленькое существо", ("colourless creature", "silver cave"), id="colours-thief"),
    pytest.param(1, 4, "золотистые искры", ("fill the cave", "golden colour"), id="colours-return"),
])
def test_illustration_matches_the_event_in_its_chapter(
    monkeypatch, episode, chapter, story_detail, prompt_details,
):
    def unexpected_provider(*args, **kwargs):
        pytest.fail("An offline story must not call a text provider")

    monkeypatch.setattr(text_service.settings, "text_provider", "template")
    monkeypatch.setattr(text_service, "_call_openrouter", unexpected_provider)
    monkeypatch.setattr(text_service, "_call_openai_direct", unexpected_provider)
    story = text_service.generate_story_payload({
        "child_name": "Нина", "age": 7, "gender": "female", "style": "nature",
        "episode_number": episode, "favorite_animal": "кот", "favorite_place": "лес",
        "hobby": "рисование",
    })
    bodies = [body for title, body in story_sections(story["story_text"]) if title]
    cover, *scenes = story["image_prompts"]
    assert cover.startswith("book cover:")
    assert len(bodies) == len(scenes) == 4
    assert story_detail in "\n".join(bodies[chapter - 1])
    for detail in prompt_details:
        assert detail in scenes[chapter - 1]
