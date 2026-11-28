"""Editorial instructions and sign-off on a particular manuscript, without paid calls."""
import json
import sys
from types import SimpleNamespace

import pytest
from pypdf import PdfReader

from backend.app import editorial_review
from backend.app.services import cost_guard, pdf_service, text_service


def form(**overrides):
    return {
        "child_name": "Ренэ", "age": 7, "gender": "neutral", "style": "nature",
        "favorite_animal": "сова", "favorite_place": "горы", "hobby": "лепка из глины",
        "episode_number": 1, **overrides,
    }


@pytest.mark.parametrize("direct", [False, True], ids=["openrouter", "direct-fallback"])
def test_providers_get_one_editorial_pass_and_save_the_actual_hook(monkeypatch, direct):
    data = form()
    answer = text_service._template_fallback(data)
    answer["next_hook"] = "На четвёртой дощечке проступили две крошечные лапы."
    answer["memory"]["open_threads"] = ["Где ночует сова?"]
    calls = []
    monkeypatch.setattr(text_service.settings, "text_provider", "openrouter")
    monkeypatch.setattr(text_service.settings, "openrouter_api_key", "" if direct else "synthetic")
    monkeypatch.setattr(text_service.settings, "openai_api_key", "synthetic")
    monkeypatch.setattr(cost_guard, "check", lambda **kwargs: None)

    def router(url, *, json, **kwargs):
        calls.append(json)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
            "choices": [{"message": {"content": encoded}}]})

    def completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=encoded))])

    encoded = json.dumps(answer, ensure_ascii=False)
    monkeypatch.setattr(text_service.httpx, "post", router)
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=completion)))))
    story = text_service.generate_story_payload(data)
    assert len(calls) == 1
    prompt = calls[0]["messages"][0]["content"]
    assert all(question in prompt for question in editorial_review.CRITERIA.values())
    assert "ЭМОЦИОНАЛЬНЫЙ ГОЛОД" not in prompt and "Мама, а можно мне ещё" not in prompt
    assert story["memory"]["open_threads"] == ["Где ночует сова?", answer["next_hook"]]
    assert len(story["image_prompts"]) == 5


@pytest.mark.parametrize("episode", [1, 2])
def test_two_offline_plots_resolve_their_problem_and_carry_a_concrete_clue(monkeypatch, episode):
    monkeypatch.setattr(text_service.settings, "text_provider", "template")
    data = form(episode_number=episode)
    first = text_service.generate_story_payload(data)
    following = text_service.generate_story_payload({
        **data, "episode_number": episode + 1, "previous_memory": first["memory"],
    })
    assert first["memory"]["world_state"]["resolved"]
    assert first["next_hook"] in first["memory"]["open_threads"]
    assert first["next_hook"] not in first["story_text"]
    assert first["next_hook"] != following["next_hook"]
    assert len(first["image_prompts"]) == len(following["image_prompts"]) == 5
    introduction = following["story_text"].split("\n\n", 2)[1]
    if "стрелка" in first["next_hook"]:
        assert "под доску со стрелкой" in introduction
    else:
        assert "следы сбежали с камешка" in introduction
    assert "лепка из глины" in first["story_text"] and "в горах" in first["story_text"]
    assert "горыа" not in first["story_text"] and "глиныом" not in first["story_text"]


@pytest.mark.parametrize("as_chapters", [False, True], ids=["backend", "chapter-manuscript"])
def test_review_refuses_a_different_version_and_requires_observations(as_chapters):
    story = {"title": "Два следа", "age": 7, "next_hook": "За дверью показалась ещё одна лапка."}
    if as_chapters:
        story["chapters"] = [{"title": "Дверь", "paragraphs": ["Друзья открыли дверь."]}]
    else:
        story["story_text"] = "Глава первая. Дверь\n\nДрузья открыли дверь."
    card = editorial_review.review_form(story)
    with pytest.raises(ValueError):
        editorial_review.reviewed(story, card)
    card["reviewer"] = "Independent test reader"
    for check in card["checks"].values():
        check.update(decision="pass", location="Конец эпизода", evidence="Тестовый пример.")
    assert editorial_review.reviewed(story, card)
    with pytest.raises(ValueError, match="другую версию"):
        editorial_review.reviewed({**story, "next_hook": "Другой финал."}, card)
    with pytest.raises(ValueError, match="другую версию"):
        editorial_review.reviewed({**story, "age": 4}, card)
    del card["checks"]["speech"]["evidence"]
    with pytest.raises(ValueError, match="наблюдение"):
        editorial_review.reviewed(story, card)
    card["checks"]["speech"].update(decision="revise", evidence="Уточнить, кто открыл дверь.")
    assert not editorial_review.reviewed(story, card)
    del card["checks"]["ending"]
    with pytest.raises(ValueError, match="четырёх"):
        editorial_review.reviewed(story, card)


def test_renderer_prints_the_story_clue_once_without_a_purchase_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(text_service.settings, "text_provider", "template")
    story = text_service.generate_story_payload(form())
    monkeypatch.setattr(pdf_service.settings, "stories_dir", str(tmp_path))
    pdf_service.generate_pdf(story["title"], story["story_text"], [],
                             child_name="Ренэ", next_hook=story["next_hook"])
    text = " ".join(" ".join(page.extract_text().split()) for page in PdfReader(
        next(tmp_path.glob("*.pdf"))).pages)
    assert text.count(story["next_hook"]) == 1
    assert "Хочешь ещё одну сказку" not in text
