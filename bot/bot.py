import base64
import os
import asyncio

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile,
)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8010")

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
    style = State()
    animal = State()      # Любимое животное (текст)
    color = State()       # Любимый цвет (кнопки)
    hobby = State()       # Любимое занятие (кнопки)
    place = State()       # Любимое место (кнопки)
    photo_choice = State()  # Добавить фото? (кнопки)
    photo_upload = State()  # Ожидание фото


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------

def kb_start() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✨ Создать сказку", callback_data="start_story"),
    ]])


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
    buttons = []
    if pdf_url:
        buttons.append([
            InlineKeyboardButton(text="📖 Открыть PDF", url=pdf_url),
        ])
    next_label = f"✨ Продолжение ({child_name}, эп. {episode + 1})" if episode > 1 else "✨ Ещё сказку"
    buttons.append([InlineKeyboardButton(text=next_label, callback_data="start_story")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
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
    await call.message.answer("📝 Как зовут ребёнка?")
    await state.set_state(Form.name)
    await call.answer()


@dp.message(F.text.lower().contains("сказка"))
async def text_skazka(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("📝 Как зовут ребёнка?")
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
    await message.answer(
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
    await call.message.answer(
        f"Отлично, {age} лет — запомнил! 👶\n\nМальчик или девочка?",
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
    await call.message.answer(
        f"{gender_labels.get(gender, gender)} — понял!\n\nКакой стиль сказки выбираем? 📖",
        reply_markup=kb_style(),
    )
    await state.set_state(Form.style)
    await call.answer()


# ---------------------------------------------------------------------------
# Шаг 4: Стиль
# ---------------------------------------------------------------------------

@dp.callback_query(Form.style, F.data.startswith("style:"))
async def cb_style(call: CallbackQuery, state: FSMContext):
    style = call.data.split(":")[1]
    await state.update_data(style=style)
    await call.message.edit_reply_markup(reply_markup=None)

    data = await state.get_data()
    name = data.get("child_name", "Герой")

    await call.message.answer(
        f"🐾 Какое любимое животное у {name}?\n\n"
        "Напиши любое — оно станет волшебным другом в сказке!\n"
        "(например: кот, дракон, единорог, лиса, черепаха...)"
    )
    await state.set_state(Form.animal)
    await call.answer()


# ---------------------------------------------------------------------------
# Шаг 5: Любимое животное (свободный текст)
# ---------------------------------------------------------------------------

@dp.message(Form.animal)
async def form_animal(message: Message, state: FSMContext):
    animal = (message.text or "").strip().lower()
    if not animal or len(animal) > 50:
        await message.answer("Напиши название любимого животного 🐾")
        return
    await state.update_data(favorite_animal=animal)
    await message.answer(
        f"Отличный выбор — {animal}! 🌟\n\nКакой любимый цвет?",
        reply_markup=kb_color(),
    )
    await state.set_state(Form.color)


# ---------------------------------------------------------------------------
# Шаг 6: Любимый цвет
# ---------------------------------------------------------------------------

@dp.callback_query(Form.color, F.data.startswith("color:"))
async def cb_color(call: CallbackQuery, state: FSMContext):
    color = call.data.split(":", 1)[1]
    await state.update_data(favorite_color=color)
    await call.message.edit_reply_markup(reply_markup=None)

    data = await state.get_data()
    name = data.get("child_name", "Герой")

    await call.message.answer(
        f"{color.capitalize()} — красивый выбор! 🎨\n\n"
        f"Чем {name} любит заниматься больше всего?",
        reply_markup=kb_hobby(),
    )
    await state.set_state(Form.hobby)
    await call.answer()


# ---------------------------------------------------------------------------
# Шаг 7: Хобби
# ---------------------------------------------------------------------------

@dp.callback_query(Form.hobby, F.data.startswith("hobby:"))
async def cb_hobby(call: CallbackQuery, state: FSMContext):
    hobby = call.data.split(":", 1)[1]
    await state.update_data(hobby=hobby)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        f"Супер! Это станет особой способностью героя 💪\n\n"
        "Где любимое место для приключений?",
        reply_markup=kb_place(),
    )
    await state.set_state(Form.place)
    await call.answer()


# ---------------------------------------------------------------------------
# Шаг 8: Любимое место
# ---------------------------------------------------------------------------

@dp.callback_query(Form.place, F.data.startswith("place:"))
async def cb_place(call: CallbackQuery, state: FSMContext):
    place = call.data.split(":", 1)[1]
    await state.update_data(favorite_place=place)
    await call.message.edit_reply_markup(reply_markup=None)

    data = await state.get_data()
    name = data.get("child_name", "Герой")

    await call.message.answer(
        f"Отлично, там и развернётся главное событие! 🗺\n\n"
        f"📷 Хочешь добавить фото {name}?\n"
        "Тогда иллюстрации будут генерироваться с его/её внешностью как референсом.",
        reply_markup=kb_photo_choice(),
    )
    await state.set_state(Form.photo_choice)
    await call.answer()


# ---------------------------------------------------------------------------
# Шаг 9: Выбор — добавить фото или нет
# ---------------------------------------------------------------------------

@dp.callback_query(Form.photo_choice, F.data.startswith("photo:"))
async def cb_photo_choice(call: CallbackQuery, state: FSMContext):
    choice = call.data.split(":")[1]
    await call.message.edit_reply_markup(reply_markup=None)

    if choice == "yes":
        await call.message.answer(
            "📸 Пришли фото ребёнка (одно фото, лицо хорошо видно).\n"
            "Оно используется только для генерации иллюстраций и нигде не сохраняется."
        )
        await state.set_state(Form.photo_upload)
    else:
        await state.update_data(photo_base64=None, photo_enabled=False)
        await _generate(call.message, state)

    await call.answer()


# ---------------------------------------------------------------------------
# Шаг 10: Приём фото
# ---------------------------------------------------------------------------

@dp.message(Form.photo_upload, F.photo)
async def form_photo(message: Message, state: FSMContext):
    # Get the largest available photo
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    downloaded = await bot.download_file(file.file_path)
    photo_bytes = downloaded.read()
    photo_b64 = base64.b64encode(photo_bytes).decode()

    await state.update_data(photo_base64=photo_b64, photo_enabled=True, photo_consent=True)
    await message.answer("✅ Фото получено! Создаю сказку...")
    await _generate(message, state)


@dp.message(Form.photo_upload)
async def form_photo_wrong(message: Message, state: FSMContext):
    await message.answer("Пришли фото (не файл, а именно фото), или нажми /start чтобы начать заново.")


# ---------------------------------------------------------------------------
# Генерация сказки
# ---------------------------------------------------------------------------

async def _generate(trigger_message: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    child_name = data.get("child_name", "Герой")
    age = data.get("age", 7)
    gender = data.get("gender", "neutral")
    style = data.get("style", "auto")
    animal = data.get("favorite_animal", "кот")
    color = data.get("favorite_color", "синий")
    hobby = data.get("hobby", "рисование")
    place = data.get("favorite_place", "лес")
    photo_b64 = data.get("photo_base64")
    photo_enabled = data.get("photo_enabled", False)
    photo_consent = data.get("photo_consent", False)

    await trigger_message.answer(
        f"✨ Создаю персональную сказку для {child_name}...\n\n"
        f"🐾 Любимое животное: {animal}\n"
        f"🎨 Любимый цвет: {color}\n"
        f"💪 Любимое занятие: {hobby}\n"
        f"🗺 Место приключений: {place}\n\n"
        "Это займёт 1–3 минуты. Не закрывай чат! 📖"
    )

    payload = {
        "external_user_id": str(trigger_message.chat.id),
        "channel": "telegram",
        "child_name": child_name,
        "age": age,
        "gender": gender,
        "style": style,
        "favorite_animal": animal,
        "favorite_color": color,
        "hobby": hobby,
        "favorite_place": place,
        "photo_enabled": photo_enabled,
        "photo_consent": photo_consent,
    }
    if photo_b64:
        payload["photo_base64"] = photo_b64

    try:
        async with httpx.AsyncClient(timeout=240) as client:
            resp = await client.post(f"{BACKEND_URL}/api/story/generate", json=payload)
            resp.raise_for_status()
            result = resp.json()
    except httpx.ReadTimeout:
        await trigger_message.answer(
            "⏳ Сервер не успел ответить. Попробуй ещё раз — напиши СКАЗКА."
        )
        return
    except httpx.HTTPStatusError as e:
        await trigger_message.answer(
            f"❌ Ошибка сервера ({e.response.status_code}). Попробуй позже."
        )
        return
    except Exception:
        await trigger_message.answer(
            "❌ Что-то пошло не так. Попробуй ещё раз — напиши СКАЗКА."
        )
        return

    story_text = result.get("story_text")
    pdf_url = result.get("pdf_url")
    images_urls = result.get("images_urls") or []
    episode = result.get("episode_number", 1)
    title = result.get("title", "")

    # Episode header for serial stories
    if episode > 1:
        await trigger_message.answer(
            f"📚 *Эпизод {episode}: продолжение приключений {child_name}!*\n\n"
            f"История продолжается с того места, где остановилась в прошлый раз...",
            parse_mode="Markdown",
        )

    # Story text (split if too long for Telegram's 4096 char limit)
    if story_text:
        chunk_size = 4000
        chunks = [story_text[i:i + chunk_size] for i in range(0, len(story_text), chunk_size)]
        for chunk in chunks:
            await trigger_message.answer(chunk)

    # Illustrations
    if images_urls:
        await trigger_message.answer(f"🎨 Иллюстрации к сказке «{title}»:")

    for idx, img_url in enumerate(images_urls):
        try:
            async with httpx.AsyncClient(timeout=30) as img_client:
                img_resp = await img_client.get(img_url)
                img_resp.raise_for_status()
            filename = img_url.split("/")[-1]
            captions = [
                "🌍 Мир сказки",
                "👀 Первое открытие",
                "⚡ Испытание",
                f"🐾 {animal.capitalize()} — верный друг",
                "🏆 Победа!",
            ]
            caption = captions[idx] if idx < len(captions) else f"Иллюстрация {idx + 1}"
            await trigger_message.answer_photo(
                photo=BufferedInputFile(img_resp.content, filename=filename),
                caption=caption,
            )
        except Exception:
            pass

    # Next hook (cliffhanger)
    next_hook = result.get("next_hook")
    if next_hook:
        await trigger_message.answer(f"💫 _{next_hook}_", parse_mode="Markdown")

    # Final buttons
    await trigger_message.answer(
        "📖 Сказка готова!" + (" Скачай PDF для чтения вслух!" if pdf_url else ""),
        reply_markup=kb_after_story(pdf_url, episode, child_name),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
