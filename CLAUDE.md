# CLAUDE.md — Malenkie Legendy: полная внутренняя документация

> Этот файл предназначен для будущих сессий с Claude Code.
> Прочитай его целиком — он содержит всё необходимое для продолжения работы.

---

## 1. Проект в двух словах

Telegram-бот, который генерирует персональные детские сказки в PDF с иллюстрациями.
Пользователь вводит имя ребёнка, возраст, предпочтения → бот генерирует сказку через OpenRouter (GPT-4o-mini) + иллюстрации через Together AI FLUX → отдаёт PDF.

**Платёж**: Telegram Stars (XTR). 150 XTR без фото, 200 XTR с фото ребёнка.

---

## 2. Инфраструктура

| Параметр | Значение |
|---|---|
| Сервер | `31.129.108.93` |
| Пользователь | `root` |
| Пароль | `VpD3IRb%ZzxI` |
| SSH | `echo "VpD3IRb%ZzxI" \| ssh -o StrictHostKeyChecking=no root@31.129.108.93 "команда"` |
| Путь к проекту | `/opt/malenkie-legendy/` |
| Backend порт | `8010` |
| Публичный URL | `http://31.129.108.93:8010` |
| PostgreSQL | `127.0.0.1:5433`, db `legend_db`, user `legend_user` |
| DB пароль | `LegendPass2026` |

### Systemd сервисы

```bash
# Backend
systemctl restart malenkie-legendy-backend
journalctl -u malenkie-legendy-backend -n 50

# Bot
systemctl restart malenkie-bot
journalctl -u malenkie-bot -n 50
```

Файлы сервисов:
- `/etc/systemd/system/malenkie-legendy-backend.service` — `python -m uvicorn app.main:app --host 0.0.0.0 --port 8010`
- `/etc/systemd/system/malenkie-bot.service` — `python3 /opt/malenkie-legendy/bot/bot.py`

---

## 3. Структура репозитория

```
backend/
  app/
    config.py             # Settings (pydantic-settings, .env)
    main.py               # FastAPI app + cost-guard validation at startup
    models.py             # SQLAlchemy: User, Child, Story, Order
    schemas.py            # Pydantic request/response schemas
    db.py                 # SQLAlchemy engine (psycopg driver)
    routers/
      story.py            # POST /stories/generate
      payment.py          # Payment-related endpoints
    services/
      story_service.py    # Orchestrates: text → images → PDF
      text_service.py     # OpenRouter (gpt-4o-mini) story generation
      image_service.py    # Image generation (Together AI primary)
      pdf_service.py      # fpdf2 PDF generation (Cyrillic DejaVu fonts)
      cost_guard.py       # ALLOWED_MODELS allowlist, blocks expensive models
  storage/
    images/               # Generated PNG files
    stories/              # Generated PDF files
  .env                    # Secret config (NOT in git)
bot/
  bot.py                  # aiogram 3 Telegram bot (production version)
  .env                    # BOT env (NOT in git)
static/
  ui/                     # Step images for bot messages (welcome.png, etc.)
```

### ⚠️ Файлы только на сервере (НЕ в GitHub)

На сервере есть устаревшие дублирующие файлы — они не используются:
- `/opt/malenkie-legendy/backend/app/services/image_service_server.py`
- `/opt/malenkie-legendy/backend/app/services/pdf_service_server.py`
- `/opt/malenkie-legendy/backend/app/services/text_service_server.py`
- `/opt/malenkie-legendy/bot/bot_server.py`

`story_service.py` на сервере импортирует из стандартных файлов (image_service, pdf_service, text_service) — это правильно.

---

## 4. Переменные окружения

### `/opt/malenkie-legendy/backend/.env`

```env
IMAGE_PROVIDER=together
BACKUP_IMAGE_PROVIDER=openai
TOGETHER_API_KEY=tgp_v1_CiVYSaiw12kTHct199cYkvyK65ZlrIvmpYOwhERrEqE
OPENAI_API_KEY=sk-proj-fB_hOS9_...  (полный ключ на сервере, одна строка)
OPENROUTER_API_KEY=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
STABILITY_API_KEY=sk-HserR6YyFHQA9jnKPQYnSYJBbJyVDB4INtPD4x7hvbJz8tYU  # 402 - НЕТ КРЕДИТОВ
DB_PASSWORD=LegendPass2026
PUBLIC_BASE_URL=http://31.129.108.93:8010
FORCE_EPISODE_ONE=true
```

### `/opt/malenkie-legendy/bot/.env`

Содержит `TELEGRAM_BOT_TOKEN` и `BACKEND_URL=http://127.0.0.1:8010`.

---

## 5. API ключи и их статус

| Сервис | Ключ (начало) | Статус |
|---|---|---|
| Together AI | `tgp_v1_CiVYSaiw12kTHct199cYkvyK65ZlrIvmpYOwhERrEqE` | ✅ Активен, $10 пополнено (март 2026) |
| OpenRouter | `sk-or-v1-1ec801c3e2e651b77076...` | ✅ Активен |
| OpenAI | `sk-proj-fB_hOS9_...` | ✅ Активен (backup) |
| Stability AI | `sk-HserR6YyFH...` | ❌ 402 No Credits |

> Together AI старый ключ `tgp_v1_CYsFywdM9JkCFy3t5jdRW` (от wb-ozon-bot) — другой аккаунт, не использовать.

---

## 6. Генерация изображений — Together AI алгоритм

**Главная идея**: обложка генерируется первой, затем все следующие иллюстрации получают URL обложки как `image_urls` — модель буквально смотрит на обложку при генерации следующих сцен.

```
i=0 (обложка):  FLUX.1.1-pro, без reference → сохраняется как cover_public_url
i=1,2,3:        FLUX.2-pro + image_urls=[cover_public_url] → строгая консистентность персонажей
```

**Endpoint**: `POST https://api.together.xyz/v1/images/generations`

```python
# Обложка
{"model": "black-forest-labs/FLUX.1.1-pro", "prompt": "...", "width": 1024, "height": 1024, "n": 1}

# Следующие (с reference)
{"model": "black-forest-labs/FLUX.2-pro", "prompt": "...", "width": 1024, "height": 1024, "n": 1,
 "image_urls": ["http://31.129.108.93:8010/files/images/xxxx.png"]}
```

Реализация: `backend/app/services/image_service.py` → функция `_together_generate()`.

**Fallback**: если Together упал → OpenAI (DALL-E 3).

---

## 7. PDF генерация

Файл: `backend/app/services/pdf_service.py`

**Шрифты**: DejaVu Sans (заголовки) + Neucha (текст сказки) — оба поддерживают кириллицу.

**Важно**: символ `✦` (U+2726) отсутствует в DejaVu Sans и Neucha → заменён на `◆` (U+25C6) в pdf_service.py. Если LLM генерирует `✦` в тексте сказки — он всё равно появится как квадратик (это проблема text_service.py, не исправлена).

---

## 8. Telegram Stars платёж

Реализован в `bot/bot.py`:
- `STORY_PRICE_XTR = 150` (без фото), `STORY_WITH_PHOTO_PRICE_XTR = 200` (с фото)
- FSM state: `Form.awaiting_payment`
- `_request_payment()` → `answer_invoice()` с `currency="XTR"`
- `@dp.pre_checkout_query()` → автоматически подтверждает
- `@dp.message(F.successful_payment)` → сохраняет `telegram_payment_charge_id`, вызывает `_generate()`
- `story_service.py` → при наличии `telegram_payment_charge_id` создаёт Order с `provider='telegram_stars'`

---

## 9. Деплой на сервер

```bash
# Обновить код из GitHub
echo "VpD3IRb%ZzxI" | ssh -o StrictHostKeyChecking=no root@31.129.108.93 \
  "cd /opt/malenkie-legendy && git pull origin main"

# Перезапустить backend
echo "VpD3IRb%ZzxI" | ssh -o StrictHostKeyChecking=no root@31.129.108.93 \
  "systemctl restart malenkie-legendy-backend"

# Перезапустить bot
echo "VpD3IRb%ZzxI" | ssh -o StrictHostKeyChecking=no root@31.129.108.93 \
  "systemctl restart malenkie-bot"

# Проверить логи
echo "VpD3IRb%ZzxI" | ssh -o StrictHostKeyChecking=no root@31.129.108.93 \
  "journalctl -u malenkie-legendy-backend -n 30 --no-pager"
```

---

## 10. Архитектура запроса

```
Telegram → bot.py → POST /stories/generate (FastAPI)
                          ↓
                    story_service.generate_story()
                          ↓
              ┌───────────────────────────────┐
              │ 1. text_service: OpenRouter   │
              │    gpt-4o-mini → story_text,  │
              │    image_prompts[4], title    │
              │                               │
              │ 2. image_service: Together AI │
              │    4 PNG → /storage/images/   │
              │                               │
              │ 3. pdf_service: fpdf2         │
              │    PDF → /storage/stories/    │
              └───────────────────────────────┘
                          ↓
              bot.py получает pdf_url + images_urls
              → отправляет фото в чат + PDF файл
```

---

## 11. Известные проблемы / TODO

- [ ] `✦` в тексте сказки (генерируется LLM) → квадратики в PDF. Нужно strip/replace в `text_service.py`
- [ ] `force_episode_one=True` — всегда генерирует эпизод 1. Для продакшена нужно переключить на `False`
- [ ] Stability AI ключ без кредитов — платить или убрать из .env совсем
- [ ] Статичные UI-картинки (`/opt/malenkie-legendy/static/ui/*.png`) — не в репозитории
- [ ] `cost_guard.py` — allowlist моделей проверяется при старте backend; если в .env неизвестная модель — сервер не запустится

---

## 12. Частые команды для отладки

```bash
# Проверить текущий .env на сервере
echo "VpD3IRb%ZzxI" | ssh -o StrictHostKeyChecking=no root@31.129.108.93 \
  "cat /opt/malenkie-legendy/backend/.env"

# Проверить импорты story_service.py
echo "VpD3IRb%ZzxI" | ssh -o StrictHostKeyChecking=no root@31.129.108.93 \
  "head -10 /opt/malenkie-legendy/backend/app/services/story_service.py"

# Последний сгенерированный PDF
# http://31.129.108.93:8010/files/stories/<uuid>.pdf

# Health check
curl http://31.129.108.93:8010/health

# Тест генерации (без бота)
curl -X POST http://31.129.108.93:8010/stories/generate \
  -H "Content-Type: application/json" \
  -d '{"external_user_id":"test","channel":"telegram","child_name":"Маша","age":6,"gender":"female","style":"auto","image_style":"watercolor","purpose":"bedtime"}'
```

---

## 13. GitHub репозиторий

https://github.com/Korban88/Malenkie-legendy

Это источник истины для кода. При деплое: `git pull origin main` на сервере.
