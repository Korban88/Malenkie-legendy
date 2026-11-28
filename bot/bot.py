import base64
import hashlib
import os
import asyncio
import uuid
import re
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile,
    FSInputFile,
    LabeledPrice,
    PreCheckoutQuery,
)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8010")
BACKEND_INTERNAL_TOKEN = os.getenv("BACKEND_INTERNAL_TOKEN", "")

STORY_PRICE_XTR = 150           # Telegram Stars, без фото
STORY_WITH_PHOTO_PRICE_XTR = 200  # Telegram Stars, с фото

STEP_IMAGES_DIR = Path('/opt/malenkie-legendy/static/ui')
STEP_IMAGES: dict[str, str] = {
    'welcome':       'welcome.png',
    'ask_name':      'ask_name.png',
    'ask_age':       'ask_age.png',
    'ask_gender':    'ask_gender.png',
    'ask_purpose':   'ask_purpose.png',
    'ask_style':     'ask_style.png',
    'ask_img_style': 'ask_img_style.png',
    'ask_animal':    'ask_animal.png',
    'ask_color':     'ask_color.png',
    'ask_hobby':     'ask_hobby.png',
    'ask_place':     'ask_place.png',
    'ask_photo':     'ask_photo.png',
    'generating':    'generating.png',
}


def age_word(age: int) -> str:
    """Правильное склонение: 1 год, 2-4 года, 5+ лет."""
    if age % 10 == 1 and age % 100 != 11:
        return f"{age} год"
    if age % 10 in (2, 3, 4) and age % 100 not in (12, 13, 14):
        return f"{age} года"
    return f"{age} лет"


def _genitive(name: str) -> str:
    """Rough Russian name → genitive case (родительный падеж) heuristic."""
    if not name:
        return name
    last = name[-1].lower()
    if last == 'а':
        pre = name[-2].lower() if len(name) > 1 else ''
        # After shibilants (ж/ш/щ/ч) and г/к/х → -и; otherwise → -ы
        return name[:-1] + ('и' if pre in 'жшщчгкх' else 'ы')
    if last == 'я':
        return name[:-1] + 'и'
    if last == 'й':
        return name[:-1] + 'я'
    if last == 'ь':
        return name[:-1] + 'я'
    # Consonant ending — typically masculine names like Иван, Максим
    if last in 'бвгджзклмнпрстфхцчшщ':
        return name + 'а'
    return name


async def _answer_step(target: Message, step_id: str, text: str, **kwargs) -> Message:
    """Send a step illustration with caption. Falls back to text-only if image missing."""
    img_path = STEP_IMAGES_DIR / STEP_IMAGES.get(step_id, '')
    if img_path.exists():
        return await target.answer_photo(
            photo=FSInputFile(img_path),
            caption=text,
            **kwargs,
        )
    return await target.answer(text, **kwargs)


bot = Bot(BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


# ---------------------------------------------------------------------------
# FSM states
# ---------------------------------------------------------------------------

class Form(StatesGroup):
    name = State()
    age = State()
    gender = State()
    purpose = State()       # NEW: для чего нужна сказка
    style = State()
    img_style = State()
    animal = State()
    color = State()
    hobby = State()
    place = State()
    photo_choice = State()
    photo_upload = State()
    awaiting_payment = State()


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------

def kb_start() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Создать сказку", callback_data="start_story")],
        [InlineKeyboardButton(text="Мои книги", callback_data="books")],
    ])


def kb_age() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=str(a), callback_data=f"age:{a}") for a in range(3, 7)],
        [InlineKeyboardButton(text=str(a), callback_data=f"age:{a}") for a in range(7, 12)],
    ])


def kb_gender() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="👦 Мальчик", callback_data="gender:male"),
        InlineKeyboardButton(text="👧 Девочка", callback_data="gender:female"),
    ]])


def kb_purpose() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🦁 Стать смелее", callback_data="purpose:brave"),
            InlineKeyboardButton(text="😨 Справиться со страхом", callback_data="purpose:fear"),
        ],
        [
            InlineKeyboardButton(text="🎨 Открыть творца в себе", callback_data="purpose:creativity"),
            InlineKeyboardButton(text="🤝 Научиться дружить", callback_data="purpose:friendship"),
        ],
        [
            InlineKeyboardButton(text="⭐ Поверить в себя", callback_data="purpose:confidence"),
            InlineKeyboardButton(text="🌙 Просто сказка на ночь", callback_data="purpose:bedtime"),
        ],
    ])


def kb_style() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🧙 Волшебная", callback_data="style:magic"),
            InlineKeyboardButton(text="🗺 Приключение", callback_data="style:adventure"),
        ],
        [
            InlineKeyboardButton(text="🌿 О природе", callback_data="style:nature"),
            InlineKeyboardButton(text="🚀 Космос", callback_data="style:space"),
        ],
        [
            InlineKeyboardButton(text="🌙 Нежная (малышам)", callback_data="style:tender"),
            InlineKeyboardButton(text="⚔️ Эпическая", callback_data="style:epic"),
        ],
    ])


def kb_img_style() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎨 Акварель", callback_data="img_style:watercolor"),
            InlineKeyboardButton(text="🌸 Студия Гибли", callback_data="img_style:ghibli"),
        ],
        [
            InlineKeyboardButton(text="🎭 Советская анимация", callback_data="img_style:soviet"),
            InlineKeyboardButton(text="🎬 Pixar", callback_data="img_style:pixar"),
        ],
        [
            InlineKeyboardButton(text="🖍 Мультик", callback_data="img_style:cartoon"),
            InlineKeyboardButton(text="📖 Книжная", callback_data="img_style:storybook"),
        ],
    ])


def kb_color() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔴 Красный", callback_data="color:красный"),
            InlineKeyboardButton(text="🔵 Синий", callback_data="color:синий"),
            InlineKeyboardButton(text="🟢 Зелёный", callback_data="color:зелёный"),
        ],
        [
            InlineKeyboardButton(text="🟡 Жёлтый", callback_data="color:жёлтый"),
            InlineKeyboardButton(text="🟣 Фиолетовый", callback_data="color:фиолетовый"),
            InlineKeyboardButton(text="🩷 Розовый", callback_data="color:розовый"),
        ],
    ])


def kb_hobby() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎨 Рисование", callback_data="hobby:рисование"),
            InlineKeyboardButton(text="⚽ Спорт", callback_data="hobby:спорт"),
        ],
        [
            InlineKeyboardButton(text="🎵 Музыка", callback_data="hobby:музыка"),
            InlineKeyboardButton(text="📚 Чтение", callback_data="hobby:чтение"),
        ],
        [
            InlineKeyboardButton(text="🎮 Игры", callback_data="hobby:игры"),
            InlineKeyboardButton(text="🍳 Готовка", callback_data="hobby:готовка"),
        ],
        [
            InlineKeyboardButton(text="🔬 Наука/опыты", callback_data="hobby:наука"),
            InlineKeyboardButton(text="🌱 Садоводство", callback_data="hobby:садоводство"),
        ],
    ])


def kb_place() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🌲 Волшебный лес", callback_data="place:лес"),
            InlineKeyboardButton(text="🌊 Берег моря", callback_data="place:море"),
        ],
        [
            InlineKeyboardButton(text="🏔 Горы", callback_data="place:горы"),
            InlineKeyboardButton(text="🏰 Замок", callback_data="place:замок"),
        ],
        [
            InlineKeyboardButton(text="🚀 Космос", callback_data="place:космос"),
            InlineKeyboardButton(text="🌆 Волшебный город", callback_data="place:город"),
        ],
    ])


def kb_photo_choice() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📷 Добавить фото", callback_data="photo:yes"),
        InlineKeyboardButton(text="➡️ Пропустить", callback_data="photo:no"),
    ]])


def kb_after_story(pdf_url: str | None, episode: int, child_name: str) -> InlineKeyboardMarkup:
    # Never expose private PDF via a permanently accessible URL. The purchased
    # document is sent as a Telegram attachment below.
    buttons = []
    next_label = f"✨ Продолжение ({child_name}, эп. {episode + 1})" if episode > 1 else "✨ Ещё сказку"
    buttons.append([InlineKeyboardButton(text=next_label, callback_data="start_story")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ---------------------------------------------------------------------------
# Оплата (Telegram Stars): registered before all form handlers
# ---------------------------------------------------------------------------

async def _checkout_request(endpoint: str, payload: dict, *, timeout: float = 8) -> dict:
    if not BACKEND_INTERNAL_TOKEN or len(BACKEND_INTERNAL_TOKEN) < 32:
        raise RuntimeError("Checkout is not configured")
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{BACKEND_URL.rstrip('/')}/api/payments/telegram/{endpoint}",
            json=payload,
            headers={"X-Legend-Internal-Key": BACKEND_INTERNAL_TOKEN},
        )
        response.raise_for_status()
        return response.json()


async def _request_payment(trigger_message: Message, state: FSMContext):
    # A callback's message is authored by the bot. The FSM key identifies the
    # actual customer. Personalized invoices/delivery are private-chat only.
    payer_id = state.key.user_id
    if trigger_message.chat.id != payer_id:
        await trigger_message.answer("Оформите персональную книгу в личном чате с ботом.")
        return
    data = await state.get_data()
    request_id = data.get("invoice_request_id") or uuid.uuid4().hex
    await state.update_data(invoice_request_id=request_id)
    allowed = (
        "child_id", "child_name", "age", "gender", "style", "image_style",
        "purpose", "parent_note", "favorite_animal", "favorite_color",
        "hobby", "favorite_place", "photo_enabled", "photo_consent", "photo_file_id",
    )
    payload = {key: data[key] for key in allowed if key in data}
    payload.update(external_user_id=str(payer_id), channel="telegram",
                   client_request_id=request_id)
    try:
        # The server commits the questionnaire and price BEFORE Telegram sees
        # an invoice. FSM is now only a disposable form, never payment evidence.
        invoice = await _checkout_request("invoices", payload)
    except Exception:
        await trigger_message.answer(
            "Не удалось подготовить счёт. Оплата не начата. Попробуйте позже."
        )
        return

    child_name = invoice["child_name"]
    photo_enabled = invoice["photo_enabled"]
    tariff_label = "с иллюстрацией по фото" if photo_enabled else "с иллюстрациями"
    await state.update_data(
        invoice_payload=invoice["invoice_payload"], order_id=invoice["order_id"],
    )
    await state.set_state(Form.awaiting_payment)
    await trigger_message.answer_invoice(
        title=f"Сказка для {child_name}",
        description=f"Персональная сказка {tariff_label} — 1 эпизод",
        payload=invoice["invoice_payload"],
        currency=invoice["currency"],
        prices=[LabeledPrice(label="Сказка", amount=invoice["total_amount"])],
    )


@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery, state: FSMContext):
    try:
        result = await _checkout_request("precheckout", {
            "invoice_payload": query.invoice_payload,
            "external_user_id": str(query.from_user.id),
            "currency": query.currency,
            "total_amount": query.total_amount,
        }, timeout=5)
        valid = result.get("ok") is True
    except Exception:
        valid = False
    await query.answer(
        ok=valid,
        error_message=None if valid else "Не удалось подтвердить счёт. Оплата не принята; попробуйте позже.",
    )


@dp.message(F.successful_payment)
async def successful_payment_handler(message: Message, state: FSMContext):
    paid = message.successful_payment
    if message.chat.id != message.from_user.id:
        await message.answer("Платёж требует проверки. Откройте личный чат с ботом; повторно платить не нужно.")
        return
    try:
        receipt = await _checkout_request("receipts", {
            "invoice_payload": paid.invoice_payload,
            "external_user_id": str(message.from_user.id),
            "currency": paid.currency,
            "total_amount": paid.total_amount,
            "telegram_payment_charge_id": paid.telegram_payment_charge_id,
        })
    except Exception:
        # A durable bot inbox is still required for backend outages. Do not
        # claim a receipt was saved if that write could not be confirmed.
        await message.answer(
            "Telegram подтвердил оплату, но сервис пока не подтвердил сохранение платежа. "
            "Повторно платить не нужно. Заказ требует проверки."
        )
        return
    data = receipt["generation_payload"]
    ready_story_id = receipt.get("ready_story_id")
    if ready_story_id is not None:
        # Receipt acceptance checked the payer, charge, and invoice.
        # A ready book must not depend on continued availability of the photo.
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(
                    f"{BACKEND_URL.rstrip('/')}/api/story/{ready_story_id}",
                    headers={"X-Legend-Internal-Key": BACKEND_INTERNAL_TOKEN},
                )
                response.raise_for_status()
                result = response.json()
            if (result.get("story_id") != ready_story_id
                    or result.get("child_id") != data["child_id"]):
                raise ValueError("Saved story does not match the paid order")
        except Exception:
            await message.answer(
                "Платёж сохранён, но готовую книгу пока не удалось получить. "
                "Повторно платить не нужно."
            )
            return
        await _deliver_generated_book(message, state, data, result)
        return
    try:
        await message.answer(f"Оплата заказа №{receipt['order_id']} сохранена. Подготавливаю книгу.")
    except TelegramAPIError:
        # The receipt is already committed. A rejected status message must not
        # strand this paid order before generation starts.
        pass
    await _generate(message, state, data, photo_file_id=receipt.get("photo_file_id"))


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

async def _show_books(message: Message, reader_id: int, before: int | None = None):
    try:
        page = await _checkout_request("library", {
            "external_user_id": str(reader_id), "before_story_id": before,
        })
    except (httpx.HTTPError, RuntimeError, ValueError):
        await message.answer("Не удалось открыть книги. Попробуйте /books позже.")
        return
    if not page["books"]:
        await message.answer("Готовых оплаченных книг здесь пока нет.")
        return
    rows = []
    for book in page["books"]:
        title = (book["title"] or "Сказка").strip()[:54]
        rows.append([InlineKeyboardButton(
            text=f"{book['episode_number']}. {title}", callback_data=f"book:{book['story_id']}",
        )])
    if page["next_before_story_id"] is not None:
        rows.append([InlineKeyboardButton(
            text="Ранее", callback_data=f"books:{page['next_before_story_id']}",
        )])
    await message.answer("Выберите книгу, чтобы получить PDF.", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.message(Command("books"))
async def cmd_books(message: Message):
    if message.from_user is None or message.chat.type != "private" or message.chat.id != message.from_user.id:
        await message.answer("Откройте /books в личном чате с ботом.")
        return
    await _show_books(message, message.from_user.id)


@dp.callback_query(F.data == "books")
@dp.callback_query(F.data.regexp(r"^(?:book|books):[1-9][0-9]{0,9}$"))
async def select_book(call: CallbackQuery):
    message = call.message
    if not isinstance(message, Message) or message.chat.type != "private" or message.chat.id != call.from_user.id:
        await call.answer("Книги доступны в личном чате с ботом.", show_alert=True)
        return
    action, _, value = call.data.partition(":")
    number = int(value) if value else None
    if number is not None and number > 2147483647:
        await call.answer("Книга недоступна.", show_alert=True)
        return
    try:
        await call.answer()
    except TelegramAPIError:
        pass  # An expired button acknowledgement need not interrupt retrieval.
    if action == "books":
        await _show_books(message, call.from_user.id, number)
        return
    try:
        book = await _checkout_request(f"library/{number}", {"external_user_id": str(call.from_user.id)})
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            await message.answer("Книга недоступна. Откройте свои книги через /books.")
            return
        await message.answer("Не удалось получить PDF. Попробуйте /books позже.")
        return
    except (httpx.HTTPError, RuntimeError, ValueError):
        await message.answer("Не удалось получить PDF. Попробуйте /books позже.")
        return
    digest = book.get("pdf_sha256")
    if (not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or not await _send_pdf(message, book["pdf_url"], book["episode_number"], expected_sha256=digest)):
        await message.answer("Не удалось доставить PDF. Книгу можно снова выбрать через /books.")


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await _answer_step(
        message, 'welcome',
        "👋 Привет! Я создаю персональные сказки для детей.\n\n"
        "✨ Каждая сказка — уникальная история, где главный герой — твой ребёнок!\n"
        "📚 Вдохновлено лучшими авторами: Астрид Линдгрен, Роальд Даль, Туве Янссон.\n\n"
        "Нажми кнопку, чтобы начать:",
        reply_markup=kb_start(),
    )


@dp.callback_query(F.data == "start_story")
async def cb_start_story(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_reply_markup(reply_markup=None)
    await _answer_step(call.message, 'ask_name', "📝 Как зовут ребёнка?")
    await state.set_state(Form.name)
    await call.answer()


@dp.message(F.text.lower().contains("сказка"))
async def text_skazka(message: Message, state: FSMContext):
    await state.clear()
    await _answer_step(message, 'ask_name', "📝 Как зовут ребёнка?")
    await state.set_state(Form.name)


# ---------------------------------------------------------------------------
# Шаг 1: Имя
# ---------------------------------------------------------------------------

@dp.message(Form.name)
async def form_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name or len(name) > 50:
        await message.answer("Пожалуйста, напиши имя ребёнка (до 50 символов).")
        return
    await state.update_data(child_name=name)
    await _answer_step(
        message, 'ask_age',
        f"Замечательно, {name}! 🌟\n\nСколько лет ребёнку?",
        reply_markup=kb_age(),
    )
    await state.set_state(Form.age)


# ---------------------------------------------------------------------------
# Шаг 2: Возраст
# ---------------------------------------------------------------------------

@dp.callback_query(Form.age, F.data.startswith("age:"))
async def cb_age(call: CallbackQuery, state: FSMContext):
    age = int(call.data.split(":")[1])
    await state.update_data(age=age)
    await call.message.edit_reply_markup(reply_markup=None)
    await _answer_step(
        call.message, 'ask_gender',
        f"Отлично, {age_word(age)} — запомнил! 👶\n\nМальчик или девочка?",
        reply_markup=kb_gender(),
    )
    await state.set_state(Form.gender)
    await call.answer()


# ---------------------------------------------------------------------------
# Шаг 3: Пол
# ---------------------------------------------------------------------------

@dp.callback_query(Form.gender, F.data.startswith("gender:"))
async def cb_gender(call: CallbackQuery, state: FSMContext):
    gender = call.data.split(":")[1]
    gender_labels = {"male": "Мальчик 👦", "female": "Девочка 👧"}
    await state.update_data(gender=gender)
    await call.message.edit_reply_markup(reply_markup=None)
    await _answer_step(
        call.message, 'ask_purpose',
        f"{gender_labels.get(gender, gender)} — понял!\n\n"
        "✨ Какую роль сыграет эта сказка для вашего ребёнка?\n\n"
        "Выбери то, что сейчас важнее всего:",
        reply_markup=kb_purpose(),
    )
    await state.set_state(Form.purpose)
    await call.answer()


# ---------------------------------------------------------------------------
# Шаг 4: Цель сказки (purpose) — NEW
# ---------------------------------------------------------------------------

@dp.callback_query(Form.purpose, F.data.startswith("purpose:"))
async def cb_purpose(call: CallbackQuery, state: FSMContext):
    purpose = call.data.split(":")[1]
    purpose_labels = {
        'brave':      'Стать смелее 🦁',
        'fear':       'Справиться со страхом 😨',
        'creativity': 'Открыть творца в себе 🎨',
        'friendship': 'Научиться дружить 🤝',
        'confidence': 'Поверить в себя ⭐',
        'bedtime':    'Сказка на ночь 🌙',
    }
    await state.update_data(purpose=purpose)
    await call.message.edit_reply_markup(reply_markup=None)
    await _answer_step(
        call.message, 'ask_style',
        f"{purpose_labels.get(purpose, purpose)} — учту!\n\nКакой стиль сказки выбираем? 📖",
        reply_markup=kb_style(),
    )
    await state.set_state(Form.style)
    await call.answer()


# ---------------------------------------------------------------------------
# Шаг 5: Стиль сюжета
# ---------------------------------------------------------------------------

@dp.callback_query(Form.style, F.data.startswith("style:"))
async def cb_style(call: CallbackQuery, state: FSMContext):
    style = call.data.split(":")[1]
    await state.update_data(style=style)
    await call.message.edit_reply_markup(reply_markup=None)
    await _answer_step(
        call.message, 'ask_img_style',
        "🖼 Выбери стиль иллюстраций:\n\n"
        "• 🎨 Акварель — нежная ручная акварель\n"
        "• 🌸 Студия Гибли — аниме, «Мой сосед Тоторо»\n"
        "• 🎭 Советская анимация — тёплая классика советских мультфильмов\n"
        "• 🎬 Pixar — объёмный 3D-мультфильм\n"
        "• 🖍 Мультик — яркий плоский мультяшный стиль\n"
        "• 📖 Книжная — классическая книжная иллюстрация",
        reply_markup=kb_img_style(),
    )
    await state.set_state(Form.img_style)
    await call.answer()


# ---------------------------------------------------------------------------
# Шаг 6: Стиль иллюстраций
# ---------------------------------------------------------------------------

@dp.callback_query(Form.img_style, F.data.startswith("img_style:"))
async def cb_img_style(call: CallbackQuery, state: FSMContext):
    img_style = call.data.split(":")[1]
    style_names = {
        'watercolor': 'Акварель 🎨',
        'ghibli':     'Студия Гибли 🌸',
        'soviet':     'Советская анимация 🎭',
        'pixar':      'Pixar 🎬',
        'cartoon':    'Мультик 🖍',
        'storybook':  'Книжная 📖',
    }
    await state.update_data(image_style=img_style)
    await call.message.edit_reply_markup(reply_markup=None)

    data = await state.get_data()
    name = data.get("child_name", "Герой")

    await _answer_step(
        call.message, 'ask_animal',
        f"{style_names.get(img_style, img_style)} — отличный выбор! 🌟\n\n"
        f"🐾 Какое любимое животное у {_genitive(name)}?\n\n"
        "Напиши любое — оно станет волшебным другом в сказке!\n"
        "(например: кот, дракон, единорог, лиса, черепаха...)",
    )
    await state.set_state(Form.animal)
    await call.answer()


# ---------------------------------------------------------------------------
# Шаг 7: Любимое животное
# ---------------------------------------------------------------------------

@dp.message(Form.animal)
async def form_animal(message: Message, state: FSMContext):
    animal = (message.text or "").strip().lower()
    if not animal or len(animal) > 50:
        await message.answer("Напиши название любимого животного 🐾")
        return
    await state.update_data(favorite_animal=animal)
    await _answer_step(
        message, 'ask_color',
        f"Отличный выбор — {animal}! 🌟\n\nКакой любимый цвет?",
        reply_markup=kb_color(),
    )
    await state.set_state(Form.color)


# ---------------------------------------------------------------------------
# Шаг 8: Любимый цвет
# ---------------------------------------------------------------------------

@dp.callback_query(Form.color, F.data.startswith("color:"))
async def cb_color(call: CallbackQuery, state: FSMContext):
    color = call.data.split(":", 1)[1]
    await state.update_data(favorite_color=color)
    await call.message.edit_reply_markup(reply_markup=None)

    data = await state.get_data()
    name = data.get("child_name", "Герой")

    await _answer_step(
        call.message, 'ask_hobby',
        f"{color.capitalize()} — красивый выбор! 🎨\n\n"
        f"Чем {name} любит заниматься больше всего?",
        reply_markup=kb_hobby(),
    )
    await state.set_state(Form.hobby)
    await call.answer()


# ---------------------------------------------------------------------------
# Шаг 9: Хобби
# ---------------------------------------------------------------------------

@dp.callback_query(Form.hobby, F.data.startswith("hobby:"))
async def cb_hobby(call: CallbackQuery, state: FSMContext):
    hobby = call.data.split(":", 1)[1]
    await state.update_data(hobby=hobby)
    await call.message.edit_reply_markup(reply_markup=None)
    await _answer_step(
        call.message, 'ask_place',
        "Супер! Это станет особой способностью героя 💪\n\n"
        "Где любимое место для приключений?",
        reply_markup=kb_place(),
    )
    await state.set_state(Form.place)
    await call.answer()


# ---------------------------------------------------------------------------
# Шаг 10: Любимое место
# ---------------------------------------------------------------------------

@dp.callback_query(Form.place, F.data.startswith("place:"))
async def cb_place(call: CallbackQuery, state: FSMContext):
    place = call.data.split(":", 1)[1]
    await state.update_data(favorite_place=place)
    await call.message.edit_reply_markup(reply_markup=None)

    data = await state.get_data()
    name = data.get("child_name", "Герой")

    await _answer_step(
        call.message, 'ask_photo',
        f"Отлично, там и развернётся главное событие! 🗺\n\n"
        f"📷 Хочешь добавить фото {_genitive(name)}?\n"
        "Тогда иллюстрации будут генерироваться с его/её внешностью как референсом.",
        reply_markup=kb_photo_choice(),
    )
    await state.set_state(Form.photo_choice)
    await call.answer()


# ---------------------------------------------------------------------------
# Шаг 11: Выбор — добавить фото или нет
# ---------------------------------------------------------------------------

@dp.callback_query(Form.photo_choice, F.data.startswith("photo:"))
async def cb_photo_choice(call: CallbackQuery, state: FSMContext):
    choice = call.data.split(":")[1]
    await call.message.edit_reply_markup(reply_markup=None)
    if choice == "yes":
        await call.message.answer(
            "📸 Пришли фото ребёнка (одно фото, лицо хорошо видно).\n"
            "Отправляя фото, вы разрешаете использовать его для иллюстраций этой книги. "
            "Для восстановления заказа сохраняется ссылка на файл в Telegram. "
            "Чтобы продолжить без фото, начните анкету заново командой /start."
        )
        await state.set_state(Form.photo_upload)
    else:
        await state.update_data(photo_base64=None, photo_file_id=None,
                                photo_enabled=False, photo_consent=False)
        await call.message.answer("Анкета готова. Перейдём к оплате сказки.")
        await _request_payment(call.message, state)
    await call.answer()


# ---------------------------------------------------------------------------
# Шаг 12: Приём фото
# ---------------------------------------------------------------------------

@dp.message(Form.photo_upload, F.photo)
async def form_photo(message: Message, state: FSMContext):
    photo = message.photo[-1]
    # Persist only the Telegram reference with the invoice, never image bytes.
    # Download after the paid receipt is durable, so a bot restart is recoverable.
    await state.update_data(photo_base64=None, photo_file_id=photo.file_id,
                            photo_enabled=True, photo_consent=True)
    await message.answer("Фото получено. Перейдём к оплате сказки.")
    await _request_payment(message, state)


@dp.message(Form.photo_upload)
async def form_photo_wrong(message: Message, state: FSMContext):
    await message.answer("Пришли фото (не файл, а именно фото), или нажми /start чтобы начать заново.")


# ---------------------------------------------------------------------------
# Вспомогательная: скачать и отправить картинку
# ---------------------------------------------------------------------------

_PRIVATE_MEDIA_NAME = re.compile(r"^[a-f0-9]{32}\.(?:png|jpg|jpeg|webp|pdf)$", re.I)


def _private_media_filename(locator: str, kind: str) -> str:
    """A story response is only a locator. Never fetch an arbitrary external URL."""
    if kind not in ("images", "stories"):
        raise ValueError("Unknown media kind")
    parsed = urlsplit(locator)
    expected = f"/files/{kind}/"
    if parsed.path.count("/") != 3 or not parsed.path.startswith(expected):
        raise ValueError("Unexpected media locator")
    filename = parsed.path[len(expected):]
    if not _PRIVATE_MEDIA_NAME.fullmatch(filename):
        raise ValueError("Invalid private media filename")
    if kind == "stories" and not filename.lower().endswith(".pdf"):
        raise ValueError("Expected PDF")
    if kind == "images" and filename.lower().endswith(".pdf"):
        raise ValueError("Expected image")
    return filename


async def _download_private_media(locator: str, kind: str) -> tuple[str, bytes]:
    if not BACKEND_INTERNAL_TOKEN or len(BACKEND_INTERNAL_TOKEN) < 32:
        raise RuntimeError("Private media access is not configured")
    filename = _private_media_filename(locator, kind)
    endpoint = f"{BACKEND_URL.rstrip('/')}/api/internal/files/{kind}/{filename}"
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(endpoint, headers={
            "X-Legend-Internal-Key": BACKEND_INTERNAL_TOKEN,
        })
        response.raise_for_status()
    content = response.content
    if not content or len(content) > 30 * 1024 * 1024:
        raise ValueError("Unexpected media size")
    if kind == "stories" and not content.startswith(b"%PDF-"):
        raise ValueError("Response is not a PDF")
    if kind == "images" and not (content.startswith(b"\x89PNG\r\n\x1a\n") or
                                  content.startswith(b"\xff\xd8\xff") or
                                  content.startswith(b"RIFF") and content[8:12] == b"WEBP"):
        raise ValueError("Response is not a supported image")
    return filename, content


async def _send_image(message: Message, img_url: str, caption: str = '') -> bool:
    try:
        filename, content = await _download_private_media(img_url, "images")
        await message.answer_photo(
            photo=BufferedInputFile(content, filename=filename),
            caption=caption,
        )
        return True
    except Exception:
        return False


async def _send_pdf(message: Message, pdf_url: str, episode: int, *, expected_sha256: str | None = None) -> bool:
    try:
        _, content = await _download_private_media(pdf_url, "stories")
        if expected_sha256 is not None and hashlib.sha256(content).hexdigest() != expected_sha256:
            return False
        await message.answer_document(
            document=BufferedInputFile(content, filename=f"legendkids-episode-{episode}.pdf"),
            caption="Ваша персональная сказка в PDF",
        )
        return True
    except Exception:
        return False


@dp.message(Form.awaiting_payment)
async def awaiting_payment_fallback(message: Message):
    await message.answer(
        "Ожидаю оплату. Нажмите кнопку «Оплатить» выше или напишите /start, чтобы начать заново."
    )


# ---------------------------------------------------------------------------
# Генерация сказки
# ---------------------------------------------------------------------------

async def _generate(trigger_message: Message, state: FSMContext, data: dict,
                    *, photo_file_id: str | None = None):
    # Only the backend's durable paid snapshot is accepted, never current FSM.
    data = dict(data)
    if not data.get("telegram_payment_charge_id"):
        await trigger_message.answer("Для этого заказа нет подтверждённой оплаты.")
        return
    if not BACKEND_INTERNAL_TOKEN or len(BACKEND_INTERNAL_TOKEN) < 32:
        await trigger_message.answer("Сервис временно не готов к выдаче книги. Платёж сохранён; не оплачивайте повторно.")
        return

    child_name      = data.get("child_name", "Герой")
    age             = data.get("age", 7)
    gender          = data.get("gender", "neutral")
    purpose         = data.get("purpose", "bedtime")
    style           = data.get("style", "auto")
    image_style     = data.get("image_style", "watercolor")
    animal          = data.get("favorite_animal", "кот")
    color           = data.get("favorite_color", "синий")
    hobby           = data.get("hobby", "рисование")
    place           = data.get("favorite_place", "лес")
    photo_b64       = None
    photo_enabled   = data.get("photo_enabled", False)
    photo_consent   = data.get("photo_consent", False)
    charge_id       = data.get("telegram_payment_charge_id")
    resume_pdf_only = data.get("resume_pdf_only") is True
    if photo_enabled and not resume_pdf_only:
        if not photo_consent or not photo_file_id:
            await trigger_message.answer(
                "Платёж сохранён, но согласованное фото недоступно. "
                "Заказ требует восстановления; повторно платить не нужно."
            )
            return
        try:
            file = await bot.get_file(photo_file_id)
            downloaded = await bot.download_file(file.file_path)
            photo_bytes = downloaded.read(10 * 1024 * 1024 + 1)
            if not photo_bytes or len(photo_bytes) > 10 * 1024 * 1024:
                raise ValueError("Photo is empty or too large")
            photo_b64 = base64.b64encode(photo_bytes).decode()
        except Exception:
            await trigger_message.answer(
                "Платёж сохранён, но фото пока не удалось получить из Telegram. "
                "Повторно платить не нужно; заказ требует восстановления."
            )
            return

    img_style_labels = {
        'watercolor': 'акварель', 'ghibli': 'Студия Гибли', 'soviet': 'Советская анимация',
        'pixar': 'Pixar', 'cartoon': 'мультик', 'storybook': 'книжная',
    }
    purpose_labels = {
        'brave': 'стать смелее', 'fear': 'справиться со страхом',
        'creativity': 'открыть творца в себе', 'friendship': 'научиться дружить',
        'confidence': 'поверить в себя', 'bedtime': 'уютная сказка на ночь',
    }

    try:
        await _answer_step(
            trigger_message, 'generating',
            f"✨ Создаю персональную сказку для {_genitive(child_name)}...\n\n"
            f"🎯 Цель: {purpose_labels.get(purpose, purpose)}\n"
            f"🐾 Любимое животное: {animal}\n"
            f"🎨 Любимый цвет: {color}\n"
            f"💪 Любимое занятие: {hobby}\n"
            f"🗺 Место приключений: {place}\n"
            f"🖼 Стиль иллюстраций: {img_style_labels.get(image_style, image_style)}\n\n"
            "Книга готовится. Чат можно закрыть; повторная оплата не нужна.",
        )
    except (TelegramAPIError, OSError):
        # Progress text and optional local step art are not payment or
        # generation prerequisites. The paid snapshot remains authoritative.
        pass

    payload = {
        "external_user_id": data["external_user_id"],
        "channel": "telegram",
        "child_name": child_name,
        "age": age,
        "gender": gender,
        "purpose": purpose,
        "style": style,
        "image_style": image_style,
        "favorite_animal": animal,
        "favorite_color": color,
        "hobby": hobby,
        "favorite_place": place,
        "photo_enabled": photo_enabled,
        "photo_consent": photo_consent,
        "child_id": data["child_id"],
        "order_id": data["order_id"],
        "parent_note": data.get("parent_note"),
    }
    if photo_b64:
        payload["photo_base64"] = photo_b64
    if resume_pdf_only:
        payload["resume_pdf_only"] = True
    if charge_id:
        payload["telegram_payment_charge_id"] = charge_id

    try:
        async with httpx.AsyncClient(timeout=480) as client:
            resp = await client.post(f"{BACKEND_URL}/api/story/generate", json=payload, headers={"X-Legend-Internal-Key": BACKEND_INTERNAL_TOKEN})
            resp.raise_for_status()
            result = resp.json()
    except httpx.ReadTimeout:
        await trigger_message.answer(
            f"Платёж заказа №{data['order_id']} сохранён, но результат пока не получен. "
            "Не оформляйте новый заказ и не платите повторно."
        )
        return
    except httpx.HTTPStatusError as e:
        await trigger_message.answer(
            f"Не удалось получить книгу заказа №{data['order_id']} "
            f"(ошибка {e.response.status_code}). Платёж сохранён; повторная оплата не нужна."
        )
        return
    except Exception:
        await trigger_message.answer(
            f"Книга заказа №{data['order_id']} пока не получена. "
            "Платёж сохранён; повторная оплата не нужна."
        )
        return

    await _deliver_generated_book(trigger_message, state, data, result)


async def _deliver_generated_book(trigger_message: Message, state: FSMContext,
                                  data: dict, result: dict):
    child_name = data.get("child_name", "Герой")
    illustrations = result.get("images_urls")
    # Do not deliver a failed/incomplete paid order, including legacy records.
    if (result.get("status") != "ready" or not result.get("pdf_url")
            or not result.get("story_text")
            or not isinstance(illustrations, list) or len(illustrations) != 5
            or not all(isinstance(url, str) and url.strip() for url in illustrations)):
        await trigger_message.answer(
            "Оплата получена, но полная иллюстрированная книга пока не готова. "
            "Повторно платить не нужно. Заказ требует восстановления."
        )
        return

    story_text  = result.get("story_text", "")
    pdf_url     = result.get("pdf_url")
    cover_url, *chapter_urls = illustrations
    episode     = result.get("episode_number", 1)
    title       = result.get("title", "")
    next_hook   = result.get("next_hook")

    # The paid PDF is the primary deliverable. Telegram may reject an optional
    # preview message (for example malformed generated Markdown) or photo.
    # Such a failure must not prevent the existing PDF from being delivered.
    preview_complete = True
    try:
        if episode > 1:
            await trigger_message.answer(
                f"📚 *Эпизод {episode}: продолжение приключений {_genitive(child_name)}!*\n\n"
                "История продолжается с того места, где остановилась...",
                parse_mode="Markdown",
            )

        # ── Разбиваем текст на главы ──────────────────────────────────────────
        # ── Обложка: images[0] с названием сказки ────────────────────────────
        if not await _send_image(trigger_message, cover_url, caption=f"📖 {title}"):
            preview_complete = False

        # ── Главы: картинка → текст (images[1-4] для первых 4 глав) ──────────
        # A legacy ready book may have a preface or mixed line endings. Its
        # text is still delivered in full; only a numbered heading uses a scene.
        text = story_text.replace('\r\n', '\n').replace('\r', '\n').strip()
        parts = re.split(
            r"^[ \t]*(Глава[ \t]+(?:\d+|[IVXLCDM]+|первая|вторая|третья|четв[её]ртая|"
            r"пятая|шестая|седьмая|восьмая|девятая|десятая)\b[^\n]*)$",
            text, flags=re.MULTILINE | re.IGNORECASE,
        )
        scenes = iter(chapter_urls)
        for ch_title, ch_text in zip(["", *parts[1::2]], parts[::2]):
            scene = next(scenes, None) if ch_title else None
            if scene:
                if not await _send_image(trigger_message, scene, caption=ch_title.strip()[:1024]):
                    preview_complete = False

            full_chapter = (ch_title.strip() + '\n\n' + ch_text.strip()).strip()
            for i in range(0, len(full_chapter), 4000):
                await trigger_message.answer(full_chapter[i:i + 4000])

        # ── Анонс следующей серии ─────────────────────────────────────────────
        if next_hook:
            await trigger_message.answer(f"💫 _{next_hook}_", parse_mode="Markdown")

    except TelegramAPIError:
        preview_complete = False

    # ── PDF и кнопки: private authenticated delivery ────────────────────
    if not pdf_url or not await _send_pdf(trigger_message, pdf_url, episode):
        # The customer has already paid. Do not clear the paid state or
        # invite another payment. Durable recovery across restarts remains P0.
        await trigger_message.answer(
            "Оплата получена, но PDF пока не удалось доставить. "
            "Повторно платить не нужно: заказ требует восстановления."
        )
        return
    confirmation = "Сказка доставлена документом выше. Его можно открыть повторно в этом чате."
    if not preview_complete:
        confirmation += " Предпросмотр в чате мог быть неполным; полная книга находится в PDF."
    await trigger_message.answer(
        confirmation,
        reply_markup=kb_after_story(None, episode, child_name),
    )
    # A late payment for an old invoice must not erase a newer questionnaire.
    if (await state.get_data()).get("order_id") == data["order_id"]:
        await state.clear()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
