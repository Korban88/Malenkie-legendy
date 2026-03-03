# n8n MVP workflow

1. Импортируйте `malenkie_legendy_mvp_workflow.json` в n8n.
2. Создайте credentials `Telegram Bot` (токен бота).
3. В переменных n8n задайте `BACKEND_URL=http://31.129.108.93:8010`.
4. В узле `Generate Story` замените статичные поля анкеты на данные из вашей ветки диалога.
5. Для оплаты добавьте перед `Generate Story` шаги:
   - `POST /api/payments/orders`
   - ожидание подтверждения
   - `POST /api/payments/orders/{id}/confirm`
6. Кнопки сделаны inline; для постоянного меню используйте Telegram BotFather commands.
