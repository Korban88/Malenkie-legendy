"""In-process order smoke: actual aiogram handlers, API, database and PDF engine.

Telegram events and text/image providers are synthetic. No external network or
real payment. SQLite is not evidence of PostgreSQL concurrency or crash recovery.
"""
import asyncio
import importlib
import io
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from PIL import Image, ImageDraw
from pypdf import PdfReader
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from backend.app.config import get_settings
from backend.app import book_release, private_media
from backend.app.services import pdf_service, story_service
from backend.app.models import Order, Story


def test_synthetic_order_through_real_handlers_and_api(tmp_path, monkeypatch):
    db_module = importlib.import_module("backend.app.db")
    images_dir = tmp_path / "images"
    stories_dir = tmp_path / "stories"
    images_dir.mkdir()
    stories_dir.mkdir()
    secret = "test-only-" + "x" * 40
    monkeypatch.setenv("BACKEND_INTERNAL_TOKEN", secret)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("BACKEND_URL", "http://testserver")
    monkeypatch.setenv("IMAGES_DIR", str(images_dir))
    monkeypatch.setenv("STORIES_DIR", str(stories_dir))
    # No production token or provider API is used.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:TEST_ONLY_NOT_A_REAL_TOKEN")
    get_settings.cache_clear()
    settings = get_settings()
    with patch.object(db_module.Base.metadata, "create_all"):
        main = importlib.import_module("backend.app.main")
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(pdf_service, "settings", settings)
    monkeypatch.setattr(private_media, "get_settings", lambda: settings)
    monkeypatch.setattr(book_release, "get_settings", lambda: settings)
    monkeypatch.setattr(story_service, "get_settings", lambda: settings)

    # SQLite-only type compilation for this isolated smoke. The production model
    # remains PostgreSQL JSONB; concurrency must be separately tested on PG.
    from sqlalchemy.ext.compiler import deregister

    @compiles(JSONB, "sqlite")
    def compile_test_jsonb(type_, compiler, **kwargs):
        return "JSON"

    engine = create_engine(
        "sqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    try:
        db_module.Base.metadata.create_all(engine)

        def isolated_db():
            with Session(engine) as db:
                yield db

        monkeypatch.setitem(main.app.dependency_overrides, db_module.get_db, isolated_db)

        def fake_text(payload):
            assert payload["child_name"] == "Лена"
            assert payload["age"] == 7
            assert payload["favorite_animal"] == "лиса"
            assert payload["favorite_place"] == "лес"
            paragraphs = [
                ("Глава 1. Находка", "Лена увидела свет на лесной тропинке."),
                ("Глава 2. Друг", "Лена и лиса позвали знакомого лесника."),
                ("Глава 3. Фонарь", "Вместе они вернули свет старому фонарю."),
                ("Глава 4. Домой", "Лена вернулась домой к своей семье."),
            ]
            return {
                "title": "ТЕСТ: Лена и свет",
                "story_text": "\n\n".join(a + "\n\n" + b for a, b in paragraphs),
                "image_prompts": ["test only"] * 5,
                "recap": [], "memory": {}, "next_hook": "",
            }

        def fake_images(**kwargs):
            assert kwargs["count"] == 5
            assert kwargs["photo_base64"] is None
            result = []
            for i in range(5):
                filename = uuid.uuid4().hex + ".png"
                im = Image.new("RGB", (960, 540), (35 + 30*i, 95, 140))
                ImageDraw.Draw(im).text((30, 30), f"TEST SLOT {i+1}", fill="white")
                im.save(images_dir / filename)
                result.append("https://example.invalid/files/images/" + filename)
            return result, None

        monkeypatch.setattr(story_service, "generate_story_payload", fake_text)
        monkeypatch.setattr(story_service, "generate_images", fake_images)
        bot = importlib.import_module("bot.bot")
        monkeypatch.setattr(bot, "STEP_IMAGES_DIR", tmp_path / "nonexistent-ui")
        monkeypatch.setattr(bot, "BACKEND_URL", "http://testserver")
        monkeypatch.setattr(bot, "BACKEND_INTERNAL_TOKEN", secret)
        original_async_client = httpx.AsyncClient

        def in_process_client(**kwargs):
            return original_async_client(
                transport=httpx.ASGITransport(app=main.app),
                base_url="http://testserver", **kwargs,
            )

        # Replace only the bot's client namespace, not the global HTTP library.
        monkeypatch.setattr(bot, "httpx", SimpleNamespace(
            AsyncClient=in_process_client,
            ReadTimeout=httpx.ReadTimeout,
            HTTPStatusError=httpx.HTTPStatusError,
        ))

        async def exercise():
            storage = MemoryStorage()
            state = FSMContext(storage=storage, key=StorageKey(bot_id=123456789, chat_id=42, user_id=42))
            message = SimpleNamespace(
                chat=SimpleNamespace(id=42),
                from_user=SimpleNamespace(id=42),
                text="Лена", answer=AsyncMock(), answer_photo=AsyncMock(),
                answer_document=AsyncMock(), answer_invoice=AsyncMock(),
                edit_reply_markup=AsyncMock(),
            )

            def callback(value):
                return SimpleNamespace(data=value, message=message, answer=AsyncMock())

            await bot.cb_start_story(callback("start_story"), state)
            await bot.form_name(message, state)
            await bot.cb_age(callback("age:7"), state)
            await bot.cb_gender(callback("gender:female"), state)
            await bot.cb_purpose(callback("purpose:bedtime"), state)
            await bot.cb_style(callback("style:magical"), state)
            await bot.cb_img_style(callback("img_style:watercolor"), state)
            message.text = "лиса"
            await bot.form_animal(message, state)
            await bot.cb_color(callback("color:синий"), state)
            await bot.cb_hobby(callback("hobby:рисование"), state)
            await bot.cb_place(callback("place:лес"), state)
            await bot.cb_photo_choice(callback("photo:no"), state)
            message.answer_invoice.assert_awaited_once()
            invoice = message.answer_invoice.await_args.kwargs
            assert invoice["currency"] == "XTR"
            assert invoice["prices"][0].amount == 150

            checkout = SimpleNamespace(
                invoice_payload=invoice["payload"], total_amount=150,
                currency="XTR", from_user=message.from_user, answer=AsyncMock(),
            )
            await bot.pre_checkout(checkout, state)
            assert checkout.answer.await_args.kwargs["ok"] is True
            checkout.total_amount = 1
            await bot.pre_checkout(checkout, state)
            assert checkout.answer.await_args.kwargs["ok"] is False

            message.successful_payment = SimpleNamespace(
                invoice_payload=invoice["payload"], total_amount=150,
                currency="XTR", telegram_payment_charge_id="synthetic-charge-001",
            )
            await bot.successful_payment_handler(message, state)
            message.answer_document.assert_awaited_once()
            pdf = message.answer_document.await_args.kwargs["document"]
            reader = PdfReader(io.BytesIO(pdf.data))
            assert len(reader.pages) >= 5
            assert sum(len(page.images) for page in reader.pages) >= 5
            assert "Лена" in "\n".join(page.extract_text() or "" for page in reader.pages)
            assert await state.get_state() is None
            assert message.answer_photo.await_count == 5

            # Payment replay after delivery must not create a second book.
            await bot.successful_payment_handler(message, state)
            assert message.answer_document.await_count == 1
            await storage.close()
            await bot.bot.session.close()

        asyncio.run(exercise())
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(Order)) == 1
            assert db.scalar(select(func.count()).select_from(Story)) == 1
            story = db.scalar(select(Story))
            assert story.status == "ready"
            assert story.pdf_url
    finally:
        engine.dispose()
        deregister(JSONB)
        get_settings.cache_clear()
