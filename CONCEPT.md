# Маленькие легенды — концепция и история проекта

> Файл для Claude: читай этот файл в начале каждой сессии, чтобы восстановить контекст.

---

## Концепция

**Маленькие легенды** — Telegram-бот, который генерирует персональные сказки для детей.
Каждая сказка — уникальная история, где главный герой — ребёнок пользователя.

**Целевая аудитория:** родители детей 3–10 лет.

**Ценность:** сказка на 10–15 минут чтения на ночь, с иллюстрациями, именем ребёнка в главной роли, скачиваемым PDF.

---

## Архитектура (актуальная после сессии 5)

```
Telegram Bot (aiogram 3)
        ↓ HTTP POST
FastAPI Backend (Uvicorn)
        ├── text_service.py   — генерация текста (OpenRouter / template fallback)
        ├── image_service.py  — генерация картинок (Stability AI / Pollinations fallback)
        ├── pdf_service.py    — сборка PDF (fpdf2 + DejaVu шрифты)
        └── story_service.py  — оркестрация всего
```

**Сервер:** `31.129.108.93`
- Backend: `http://31.129.108.93:8010` (systemd: `malenkie-legendy-backend`)
- Bot: systemd-сервис `malenkie-bot`
- Проект: `/opt/malenkie-legendy/`
- Backend venv: `/opt/malenkie-legendy/backend/.venv/`
- Bot venv: `/opt/malenkie-legendy/bot/.venv/`
- Bot env: `/opt/malenkie-legendy/bot/.env`

**GitHub:** https://github.com/Korban88/Malenkie-legendy

---

## Технологии

| Компонент | Стек |
|-----------|------|
| Telegram бот | Python, aiogram 3.15, FSM (MemoryStorage) |
| Backend | FastAPI, Uvicorn, SQLAlchemy, PostgreSQL |
| Генерация текста | OpenRouter API (GPT-4o-mini) + template fallback |
| Генерация картинок | Stability AI + Pollinations.ai fallback |
| PDF | fpdf2 + DejaVuSans (поддержка кириллицы) |

---

## Флоу бота (FSM)

```
/start → кнопка [Создать сказку]
  → "Как зовут ребёнка?" (текст)
  → "Сколько лет?" [3..10] (кнопки)
  → "Мальчик / Девочка / Нейтрально" (кнопки)
  → "Волшебная / Приключение / О природе / Космос" (кнопки)
  → "Создаю сказку для {имя}..."
  → POST /api/story/generate
  → текст сказки
  → 5 иллюстраций (фото в чат)
  → кнопки [Открыть PDF] [Ещё сказку]
```

---

## Endpoint /api/story/generate

**Request:**
```json
{
  "external_user_id": "string",
  "channel": "telegram",
  "child_name": "string",
  "age": 6,
  "gender": "male|female|neutral",
  "style": "magic|adventure|nature|space",
  "photo_enabled": false
}
```

**Response:**
```json
{
  "story_id": 1,
  "child_id": 1,
  "episode_number": 1,
  "status": "ready",
  "title": "string",
  "story_text": "string",
  "recap": [],
  "memory": {},
  "next_hook": "string",
  "images_urls": ["http://..."],
  "pdf_url": "http://..."
}
```

---

## Стили сказок

| Ключ бота | Описание | По возрасту |
|-----------|----------|-------------|
| magic | волшебный и сказочный | 5–8 лет (auto) |
| adventure | приключенческий | 8–10 лет (auto) |
| nature | про природу и живой мир | - |
| space | космический и фантастический | - |
| tender | нежный и тёплый | 3–5 лет (auto) |
| epic | эпический | 11–12 лет (auto) |

---

## История изменений

### Сессия 1 (2026-03-08) — базовая инфраструктура

**Проблема:** бот отвечал "None", падал с httpx.ReadTimeout.

**Исправлено в `bot/bot.py`:**
- timeout=180 секунд
- try/except для ReadTimeout и HTTPStatusError
- безопасное `data.get('story_text')`, `data.get('pdf_url')`
- сообщение "Сказка создаётся..." перед запросом

**Инфраструктура:**
- Создан systemd-сервис `malenkie-bot` (автостарт, Restart=always)
- Файл: `/etc/systemd/system/malenkie-bot.service`
- EnvironmentFile: `/opt/malenkie-legendy/bot/.env`

---

### Сессия 2 (2026-03-08) — FSM + кнопки

**Добавлено в `bot/bot.py`:**
- FSM (aiogram.fsm) с состояниями: name → age → gender → style
- Inline-кнопки на каждом шаге анкеты
- Кнопка [Создать сказку] в /start
- Кнопки [Открыть PDF] [Ещё сказку] после генерации
- Отправка `images_urls` как фото (BufferedInputFile, скачиваем байты — HTTP→Telegram требует HTTPS)

---

### Сессия 3 (2026-03-08) — качество контента

**Исправлено в `backend/app/services/text_service.py`:**
- Расширены словари стилей (magic, space, nature)
- Промпт для GPT: 5000–7000 символов, строгий род, image_prompts на английском
- Template fallback полностью переписан:
  - Все глаголы параметризованы по роду (female/male)
  - История ~5000 символов, 5 глав, правильная структура сказки
  - Возвращает `image_prompts` — 5 сцен на английском для иллюстраций

**Исправлено в `backend/app/services/story_service.py`:**
- Передаёт `scene_prompts` и `count=5` в generate_images

**Исправлено в `backend/app/services/image_service.py`:**
- Принимает `scene_prompts` — промпт для каждой картинки уникален
- Суффикс стиля по умолчанию зависит от стиля сказки
- Ошибка одной картинки не ломает всю генерацию (try/except per image)

**Исправлено в `backend/app/services/pdf_service.py`:**
- Книжная вёрстка: титульная страница + картинка вверху + текст внизу
- Иллюстрации вставляются inline через каждые N абзацев
- Двойная рамка на каждой странице
- Заголовки глав выделены жирным
- Текст выровнен по ширине (align='J')

**Исправлено на сервере (pdf_service.py line 71):**
```python
# Было (вызывало FPDFException):
pdf.multi_cell(0, 6, url)
# Стало:
pdf.set_x(pdf.l_margin)
pdf.multi_cell(pdf.epw, 6, url)
```

---

## Известные проблемы и заметки

### OpenRouter (генерация текста)
- Если `OPENROUTER_API_KEY` не задан в `.env` — используется template fallback
- Проверить на сервере: `grep OPENROUTER /opt/malenkie-legendy/backend/.env`
- Модель: `openai/gpt-4o-mini` (настраивается через `OPENROUTER_MODEL`)

### Pollinations.ai (картинки)
- Бесплатный, но нестабильный (502/503 ошибки)
- Основной провайдер: Stability AI (нужен `STABILITY_API_KEY`)
- Проверить: `grep STABILITY /opt/malenkie-legendy/backend/.env`

### Кириллица в PDF
- Требует шрифт DejaVuSans: `apt-get install fonts-dejavu-core`
- Проверить: `ls /usr/share/fonts/truetype/dejavu/`

---

## Команды на сервере

```bash
# Логи бота
journalctl -u malenkie-bot -f

# Логи backend
journalctl -u malenkie-legendy-backend -f

# Перезапуск
systemctl restart malenkie-bot
systemctl restart malenkie-legendy-backend

# Тест генерации
curl -s -X POST http://127.0.0.1:8010/api/story/generate \
  -H 'Content-Type: application/json' \
  -d '{"external_user_id":"test","channel":"telegram","child_name":"Аня","age":6,"gender":"female","style":"magic","photo_enabled":false}' \
  | python3 -m json.tool | grep -E 'story_text|pdf_url|detail'
```

---

---

### Сессия 4 (2026-03-13) — мощный апгрейд

**Изменения:**

**`backend/app/models.py`** — добавлены 4 поля в `Child`:
- `favorite_animal`, `favorite_color`, `hobby`, `favorite_place`

**`backend/app/schemas.py`** — те же 4 поля в `StoryGenerateRequest`

**`backend/app/services/text_service.py`** — полная переработка:
- Промпт в стиле Астрид Линдгрен + Роальд Даль + Туве Янссон + Корнелия Функе
- Объём сказки увеличен до 7000–9000 символов
- Предпочтения ребёнка включаются в сюжет как обязательные элементы
- 5 image_prompts с разными типами кадров (world shot / discovery / challenge / helper / triumph)
- Серийные сказки: hero character_level растёт с каждым эпизодом, new challenges escalate

**`backend/app/services/image_service.py`** — разные иллюстрации:
- `_SHOT_MODIFIERS[i]` добавляет к каждому из 5 изображений уникальный тип кадра
- Фото-референс: при наличии фото используется `/control/style` endpoint Stability AI

**`backend/app/services/pdf_service.py`** — профессиональная книжная вёрстка:
- Тёплый кремовый фон на всех страницах
- Декоративные угловые орнаменты
- Заголовки глав на цветной полосе (тёмно-коричневая лента + белый текст)
- Иллюстрации в двойной декоративной рамке
- Номера страниц + running header
- Финальный орнамент "Конец"

**`backend/app/services/story_service.py`** — передача предпочтений в генерацию

**`bot/bot.py`** — расширенная анкета:
- Новые состояния: `animal` / `color` / `hobby` / `place` / `photo_choice` / `photo_upload`
- Вопросы: любимое животное (текст), цвет (6 кнопок), занятие (8 кнопок), место (6 кнопок)
- Опциональное фото: если user отправляет фото → `photo_base64` → Stability AI
- Серийные сказки: при episode > 1 показывает "Эпизод N: продолжение!"
- Подписи к картинкам: "Мир сказки / Первое открытие / Испытание / Верный друг / Победа!"

**⚠️ ТРЕБУЕТСЯ МИГРАЦИЯ БД на сервере:**
```sql
ALTER TABLE children ADD COLUMN IF NOT EXISTS favorite_animal VARCHAR(120);
ALTER TABLE children ADD COLUMN IF NOT EXISTS favorite_color VARCHAR(50);
ALTER TABLE children ADD COLUMN IF NOT EXISTS hobby VARCHAR(120);
ALTER TABLE children ADD COLUMN IF NOT EXISTS favorite_place VARCHAR(120);
```
Выполнить: `psql -U postgres -d malenkie_legendy -c "ALTER TABLE children ADD COLUMN IF NOT EXISTS favorite_animal VARCHAR(120); ALTER TABLE children ADD COLUMN IF NOT EXISTS favorite_color VARCHAR(50); ALTER TABLE children ADD COLUMN IF NOT EXISTS hobby VARCHAR(120); ALTER TABLE children ADD COLUMN IF NOT EXISTS favorite_place VARCHAR(120);"`

---

---

### Сессия 5 (2026-03-16) — UX, качество картинок, PDF-полировка

**`bot/bot.py`:**
- Правильное склонение возраста: `age_word()` → "4 года" вместо "4 лет"
- Disney заменён на **Советская анимация** (Союзмультфильм) во всех местах бота
- На сервере добавлен шаг **purpose** (цель сказки): смелость / страх / творчество / дружба / уверенность / сказка на ночь

**`backend/app/services/image_service.py`:**
- Добавлен стиль `soviet` — жёсткий промпт на стиль Союзмультфильм (Чебурашка 1966)
- DALL-E 3 → **DALL-E 2** (вдвое дешевле для массовой генерации)
- `_BASE_QUALITY` дополнен: `"correct human anatomy, exactly five fingers on each hand, no extra limbs, only named characters in scene"`
- Стили стали более детальными и жёсткими (точный подстиль для Ghibli, Pixar, watercolor и т.д.)

**`backend/app/services/pdf_service.py`:**
- Заголовки глав: цветная полоса убрана → **жирный шрифт 17pt**, цвет палитры
- Обложка: рамка убрана → **чистое изображение** (без border)
- "Конец": размер увеличен до **22pt**
- Добавлена строка: **"{Имя}, до встречи в будущих приключениях!"**

**`backend/app/services/text_service.py`:**
- next_hook: обязательно заканчивается отсылкой к следующей сказке ("...история следующей сказки!" / "Узнаем в следующий раз!")
- Добавлен стиль `soviet` в `_IMG_STYLE_FOR_PROMPT`
- На сервере: функция `_build_char_desc()` — детерминированное описание персонажа (по имени), используется для всех 5 промптов → визуальная консистентность

**GPT-промпт для UI-картинок бота:** готов (см. предыдущий ответ ассистента), 13 иллюстраций для каждого шага анкеты.

---

## Флоу бота (FSM — актуальная версия)

```
/start → [Создать сказку]
  → "Как зовут ребёнка?" (текст)
  → "Сколько лет?" [3..11] (кнопки)
  → "Мальчик / Девочка" (кнопки)
  → "Цель сказки?" [6 кнопок: смелость / страх / творчество / дружба / уверенность / на ночь]
  → "Стиль сказки?" [6 кнопок: волшебная / приключение / природа / космос / нежная / эпическая]
  → "Стиль иллюстраций?" [6 кнопок: акварель / гибли / советская / pixar / мультик / книжная]
  → "Любимое животное?" (свободный текст)
  → "Любимый цвет?" [6 кнопок]
  → "Любимое занятие?" [8 кнопок]
  → "Любимое место?" [6 кнопок]
  → "Добавить фото?" [Да / Пропустить]
  → POST /api/story/generate
  → обложка (image[0]) + главы с картинками (image[1-3]) + текст + крючок + финал (image[4]) + PDF
```

---

## Следующие шаги (план)

- [x] Серийные сказки — продолжение истории с памятью персонажей
- [x] Генерация картинок по фото ребёнка (Stability AI /control/style)
- [x] Разные иллюстрации (5 уникальных кадров)
- [x] Красивый PDF (профессиональная книжная вёрстка, пергамент, орнаменты)
- [x] Мини-анкета с предпочтениями ребёнка (животное, цвет, хобби, место)
- [x] Цель сказки (purpose) — терапевтический вектор
- [x] Советская анимация вместо Disney
- [x] Правильное склонение возраста в боте
- [x] PDF: заголовки без рамки, крупный "Конец", прощальная фраза с именем
- [x] Картинки: правильная анатомия рук, консистентный персонаж
- [x] Удешевление генерации (DALL-E 2)
- [ ] UI-картинки для шагов анкеты бота (промпт готов)
- [ ] Платёжная интеграция (эпизоды за подписку)
- [ ] Webhook вместо polling для production
- [ ] HTTPS на сервере (Nginx + Let's Encrypt)
- [ ] InstantID / IP-Adapter для реального сходства с фото
