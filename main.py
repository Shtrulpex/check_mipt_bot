import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from bot.telegram_bot import BotRuler
from database.db_worker import DatabaseWorker


def configure_logging() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_dir = os.getenv("LOG_DIR")
    if log_dir:
        path = Path(log_dir)
        path.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path / "bot.log"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


async def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is required")
    await BotRuler(token, DatabaseWorker()).start_polling()


if __name__ == "__main__":
    load_dotenv()
    configure_logging()
    asyncio.run(main())
