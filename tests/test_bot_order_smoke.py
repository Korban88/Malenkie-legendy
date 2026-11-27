"""In-process order smoke: actual aiogram handlers, API, database and PDF engine.

Telegram events and text/image providers are synthetic. No external network or
real payment. SQLite is not evidence of PostgreSQL concurrency or crash recovery.
"""
import asyncio
import base64
import importlib
import io
import os
import uuid

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from PIL import Image, ImageDraw
from pypdf import PdfReader
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from backend.app.config import get_settings
from backend.app import book_release, private_media
from backend.app.services import pdf_service, story_service
from backend.app.models import Order, Story


@pytest.mark.parametrize("db_kind", ["sqlite", "postgresql"])
@pytest.mark.parametrize("with_photo", [False, True])
@pytest.mark.parametrize("preview_failure", [False, True])
@pytest.mark.parametrize("progress_failure", [False, True])
def test_synthetic_order_through_real_handlers_and_api(tmp_path, monkeypatch, db_kind, with_photo, preview_failure, progress_failure):
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

    pg_admin = None
    schema = None
    if db_kind == "postgresql":
        dsn = os.getenv("LEGENDKIDS_TEST_POSTGRES_DSN")
        if not dsn:
            deregister(JSONB)
            pytest.skip("Dedicated loopback test PostgreSQL not configured")
        url = make_url(dsn)
        if (url.drivername != "postgresql+psycopg"
                or url.host not in {"127.0.0.1", "localhost"}
                or url.database != "legendkids_test"
                or url.username != "legendkids_test"
                or url.query):
            deregister(JSONB)
            raise RuntimeError("Only the dedicated loopback legendkids_test DB is allowed")
        schema = "lk_smoke_" + uuid.uuid4().hex
        pg_admin = create_engine(url)
        with pg_admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
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

        generation_calls = []

        def fake_text(payload):
            generation_calls.append(payload)
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
            expected_photo = base64.b64encode(b"synthetic-photo").decode() if with_photo else None
            assert kwargs["photo_base64"] == expected_photo
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
        get_photo = AsyncMock(return_value=SimpleNamespace(file_path="synthetic.png"))
        download_photo = AsyncMock(return_value=io.BytesIO(b"synthetic-photo"))
        monkeypatch.setattr(bot.bot, "get_file", get_photo)
        monkeypatch.setattr(bot.bot, "download_file", download_photo)
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
            if with_photo:
                await bot.cb_photo_choice(callback("photo:yes"), state)
                message.photo = [SimpleNamespace(file_id="synthetic-photo-reference")]
                await bot.form_photo(message, state)
            else:
                await bot.cb_photo_choice(callback("photo:no"), state)
            amount = 200 if with_photo else 150
            message.answer_invoice.assert_awaited_once()
            invoice = message.answer_invoice.await_args.kwargs
            assert invoice["currency"] == "XTR"
            assert invoice["prices"][0].amount == amount

            # The invoice exists in a new DB session BEFORE Telegram payment.
            with Session(engine) as observer:
                unpaid = observer.scalar(select(Order))
                assert unpaid.status == "created"
                assert unpaid.provider_payment_id is None
                assert unpaid.meta["questionnaire_v1"]["child_name"] == "Лена"
                assert observer.scalar(select(func.count()).select_from(Story)) == 0

            # A fresh MemoryStorage models loss of every conversational field.
            # Checkout must still use the committed invoice and original price.
            await storage.close()
            storage = MemoryStorage()
            state = FSMContext(storage=storage, key=StorageKey(bot_id=123456789, chat_id=42, user_id=42))
            assert not await state.get_data()

            checkout = SimpleNamespace(
                invoice_payload=invoice["payload"], total_amount=amount,
                currency="XTR", from_user=message.from_user, answer=AsyncMock(),
            )
            await bot.pre_checkout(checkout, state)
            assert checkout.answer.await_args.kwargs["ok"] is True
            checkout.total_amount = 1
            await bot.pre_checkout(checkout, state)
            assert checkout.answer.await_args.kwargs["ok"] is False

            message.successful_payment = SimpleNamespace(
                invoice_payload=invoice["payload"], total_amount=amount,
                currency="XTR", telegram_payment_charge_id="synthetic-charge-001",
            )
            # A second memory loss between checkout approval and receipt must
            # not lose the paid order, either.
            await storage.close()
            storage = MemoryStorage()
            state = FSMContext(storage=storage, key=StorageKey(bot_id=123456789, chat_id=42, user_id=42))
            rejected_progress = []
            if progress_failure:
                async def reject_progress(text, **kwargs):
                    if "Подготавливаю книгу" in text or "Создаю персональную сказку" in text:
                        rejected_progress.append(True)
                        raise TelegramBadRequest(
                            method=SendMessage(chat_id=42, text="synthetic progress"),
                            message="synthetic Telegram progress rejection",
                        )
                message.answer.side_effect = reject_progress
            await bot.successful_payment_handler(message, state)
            assert len(rejected_progress) == (2 if progress_failure else 0)
            message.answer.side_effect = None
            message.answer_document.assert_awaited_once()
            pdf = message.answer_document.await_args.kwargs["document"]
            reader = PdfReader(io.BytesIO(pdf.data))
            assert len(reader.pages) >= 5
            assert sum(len(page.images) for page in reader.pages) >= 5
            assert "Лена" in "\n".join(page.extract_text() or "" for page in reader.pages)
            assert await state.get_state() is None
            assert message.answer_photo.await_count == 5

            # A replay returns the SAME document from the saved paid order.
            # Redelivery is at-least-once; it must not re-run paid generation.
            # A newer questionnaire must remain untouched by an old payment.
            await state.set_state(bot.Form.name)
            await state.update_data(child_name="Новая анкета")
            assert get_photo.await_count == int(with_photo)
            assert download_photo.await_count == int(with_photo)
            get_photo.side_effect = RuntimeError("original photo no longer available")
            rejected_previews = []
            if preview_failure:
                async def reject_preview(text, **kwargs):
                    if "Лена увидела свет" in text:
                        rejected_previews.append(True)
                        raise TelegramBadRequest(
                            method=SendMessage(chat_id=42, text="synthetic preview"),
                            message="synthetic Telegram preview rejection",
                        )
                message.answer.side_effect = reject_preview
            await bot.successful_payment_handler(message, state)
            assert len(rejected_previews) == int(preview_failure)
            if preview_failure:
                assert "Предпросмотр в чате мог быть неполным" in message.answer.await_args.args[0]
            assert get_photo.await_count == int(with_photo)
            assert download_photo.await_count == int(with_photo)
            assert message.answer_document.await_count == 2
            assert message.answer_document.await_args.kwargs["document"].data == pdf.data
            assert len(generation_calls) == 1
            assert await state.get_state() == bot.Form.name.state
            assert (await state.get_data())["child_name"] == "Новая анкета"
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
        if pg_admin is not None:
            try:
                with pg_admin.begin() as conn:
                    conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            finally:
                pg_admin.dispose()
        deregister(JSONB)
        get_settings.cache_clear()
