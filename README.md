# Маленькие легенды — MVP

Полностью рабочий MVP: FastAPI backend, генерация серийных сказок, картинки, PDF, платежные заказы, n8n workflow и опциональный Telegram bot.

## Структура

- `backend/` — API, БД, генерация историй/изображений/PDF.
- `bot/` — резервный лёгкий Telegram-бот (aiogram).
- `n8n/` — workflow JSON и инструкция.

## 1) Что нужно заполнить

Скопируйте `backend/.env.example` в `backend/.env` и заполните секреты:

- `DB_PASSWORD`
- `OPENROUTER_API_KEY`
- `STABILITY_API_KEY` (или используйте backup provider)
- `PUBLIC_BASE_URL=http://31.129.108.93:8010`

## 2) Быстрый запуск backend (локально или на VPS)

```bash
cd /opt/malenkie-legendy-backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --host 0.0.0.0 --port 8010
```

## 3) systemd (оставляем порт 8010)

Пример `ExecStart`:

```ini
ExecStart=/opt/malenkie-legendy-backend/.venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port 8010
WorkingDirectory=/opt/malenkie-legendy-backend
EnvironmentFile=/opt/malenkie-legendy-backend/backend/.env
```

После изменений:

```bash
sudo systemctl daemon-reload
sudo systemctl restart malenkie-legendy-backend.service
sudo systemctl status malenkie-legendy-backend.service
```

## 4) Проверка API

```bash
curl http://31.129.108.93:8010/health
curl http://31.129.108.93:8010/health_db
```

Генерация истории:

```bash
curl -X POST http://31.129.108.93:8010/api/story/generate \
  -H "Content-Type: application/json" \
  -d '{
    "external_user_id":"tg_123",
    "channel":"telegram",
    "child_name":"Маша",
    "age":6,
    "gender":"girl",
    "style":"auto",
    "parent_note":"Сегодня первый день в садике",
    "photo_enabled":false
  }'
```

История по id:

```bash
curl http://31.129.108.93:8010/api/story/1
```

Последние истории ребёнка:

```bash
curl http://31.129.108.93:8010/api/child/1/stories
```

## 5) Оплаты (провайдер-независимая схема)

### Вариант A: Telegram provider
1. Создаёте заказ `POST /api/payments/orders` с `provider=telegram`.
2. Отправляете пользователю инвойс/ссылку.
3. После webhook подтверждаете `POST /api/payments/orders/{id}/confirm`.

### Вариант B: Link provider
1. Создаёте заказ с `provider=link`.
2. Отправляете ссылку из `payment_url`.
3. После факта оплаты подтверждаете `/confirm`.

После `paid` вызывайте `/api/story/generate` с `order_id`.

## 6) Фото и приватность

- Фото передаётся только в запросе `photo_base64`.
- В БД сохраняется только `photo_hash` (SHA-256), если фото использовалось.
- Исходник фото **не хранится**, если `KEEP_UPLOADED_PHOTO=false`.
- Не логируйте тело запроса с фото в reverse proxy/systemd.

## 7) n8n

См. `n8n/README.md` и `n8n/malenkie_legendy_mvp_workflow.json`.

## 8) Резервный bot (опционально)

```bash
cd bot
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=...
export BACKEND_URL=http://31.129.108.93:8010
python bot.py
```

## 9) Инструкция для владельца (без терминов)

1. Откройте файл `backend/.env`.
2. Вставьте пароли/токены в пустые поля.
3. Перезапустите сервис (`systemctl restart ...`).
4. Проверьте ссылку `/health_db` — должно быть `status: ok`.
5. В n8n импортируйте workflow и вставьте токен Telegram-бота.
6. Запустите workflow и отправьте `/start` в бота.
7. После оплаты бот отправит сказку, картинки и PDF.
