"""
Точка входу Telegram-бота курсів валют та криптовалют.

Запуск:
    1. Встановіть залежності:  pip install -r requirements.txt
    2. Задайте токен бота:
       - у файлі config.py (BOT_TOKEN), АБО
       - через змінну середовища: export BOT_TOKEN="ваш_токен"
    3. Запустіть:  python main.py
"""

import logging
import asyncio

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from api_client import coingecko
from handlers import router
from middlewares import AccessMiddleware

# ── Логування ───────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Головна асинхронна функція."""

    if not BOT_TOKEN or "СЮДИ" in BOT_TOKEN:
        logger.error(
            "❌ BOT_TOKEN не задано! Встановіть його у config.py "
            "або через змінну середовища BOT_TOKEN."
        )
        return

    # Ініціалізація бота та диспетчера
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.message.outer_middleware(AccessMiddleware())

    # Підключаємо роутер з обробниками
    dp.include_router(router)

    # Обробник помилок на рівні диспетчера
    @dp.error()
    async def on_error(event):
        logger.exception("Необроблена помилка: %s", event.exception)

    logger.info("🤖 Бот запущено. Натисніть Ctrl+C для зупинки.")

    try:
        await dp.start_polling(bot)
    finally:
        # Коректно закриваємо сесію API-клієнта
        await coingecko.close()
        await bot.session.close()
        logger.info("🛑 Бот зупинено.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Отримано сигнал зупинки.")

