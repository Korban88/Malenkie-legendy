import base64
import os
import asyncio
from pathlib import Path

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
    FSInputFile,
)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8010")

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
    buttons = []
    if pdf_url:
        buttons.append([InlineKeyboardButton(text="📖 Открыть PDF", url=pdf_url)])
    next_label = f"✨ Продолжение ({child_name}, эп. {episode + 1})" if episode > 1 else "✨ Ещё сказку"
    buttons.append([InlineKeyboardButton(text=next_label, callback_data="start_story")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

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
        "• ✨ Disney — яркие волшебные персонажи\n"
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
            "Оно используется только для генерации иллюстраций и нигде не сохраняется."
        )
        await state.set_state(Form.photo_upload)
    else:
        await state.update_data(photo_base64=None, photo_enabled=False)
        await _generate(call.message, state)
    await call.answer()


# ---------------------------------------------------------------------------
# Шаг 12: Приём фото
# ---------------------------------------------------------------------------

@dp.message(Form.photo_upload, F.photo)
async def form_photo(message: Message, state: FSMContext):
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
# Вспомогательная: скачать и отправить картинку
# ---------------------------------------------------------------------------

async def _send_image(message: Message, img_url: str, caption: str = '') -> bool:
    try:
        async with httpx.AsyncClient(timeout=30) as img_client:
            img_resp = await img_client.get(img_url)
            img_resp.raise_for_status()
        filename = img_url.split("/")[-1]
        await message.answer_photo(
            photo=BufferedInputFile(img_resp.content, filename=filename),
            caption=caption,
        )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Генерация сказки
# ---------------------------------------------------------------------------

async def _generate(trigger_message: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    child_name   = data.get("child_name", "Герой")
    age          = data.get("age", 7)
    gender       = data.get("gender", "neutral")
    purpose      = data.get("purpose", "bedtime")
    style        = data.get("style", "auto")
    image_style  = data.get("image_style", "watercolor")
    animal       = data.get("favorite_animal", "кот")
    color        = data.get("favorite_color", "синий")
    hobby        = data.get("hobby", "рисование")
    place        = data.get("favorite_place", "лес")
    photo_b64    = data.get("photo_base64")
    photo_enabled   = data.get("photo_enabled", False)
    photo_consent   = data.get("photo_consent", False)

    img_style_labels = {
        'watercolor': 'акварель', 'ghibli': 'Студия Гибли', 'soviet': 'Советская анимация',
        'pixar': 'Pixar', 'cartoon': 'мультик', 'storybook': 'книжная',
    }
    purpose_labels = {
        'brave': 'стать смелее', 'fear': 'справиться со страхом',
        'creativity': 'открыть творца в себе', 'friendship': 'научиться дружить',
        'confidence': 'поверить в себя', 'bedtime': 'уютная сказка на ночь',
    }

    await _answer_step(
        trigger_message, 'generating',
        f"✨ Создаю персональную сказку для {_genitive(child_name)}...\n\n"
        f"🎯 Цель: {purpose_labels.get(purpose, purpose)}\n"
        f"🐾 Любимое животное: {animal}\n"
        f"🎨 Любимый цвет: {color}\n"
        f"💪 Любимое занятие: {hobby}\n"
        f"🗺 Место приключений: {place}\n"
        f"🖼 Стиль иллюстраций: {img_style_labels.get(image_style, image_style)}\n\n"
        "⏳ Это займёт 3–5 минут — не закрывай чат, волшебство уже в пути! ✨",
    )

    payload = {
        "external_user_id": str(trigger_message.chat.id),
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
    }
    if photo_b64:
        payload["photo_base64"] = photo_b64

    try:
        async with httpx.AsyncClient(timeout=480) as client:
            resp = await client.post(f"{BACKEND_URL}/api/story/generate", json=payload)
            resp.raise_for_status()
            result = resp.json()
    except httpx.ReadTimeout:
        await trigger_message.answer("⏳ Сервер не успел ответить. Попробуй ещё раз — напиши СКАЗКА.")
        return
    except httpx.HTTPStatusError as e:
        await trigger_message.answer(f"❌ Ошибка сервера ({e.response.status_code}). Попробуй позже.")
        return
    except Exception:
        await trigger_message.answer("❌ Что-то пошло не так. Попробуй ещё раз — напиши СКАЗКА.")
        return

    story_text  = result.get("story_text", "")
    pdf_url     = result.get("pdf_url")
    raw_urls    = result.get("images_urls") or []
    # Pad to 6 slots so positional indexing is always safe (None = image failed)
    images_urls: list[str | None] = list(raw_urls) + [None] * max(0, 6 - len(raw_urls))
    episode     = result.get("episode_number", 1)
    title       = result.get("title", "")
    next_hook   = result.get("next_hook")

    if episode > 1:
        await trigger_message.answer(
            f"📚 *Эпизод {episode}: продолжение приключений {_genitive(child_name)}!*\n\n"
            "История продолжается с того места, где остановилась...",
            parse_mode="Markdown",
        )

    # ── Разбиваем текст на главы ──────────────────────────────────────────
    paragraphs = [p.strip() for p in story_text.split('\n\n') if p.strip()]
    chapters: list[tuple[str, str]] = []
    current_title = ''
    current_paras: list[str] = []

    for para in paragraphs:
        if para.startswith('Глава'):
            if current_title or current_paras:
                chapters.append((current_title, '\n\n'.join(current_paras)))
            current_title = para
            current_paras = []
        else:
            current_paras.append(para)
    if current_title or current_paras:
        chapters.append((current_title, '\n\n'.join(current_paras)))

    # ── Обложка: images[0] с названием сказки ────────────────────────────
    if images_urls[0]:
        await _send_image(trigger_message, images_urls[0], caption=f"📖 {title}")

    # ── Главы: картинка → текст (images[1-4] для первых 4 глав) ──────────
    for ch_idx, (ch_title, ch_text) in enumerate(chapters):
        img_idx = ch_idx + 1  # [1],[2],[3],[4] → главы 0,1,2,3
        ch_url = images_urls[img_idx] if 1 <= img_idx <= 4 else None
        if ch_url:
            caption = ch_title if ch_title else f"Глава {ch_idx + 1}"
            await _send_image(trigger_message, ch_url, caption=caption)

        full_chapter = (ch_title + '\n\n' + ch_text).strip() if ch_title else ch_text
        for i in range(0, len(full_chapter), 4000):
            await trigger_message.answer(full_chapter[i:i + 4000])

    # ── Анонс следующей серии ─────────────────────────────────────────────
    if next_hook:
        await trigger_message.answer(f"💫 _{next_hook}_", parse_mode="Markdown")

    # ── Финальная иллюстрация: images[5] ─────────────────────────────────
    if images_urls[5]:
        await _send_image(trigger_message, images_urls[5], caption="🏆 Финал")

    # ── PDF и кнопки ──────────────────────────────────────────────────────
    await trigger_message.answer(
        "📖 Сказка готова!" + (" Скачай PDF для чтения вслух!" if pdf_url else ""),
        reply_markup=kb_after_story(pdf_url, episode, child_name),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
