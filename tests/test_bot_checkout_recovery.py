"""Critical Telegram routing and fail-closed checkout regressions, no network."""

import asyncio
import importlib
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Message, SuccessfulPayment, Update, User


def bot_module(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:TEST_ONLY_NOT_A_REAL_TOKEN")
    return importlib.import_module("bot.bot")


def test_payment_update_precedes_handlers_for_a_new_questionnaire(monkeypatch):
    module = bot_module(monkeypatch)
    snapshot = {
        "external_user_id": "42", "child_id": 1, "order_id": 7,
        "child_name": "Сохранённая анкета", "telegram_payment_charge_id": "test-charge",
    }
    checkout = AsyncMock(return_value={
        "order_id": 7, "generation_payload": snapshot, "photo_file_id": None,
    })
    generate = AsyncMock()
    monkeypatch.setattr(module, "_checkout_request", checkout)
    monkeypatch.setattr(module, "_generate", generate)
    # Answer methods go through the real Bot, but the network boundary is inert.
    monkeypatch.setattr(module.bot.session, "make_request", AsyncMock(return_value=True))

    async def exercise():
        key = StorageKey(bot_id=module.bot.id, chat_id=42, user_id=42)
        state = FSMContext(storage=module.dp.storage, key=key)
        await state.set_state(module.Form.name)
        await state.set_data({"child_name": "Новая анкета"})
        update = Update(update_id=901, message=Message(
            message_id=51, date=datetime.now(timezone.utc),
            chat=Chat(id=42, type="private"),
            from_user=User(id=42, is_bot=False, first_name="Synthetic"),
            successful_payment=SuccessfulPayment(
                currency="XTR", total_amount=150, invoice_payload="synthetic-invoice",
                telegram_payment_charge_id="test-charge", provider_payment_charge_id="",
            ),
        ))
        await module.dp.feed_update(module.bot, update)
        generate.assert_awaited_once()
        assert generate.await_args.args[2] == snapshot
        assert checkout.await_args.args[1]["external_user_id"] == "42"
        assert (await state.get_data())["child_name"] == "Новая анкета"
        await state.clear()
        await module.bot.session.close()

    asyncio.run(exercise())


def test_no_telegram_invoice_when_durable_save_fails(monkeypatch):
    module = bot_module(monkeypatch)
    monkeypatch.setattr(module, "_checkout_request", AsyncMock(side_effect=RuntimeError("offline")))

    async def exercise():
        storage = MemoryStorage()
        state = FSMContext(storage=storage, key=StorageKey(bot_id=123456789, chat_id=42, user_id=42))
        await state.set_data({"child_name": "Тест", "age": 7})
        message = SimpleNamespace(chat=SimpleNamespace(id=42), answer=AsyncMock(), answer_invoice=AsyncMock())
        await module._request_payment(message, state)
        message.answer_invoice.assert_not_awaited()
        assert await state.get_state() != module.Form.awaiting_payment.state
        await storage.close()

    asyncio.run(exercise())


def test_start_command_can_replace_a_form_while_invoice_is_pending(monkeypatch):
    module = bot_module(monkeypatch)
    answer_step = AsyncMock()
    monkeypatch.setattr(module, "_answer_step", answer_step)
    monkeypatch.setattr(module.bot.session, "make_request", AsyncMock(return_value=True))

    async def exercise():
        key = StorageKey(bot_id=module.bot.id, chat_id=42, user_id=42)
        state = FSMContext(storage=module.dp.storage, key=key)
        await state.set_state(module.Form.awaiting_payment)
        await state.set_data({"order_id": 7})
        update = Update(update_id=902, message=Message(
            message_id=52, date=datetime.now(timezone.utc), text="/start",
            chat=Chat(id=42, type="private"),
            from_user=User(id=42, is_bot=False, first_name="Synthetic"),
        ))
        await module.dp.feed_update(module.bot, update)
        answer_step.assert_awaited_once()
        assert await state.get_state() is None
        assert await state.get_data() == {}
        await module.bot.session.close()

    asyncio.run(exercise())


def test_photo_form_persists_reference_without_downloading_bytes(monkeypatch):
    module = bot_module(monkeypatch)
    request_payment = AsyncMock()
    get_file = AsyncMock()
    monkeypatch.setattr(module, "_request_payment", request_payment)
    monkeypatch.setattr(module.bot, "get_file", get_file)

    async def exercise():
        storage = MemoryStorage()
        state = FSMContext(storage=storage, key=StorageKey(bot_id=123456789, chat_id=42, user_id=42))
        message = SimpleNamespace(
            photo=[SimpleNamespace(file_id="synthetic-file-reference")], answer=AsyncMock(),
        )
        await module.form_photo(message, state)
        data = await state.get_data()
        assert data["photo_file_id"] == "synthetic-file-reference"
        assert data["photo_consent"] is True
        assert data.get("photo_base64") is None
        get_file.assert_not_awaited()
        request_payment.assert_awaited_once()
        await storage.close()

    asyncio.run(exercise())
