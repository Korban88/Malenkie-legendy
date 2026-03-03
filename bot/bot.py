import os

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
BACKEND_URL = os.getenv('BACKEND_URL', 'http://127.0.0.1:8010')

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer('Привет! Это Маленькие легенды. Напиши: СКАЗКА')


@dp.message(F.text.lower().contains('сказка'))
async def story(message: Message):
    payload = {
        'external_user_id': str(message.from_user.id),
        'channel': 'telegram',
        'child_name': 'Герой',
        'age': 7,
        'gender': 'neutral',
        'style': 'auto',
        'photo_enabled': False,
    }
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(f'{BACKEND_URL}/api/story/generate', json=payload)
        data = resp.json()
    await message.answer(f"{data.get('title')}\n\n{data.get('story_text')}\n\n{data.get('next_hook')}")


if __name__ == '__main__':
    import asyncio

    asyncio.run(dp.start_polling(bot))
