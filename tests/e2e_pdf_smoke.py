"""Generate a reproducible *synthetic* 5-image book using the real PDF engine.

This tests existing FPDF layout, font handling and embedding, not LLM, aiogram,
payment verification or real art quality. No provider call, network, secret or
customer data. Run from repository root:
    python tests/e2e_pdf_smoke.py --out artifacts/synthetic-book
"""
import argparse
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CHAPTERS = [
    (
        "Глава 1. Необычная находка",
        "Однажды в лесу заблестела маленькая звезда. Лена и её друг Лис "
        "заметили сияние рядом со старым деревом. Никто не знал, как звезда "
        "оказалась на земле. Друзья решили не торопиться и внимательно "
        "посмотреть вокруг. На ветке сидела сова и показывала крылом "
        "в сторону старой тропинки.",
    ),
    (
        "Глава 2. Дорога к огоньку",
        "Лена и Лис отправились к тропинке вместе со знакомым лесником. "
        "Он объяснил, как безопасно пройти между деревьями, не мешая "
        "лесным жителям. Маленькая звезда всё ещё светилась у Лены "
        "в ладонях. С каждым шагом она становилась ярче. На поляне "
        "путешественники увидели забытый деревянный фонарь.",
    ),
    (
        "Глава 3. Доброе дело",
        "В фонаре не хватало светящегося стекла. Лесник осторожно "
        "поставил звезду внутрь, а Лена помогла ему очистить "
        "стёкла от пыли. Лис принёс сухие листья для мягкой подстилки. "
        "Когда фонарь заработал, его свет стал виден со всех "
        "лесных дорожек. Сова радостно захлопала крыльями.",
    ),
    (
        "Глава 4. Начало новой истории",
        "Вечером друзья вернулись домой, довольные общим делом. "
        "Лена поняла, что большую пользу можно принести и маленькими "
        "добрыми поступками. Перед сном она выглянула в окно. "
        "На далёком холме мерцал ещё один огонёк. "
        "На этот раз никто не спешил: новые приключения могли "
        "подождать до следующего дня.",
    ),
]

COLORS = [
    ((58, 89, 73), (245, 216, 152)),
    ((77, 105, 130), (231, 200, 146)),
    ((101, 117, 90), (250, 228, 168)),
    ((117, 93, 83), (239, 215, 180)),
    ((67, 93, 111), (250, 215, 141)),
]


def _font(size: int):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for path in paths:
        if Path(path).is_file():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _synthetic_image(path: Path, slot: int):
    """Clear neutral test illustration; should never be mistaken for product art."""
    background, accent = COLORS[slot]
    canvas = Image.new("RGB", (960, 540), background)
    draw = ImageDraw.Draw(canvas)
    draw.ellipse((555, 65, 800, 310), fill=accent)
    draw.polygon([(0, 500), (280, 290), (535, 490), (830, 310), (960, 490)], fill=(120, 151, 128))
    draw.rounded_rectangle((24, 18, 530, 86), radius=13, fill=(255, 248, 226))
    draw.text((38, 31), f"TEST IMAGE SLOT {slot + 1}/5", fill=(37, 46, 39), font=_font(31))
    draw.text((38, 448), "SYNTHETIC ART - NOT FOR SALE", fill=(255, 245, 231), font=_font(24))
    canvas.save(path, format="PNG")


def produce(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    images_dir = out / "images"
    stories_dir = out / "stories"
    images_dir.mkdir(exist_ok=True)
    stories_dir.mkdir(exist_ok=True)

    os.environ["STORIES_DIR"] = str(stories_dir.resolve())
    os.environ["IMAGES_DIR"] = str(images_dir.resolve())
    os.environ["PUBLIC_BASE_URL"] = "https://test.example.invalid"

    # Environment must be set before modules with cached Settings are imported.
    from backend.app.config import get_settings
    get_settings.cache_clear()
    from backend.app.services.pdf_service import generate_pdf

    urls = []
    for n in range(5):
        filename = uuid.uuid4().hex + ".png"
        _synthetic_image(images_dir / filename, n)
        urls.append(f"https://test.example.invalid/files/images/{filename}")

    story_text = "\n\n".join(
        heading + "\n\n" + paragraph for heading, paragraph in CHAPTERS
    )
    url = generate_pdf(
        title="ТЕСТ: Лена и фонарь добрых историй",
        story_text=story_text,
        image_urls=urls,
        child_name="Лена",
        episode_number=1,
        gender="female",
        next_hook="Впереди ждёт ещё одна сказка!",
    )
    filename = urlsplit(url).path.rsplit("/", 1)[-1]
    pdf_path = stories_dir / filename

    if not pdf_path.is_file():
        raise AssertionError(f"No PDF output: {pdf_path}")
    raw = pdf_path.read_bytes()
    if not raw.startswith(b"%PDF-"):
        raise AssertionError("PDF signature missing")

    reader = PdfReader(str(pdf_path))
    pages = len(reader.pages)
    if pages < 5:
        raise AssertionError(f"Unexpected page count: {pages}")
    total_images = sum(len(page.images) for page in reader.pages)
    if total_images < 5:
        raise AssertionError(f"Expected 5 real embedded test images; got {total_images}")
    all_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if "Глава 1" not in all_text or "Глава 4" not in all_text:
        raise AssertionError("Chapter text missing from rendered PDF")
    if "Лена" not in all_text:
        raise AssertionError("Sample child name missing from PDF")

    manifest = {
        "kind": "SYNTHETIC_PDF_ENGINE_SMOKE_ONLY",
        "status": "passed",
        "engine": "backend.app.services.pdf_service.generate_pdf",
        "provider_calls": 0,
        "live_payments": 0,
        "image_slots": 5,
        "embedded_pdf_images": total_images,
        "pages": pages,
        "pdf_file": str(pdf_path.resolve()),
        "pdf_bytes": len(raw),
        "pdf_sha256": hashlib.sha256(raw).hexdigest(),
        "limitations": [
            "Does not exercise the Telegram FSM, database, actual checkout or AI providers",
            "Story and pictures are deliberately synthetic and NOT customer-ready",
            "Independent literary and visual review is still required",
        ],
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts" / "synthetic-book")
    args = parser.parse_args()
    try:
        print(json.dumps(produce(args.out), ensure_ascii=False, indent=2))
    except Exception as exc:
        print("SYNTHETIC PDF GATE FAILED:", type(exc).__name__, str(exc), file=sys.stderr)
        sys.exit(1)
