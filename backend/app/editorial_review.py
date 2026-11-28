"""Private, offline review of one Russian manuscript. No provider calls.

python -m backend.app.editorial_review draft.json --output review.json
An independent reader fills the four decisions and cites the passage or action.
python -m backend.app.editorial_review draft.json --review review.json
Exit 0 confirms the recorded decisions for these exact words. Exit 1 requests
a revision at the cited location. Exit 2 indicates an invalid or stale record.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path


CRITERIA = {
    "speech": "Прочитай вслух. Подбери привычные для русского уха сочетания слов. "
              "Сохрани точные, неожиданные образы, если их легко представить. "
              "Проверь управление, согласование, имена и местоимения.",
    "dialogue": "У каждой реплики есть собеседник и повод. Дай героям говорить "
                "так, как они сказали бы это в данной сцене. Длина фраз и паузы "
                "должны подходить возрасту слушателя.",
    "causality": "Проследи, что герой заметил, чего захотел и что сделал. "
                 "Из его поступка должно вытекать следующее событие. Проверь, "
                 "кто что видел и слышал, где остались предметы.",
    "ending": "Разреши главное затруднение в самой истории. Для следующей встречи "
              "оставь одну конкретную находку или загадку, которая выросла из "
              "уже показанной детали. Оставь выбор вернуться читателю. В детском "
              "финале нет просьбы уговорить взрослых купить следующую книгу.",
}


def review_form(draft: dict) -> dict:
    if not isinstance(draft, dict) or not isinstance(draft.get("title"), str) or not draft["title"].strip():
        raise ValueError("Нужно название рукописи.")
    words = {"title": draft["title"], "next_hook": draft.get("next_hook", "")}
    if not isinstance(words["next_hook"], str):
        raise ValueError("Финал должен быть текстом.")
    if "story_text" in draft:
        if not isinstance(draft["story_text"], str) or not draft["story_text"].strip():
            raise ValueError("Нужен текст эпизода.")
        words["story_text"] = draft["story_text"]
    else:
        chapters = draft.get("chapters")
        if not isinstance(chapters, list) or not chapters:
            raise ValueError("Нужны главы с абзацами или поле story_text.")
        words["chapters"] = []
        for chapter in chapters:
            if (not isinstance(chapter, dict) or not isinstance(chapter.get("title"), str)
                    or not chapter["title"].strip() or not isinstance(chapter.get("paragraphs"), list)
                    or not chapter["paragraphs"]
                    or any(not isinstance(p, str) or not p.strip() for p in chapter["paragraphs"])):
                raise ValueError("Каждой главе нужны заголовок и текст.")
            words["chapters"].append({"title": chapter["title"], "paragraphs": chapter["paragraphs"]})
    if "age" in draft:
        words["age"] = draft["age"]
    content = json.dumps(words, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return {
        "manuscript_sha256": hashlib.sha256(content).hexdigest(),
        "reviewer": "",
        "checks": {
            key: {"criterion": criterion, "decision": "", "location": "", "evidence": ""}
            for key, criterion in CRITERIA.items()
        },
    }


def reviewed(draft: dict, receipt: dict) -> bool:
    if not isinstance(receipt, dict):
        raise ValueError("Нужна редакционная карточка в формате JSON.")
    if receipt.get("manuscript_sha256") != review_form(draft)["manuscript_sha256"]:
        raise ValueError("Редактор читал другую версию текста.")
    if not isinstance(receipt.get("reviewer"), str) or not receipt["reviewer"].strip():
        raise ValueError("Укажите проверявшего редактора.")
    checks = receipt.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(CRITERIA):
        raise ValueError("Нужны результаты всех четырёх проверок.")
    accepted = True
    for key, item in checks.items():
        if not isinstance(item, dict) or item.get("decision") not in ("pass", "revise"):
            raise ValueError(f"{key}: укажите pass или revise.")
        if any(not isinstance(item.get(field), str) or not item[field].strip()
               for field in ("location", "evidence")):
            raise ValueError(f"{key}: укажите место в тексте и наблюдение редактора.")
        if item["decision"] == "revise":
            accepted = False
    return accepted


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка редакционной карточки одной сказки")
    parser.add_argument("draft", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--review", type=Path)
    mode.add_argument("--output", type=Path, help="Новая карточка UTF-8 для независимого редактора")
    args = parser.parse_args()
    try:
        draft = json.loads(args.draft.read_text(encoding="utf-8-sig"))
        if args.review is None:
            form = json.dumps(review_form(draft), ensure_ascii=False, indent=2) + "\n"
            if args.output is None:
                print(form, end="")
            else:
                with args.output.open("x", encoding="utf-8") as output:
                    output.write(form)
            return 0
        receipt = json.loads(args.review.read_text(encoding="utf-8-sig"))
        if reviewed(draft, receipt):
            print("Редактор принял эту версию.")
            return 0
        print("Нужна правка указанных фрагментов.")
        return 1
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
