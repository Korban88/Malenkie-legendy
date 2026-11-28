"""A returning Telegram buyer can retrieve a ready PDF without a new payment event."""

import asyncio
import importlib
import io
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from aiogram.types import CallbackQuery, Chat, Message, Update, User as TelegramUser
from pypdf import PdfWriter
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles, deregister
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.db import Base, get_db
from backend.app.models import Child, Order, Story, User
from backend.app.services.telegram_library import PAGE_SIZE, find_book, list_books


@pytest.fixture
def engine(tmp_path):
    @compiles(JSONB, "sqlite")
    def jsonb(type_, compiler, **kw):
        return "JSON"

    value = create_engine("sqlite:///" + (tmp_path / "synthetic.db").as_posix())
    try:
        Base.metadata.create_all(value)
        yield value
    finally:
        value.dispose()
        deregister(JSONB)


def family(db, identifier):
    buyer = User(channel="telegram", external_id=str(identifier))
    db.add(buyer)
    db.flush()
    child = Child(user_id=buyer.id, name="Тест", age=7, gender="neutral")
    db.add(child)
    db.flush()
    return buyer, child


def purchase(db, buyer, child, title, **changes):
    order = Order(user_id=buyer.id, child_id=child.id, provider="telegram_stars",
                  tariff="story", amount_rub=150, status="paid")
    db.add(order)
    db.flush()
    order.provider_payment_id = "synthetic-" + str(order.id)
    for key, value in changes.items():
        setattr(order, key, value)
    story = Story(order_id=order.id, child_id=child.id, episode_number=order.id,
                  title=title, status="ready", pdf_url="/files/stories/" + f"{order.id:032x}.pdf")
    db.add(story)
    db.flush()
    return story


def test_library_uses_one_ownership_rule_for_pages_and_documents(engine):
    with Session(engine) as db:
        buyer, child = family(db, 101)
        other, neighbour = family(db, 202)
        eligible = [purchase(db, buyer, child, str(i)).id for i in range(PAGE_SIZE + 2)]
        excluded = [
            purchase(db, other, neighbour, "Чужая"),
            purchase(db, buyer, neighbour, "Чужой ребёнок"),
            purchase(db, buyer, child, "Не оплачена", status="created"),
            purchase(db, buyer, child, "Нет квитанции", provider_payment_id=None),
            purchase(db, buyer, child, "Другой канал", provider="link"),
            purchase(db, buyer, child, "Не готова"),
            purchase(db, buyer, child, "Не тот ребёнок заказа"),
            purchase(db, buyer, child, "Нет файла"),
        ]
        excluded[-3].status = "pdf_pending"
        excluded[-2].child_id = neighbour.id
        excluded[-1].pdf_url = None
        db.commit()

        page = list_books(db, "101", None)
        second = list_books(db, "101", page["next_before_story_id"])
        assert second["next_before_story_id"] is None
        assert [row["story_id"] for row in page["books"] + second["books"]] == eligible[::-1]
        assert all("pdf_url" not in row for row in page["books"])
        assert all(find_book(db, "101", item.id) is None for item in excluded)
        assert list_books(db, "303", None)["books"] == []


def test_cold_dispatcher_lists_and_resends_only_buyers_paid_pdf(engine, tmp_path, monkeypatch):
    books_dir = tmp_path / "pdf"
    books_dir.mkdir()
    with Session(engine) as db:
        alice, child = family(db, 101)
        bob, neighbour = family(db, 202)
        first = purchase(db, alice, child, "Моя сказка")
        second = purchase(db, bob, neighbour, "Чужая сказка")
        my_id, other_id = first.id, second.id
        filename = first.pdf_url.rsplit("/", 1)[1]
        db.commit()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    encoded = io.BytesIO()
    writer.write(encoded)
    (books_dir / filename).write_bytes(encoded.getvalue())

    key = "synthetic-family-library-" + "x" * 32
    monkeypatch.setenv("STORIES_DIR", str(books_dir))
    monkeypatch.setenv("BACKEND_INTERNAL_TOKEN", key)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:TEST_ONLY_NOT_A_REAL_TOKEN")
    get_settings.cache_clear()
    with patch.object(Base.metadata, "create_all"):
        main = importlib.import_module("backend.app.main")
    monkeypatch.setattr(main, "settings", get_settings())

    def local_db():
        with Session(engine) as db:
            yield db

    monkeypatch.setitem(main.app.dependency_overrides, get_db, local_db)
    telegram = importlib.import_module("bot.bot")
    monkeypatch.setattr(telegram, "BACKEND_INTERNAL_TOKEN", key)
    monkeypatch.setattr(telegram, "BACKEND_URL", "http://synthetic.test")
    transport = httpx.ASGITransport(app=main.app)
    paths = []

    async def record(request):
        paths.append(request.url.path)

    def client(**kwargs):
        return httpx.AsyncClient(transport=transport, event_hooks={"request": [record]}, **kwargs)

    monkeypatch.setattr(telegram, "httpx", SimpleNamespace(
        AsyncClient=client, HTTPError=httpx.HTTPError, HTTPStatusError=httpx.HTTPStatusError))
    sent = AsyncMock(return_value=True)
    monkeypatch.setattr(telegram.bot.session, "make_request", sent)
    person = TelegramUser(id=101, first_name="Synthetic", is_bot=False)
    bot_user = TelegramUser(id=123456789, first_name="Test", is_bot=True)

    def message(chat, sender, text=None):
        return Message(message_id=12, date=datetime.now(timezone.utc), chat=chat, from_user=sender, text=text)

    async def tap(data, chat):
        update = Update(update_id=71, callback_query=CallbackQuery(
            id="synthetic-callback", from_user=person, chat_instance="synthetic",
            data=data, message=message(chat, bot_user, "Мои книги"),
        ))
        await telegram.dp.feed_update(telegram.bot, update)

    async def exercise():
        private = Chat(id=101, type="private")
        async with httpx.AsyncClient(transport=transport, base_url="http://synthetic.test") as http:
            assert (await http.post("/api/payments/telegram/library", json={"external_user_id": "101"})).status_code == 401
            assert (await http.get("/files/stories/" + filename)).status_code == 404
        await telegram.dp.feed_update(telegram.bot, Update(
            update_id=70, message=message(private, person, "/books"),
        ))
        menu = sent.await_args.args[1].reply_markup.inline_keyboard
        assert len(menu) == 1
        assert menu[0][0].callback_data == f"book:{my_id}"
        assert "Моя сказка" in menu[0][0].text
        await tap(f"book:{my_id}", private)
        await tap(f"book:{my_id}", private)
        await tap(f"book:{other_id}", private)
        requests_before_group = len(paths)
        await tap(f"book:{my_id}", Chat(id=-101, type="group"))
        await tap(f"book:{my_id}", Chat(id=202, type="private"))
        assert len(paths) == requests_before_group
        pdfs = [op.args[1] for op in sent.await_args_list if op.args[1].__api_method__ == "sendDocument"]
        assert len(pdfs) == 2
        assert all(doc.chat_id == 101 and doc.document.data == encoded.getvalue() for doc in pdfs)
        assert paths == ["/api/payments/telegram/library",
                         f"/api/payments/telegram/library/{my_id}", "/api/internal/files/stories/" + filename,
                         f"/api/payments/telegram/library/{my_id}", "/api/internal/files/stories/" + filename,
                         f"/api/payments/telegram/library/{other_id}"]
        await telegram.bot.session.close()

    try:
        asyncio.run(exercise())
        with Session(engine) as db:
            assert db.scalar(select(func.count(Order.id))) == 2
            assert db.scalar(select(func.count(Story.id))) == 2
    finally:
        get_settings.cache_clear()
