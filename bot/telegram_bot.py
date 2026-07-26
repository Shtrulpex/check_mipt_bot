from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database.db_worker import DatabaseWorker, Tracking
from parser.parser import (
    AdmissionsParser,
    ParserError,
    UnsupportedSourceError,
    default_registry,
    normalize_applicant_id,
)


MSU_PRESETS = {
    "msu_vmk_submitted": ("МГУ ВМК — предварительный", "https://cpk.msu.ru/submitted/bachelor/dep_02"),
    "msu_vmk_rating": ("МГУ ВМК — конкурсный", "https://cpk.msu.ru/rating/dep_02"),
    "msu_math_submitted": ("МГУ мехмат — предварительный", "https://cpk.msu.ru/submitted/bachelor/dep_01"),
    "msu_math_rating": ("МГУ мехмат — конкурсный", "https://cpk.msu.ru/rating/dep_01"),
}


class Register(StatesGroup):
    waiting_for_custom_url = State()
    waiting_for_applicant_id = State()


class BotRuler:
    def __init__(self, token: str, db_worker: DatabaseWorker):
        self.bot = Bot(token=token)
        self.dp = Dispatcher()
        self.db_worker = db_worker
        self.registry = default_registry()
        self.logger = logging.getLogger(__name__)
        self.parsers: dict[int, AdmissionsParser] = {}
        self.pending_parsers: dict[int, AdmissionsParser] = {}
        self.moscow_tz = ZoneInfo("Europe/Moscow")
        configured_year = os.getenv("ADMISSION_YEAR")
        self.admission_year = (
            int(configured_year) if configured_year else datetime.now(self.moscow_tz).year
        )
        self.scheduler = AsyncIOScheduler(timezone=self.moscow_tz)
        for hour in range(9, 23):
            self.scheduler.add_job(self.update_parsers, "cron", hour=hour, minute=3)
        self.scheduler.add_job(self.send_daily_message, "cron", hour=10, minute=30)
        self.scheduler.add_job(self.send_daily_message, "cron", hour=22, minute=30)

        for source in self.db_worker.get_sources():
            try:
                self.parsers[source.id] = self.registry.create(
                    source.url, load=False, expected_year=self.admission_year
                )
            except UnsupportedSourceError:
                self.logger.warning("Ignoring unsupported persisted source: %s", source.url)

        self.standard_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Отслеживания", callback_data="trackings")],
                [InlineKeyboardButton(text="Вся информация сейчас", callback_data="give_info_now")],
            ]
        )

        self.dp.message.register(self.main_command, CommandStart())
        self.dp.message.register(self.main_command, Command("menu"))
        self.dp.message.register(self.handle_custom_url, Register.waiting_for_custom_url)
        self.dp.message.register(self.handle_applicant_id, Register.waiting_for_applicant_id)
        self.dp.callback_query.register(self.callback_handler)

    async def start_polling(self) -> None:
        await self.update_parsers()
        self.scheduler.start()
        await self.dp.start_polling(self.bot)

    async def update_parsers(self) -> None:
        if not self.parsers:
            return
        self.logger.info("Refreshing %d admissions sources", len(self.parsers))
        source_ids = list(self.parsers)
        outcomes = await asyncio.gather(
            *(asyncio.to_thread(self.parsers[source_id].refresh) for source_id in source_ids),
            return_exceptions=True,
        )
        for source_id, outcome in zip(source_ids, outcomes):
            parser = self.parsers[source_id]
            if outcome is True:
                self.db_worker.update_source_title(source_id, parser.title)
            elif isinstance(outcome, Exception):
                self.logger.error("Refresh failed for %s: %s", parser.url, outcome)
            else:
                self.logger.warning("Refresh failed for %s: %s", parser.url, parser.last_error)

    async def send_daily_message(self) -> None:
        self.logger.info("Sending scheduled admissions reports")
        for tracking in self.db_worker.get_all_trackings():
            await self._send_tracking(tracking.user_id, tracking)

    async def main_command(self, message: Message, state: FSMContext) -> None:
        self.pending_parsers.pop(message.from_user.id, None)
        await state.clear()
        await message.answer(
            "Бот отслеживает конкурсные списки по точной связке страницы и ID заявления.",
            reply_markup=self.standard_keyboard,
        )

    async def callback_handler(self, callback: types.CallbackQuery, state: FSMContext) -> None:
        data = callback.data or ""
        try:
            if data == "back_to_menu":
                await callback.answer()
                await state.clear()
                self.pending_parsers.pop(callback.from_user.id, None)
                await callback.message.edit_text(
                    "Бот отслеживает конкурсные списки по точной связке страницы и ID заявления.",
                    reply_markup=self.standard_keyboard,
                )
            elif data == "trackings":
                await callback.answer()
                await self.show_trackings(callback, state)
            elif data == "add_tracking":
                await callback.answer()
                await self.show_source_picker(callback, state)
            elif data == "custom_source":
                await callback.answer()
                await state.set_state(Register.waiting_for_custom_url)
                await callback.message.answer(
                    "Пришлите полную ссылку на поддерживаемый конкурсный список:",
                    reply_markup=ForceReply(input_field_placeholder="https://..."),
                )
            elif data.startswith("preset_"):
                await callback.answer("Проверяю страницу…")
                preset_key = data.removeprefix("preset_")
                await self._prepare_source(callback.from_user.id, MSU_PRESETS[preset_key][1], state, callback.message)
            elif data.startswith("del_tracking_"):
                await callback.answer()
                tracking_id = int(data.removeprefix("del_tracking_"))
                unused_source = self.db_worker.delete_tracking(tracking_id, callback.from_user.id)
                if unused_source is not None:
                    self.parsers.pop(unused_source, None)
                await self.show_trackings(callback, state)
            elif data == "give_info_now":
                await callback.answer()
                trackings = self.db_worker.get_user_trackings(callback.from_user.id)
                if not trackings:
                    await callback.message.answer("Сначала добавьте хотя бы одно отслеживание.")
                for tracking in trackings:
                    await self._send_tracking(callback.from_user.id, tracking)
            else:
                await callback.answer("Неизвестная команда")
        except (ParserError, UnsupportedSourceError, KeyError) as exc:
            self.logger.info("Cannot process source: %s", exc)
            await callback.message.answer(f"Не удалось использовать страницу: {exc}")
        except Exception:
            self.logger.exception("Callback handling failed for user %s", callback.from_user.id)
            await callback.message.answer("Произошла внутренняя ошибка. Попробуйте позже.")

    async def show_trackings(self, callback: types.CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        trackings = self.db_worker.get_user_trackings(callback.from_user.id)
        buttons: list[list[InlineKeyboardButton]] = []
        lines = ["Отслеживания (нажмите, чтобы удалить):"]
        for index, tracking in enumerate(trackings, start=1):
            title = tracking.title or tracking.provider.upper()
            label = f"{index:02}. {title}: {tracking.applicant_id}"
            buttons.append(
                [InlineKeyboardButton(text=label[:60], callback_data=f"del_tracking_{tracking.id}")]
            )
            lines.append(label)
        buttons.append([InlineKeyboardButton(text="Добавить", callback_data="add_tracking")])
        buttons.append([InlineKeyboardButton(text="Назад", callback_data="back_to_menu")])
        await callback.message.edit_text(
            "\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )

    async def show_source_picker(self, callback: types.CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        buttons = [
            [InlineKeyboardButton(text=label, callback_data=f"preset_{key}")]
            for key, (label, _) in MSU_PRESETS.items()
        ]
        buttons.extend(
            [
                [InlineKeyboardButton(text="Другой URL", callback_data="custom_source")],
                [InlineKeyboardButton(text="Назад", callback_data="trackings")],
            ]
        )
        await callback.message.edit_text(
            "Выберите список. Предварительный и конкурсный ID могут различаться.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )

    async def handle_custom_url(self, message: Message, state: FSMContext) -> None:
        await self._prepare_source(message.from_user.id, message.text or "", state, message)

    async def _prepare_source(
        self,
        user_id: int,
        url: str,
        state: FSMContext,
        target: Message,
    ) -> None:
        try:
            parser = await asyncio.to_thread(
                self.registry.create,
                url,
                load=True,
                expected_year=self.admission_year,
            )
        except (ParserError, UnsupportedSourceError) as exc:
            await target.answer(f"Не удалось использовать страницу: {exc}")
            return
        self.pending_parsers[user_id] = parser
        await state.set_state(Register.waiting_for_applicant_id)
        await target.answer(
            f"Страница распознана: {parser.title}.\n"
            "Введите ID, отображаемый именно на этой странице:",
            reply_markup=ForceReply(input_field_placeholder="ID заявления"),
        )

    async def handle_applicant_id(self, message: Message, state: FSMContext) -> None:
        applicant_id = normalize_applicant_id(message.text or "")
        parser = self.pending_parsers.get(message.from_user.id)
        if parser is None:
            await state.clear()
            await message.answer("Сессия добавления истекла. Начните ещё раз через меню.")
            return
        if not applicant_id or len(applicant_id) > 128 or not applicant_id.isprintable():
            await message.answer("Введите непустой ID длиной не более 128 символов.")
            return
        found = parser.lookup(applicant_id)
        if not found:
            await message.answer(
                "Такой ID не найден в основных бюджетных местах этой страницы. "
                "Проверьте ID или пришлите другой."
            )
            return

        _, source_id = self.db_worker.add_tracking(
            parser.url, parser.provider, applicant_id, message.from_user.id
        )
        self.db_worker.update_source_title(source_id, parser.title)
        self.parsers[source_id] = parser
        self.pending_parsers.pop(message.from_user.id, None)
        await state.clear()
        await message.answer(
            f"Отслеживание добавлено. Найдено конкурсных групп: {len(found)}."
        )
        await message.answer(
            "Бот отслеживает конкурсные списки по точной связке страницы и ID заявления.",
            reply_markup=self.standard_keyboard,
        )

    async def _send_tracking(self, user_id: int, tracking: Tracking) -> None:
        parser = self.parsers.get(tracking.source_id)
        if parser is None:
            await self.bot.send_message(user_id, f"Источник для ID {tracking.applicant_id} недоступен.")
            return
        report = parser(tracking.applicant_id)
        for chunk in self._split_message(report):
            try:
                await self.bot.send_message(user_id, chunk)
            except Exception:
                self.logger.exception("Cannot send report to user %s", user_id)
                break

    @staticmethod
    def _split_message(text: str, limit: int = 4000) -> list[str]:
        if len(text) <= limit:
            return [text]
        chunks: list[str] = []
        current = ""
        for block in text.split("\n\n"):
            candidate = f"{current}\n\n{block}".strip()
            if current and len(candidate) > limit:
                chunks.append(current)
                current = block
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks
