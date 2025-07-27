import os
import shutil

from dotenv import load_dotenv
import asyncio

from bot.telegram_bot import BotRuler
from database.db_worker import DatabaseWorker

if __name__ == '__main__':
    load_dotenv()
    if os.path.exists(os.getenv("LOG_DIR")):
        shutil.rmtree(os.getenv("LOG_DIR"))
    os.makedirs(os.getenv("LOG_DIR"), exist_ok=True)
    bot_ruler = BotRuler(os.getenv("BOT_TOKEN"), DatabaseWorker())
    asyncio.run(bot_ruler.start_polling())
