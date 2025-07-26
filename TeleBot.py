from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from aiogram.filters import CommandStart, Command
import asyncio
from aiogram.types import ForceReply, InlineKeyboardMarkup, InlineKeyboardButton
from parser import Parser

from db_worker import DB_worker_unit


class Register(StatesGroup):
    waiting_for_student_number = State()
    waiting_for_new_student_number = State()
    waiting_for_url = State()
    waiting_for_new_url = State()

class BotRuler:
    def __init__(self, token):
        self.bot = Bot(token=token)
        self.dp = Dispatcher()
        self.scheduler = AsyncIOScheduler()
        for i in range(9, 23):
            self.scheduler.add_job(self.update_parsers, 'cron', hour=i, minute=3)
        self.scheduler.add_job(self.send_daily_message, 'cron', hour=10, minute=0)
        self.scheduler.add_job(self.send_daily_message, 'cron', hour=23, minute=0)
        self.db_worker = DB_worker_unit
        self.parsers = {}

        for id, url in self.db_worker.get_urls():
            self.parsers[id] = Parser(url)

        self.standard_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="URLs", callback_data="urls"),
                InlineKeyboardButton(text="Студенты", callback_data="student_number")],
                [InlineKeyboardButton(text="Всю информацию прямо сейчас", callback_data="give_info_now")]
            ]
        )

        self.dp.message.register(self.main_command, CommandStart())
        self.dp.message.register(self.main_command, Command("menu"))
        self.dp.message.register(self.handle_new_url, Register.waiting_for_new_url)
        self.dp.message.register(self.handle_new_student, Register.waiting_for_new_student_number)
        self.dp.callback_query.register(self.url_button_handler, Register.waiting_for_url)
        self.dp.callback_query.register(self.student_button_handler, Register.waiting_for_student_number)
        self.dp.callback_query.register(self.callback_handler)

    async def start_polling(self):
        self.scheduler.start()
        await self.dp.start_polling(self.bot)

    async def update_parsers(self):
        """Обновляет парсеры для всех URL."""
        for k in self.parsers:
            self.parsers[k].load_html()

    async def send_daily_message(self):
        for student_id, user_id, url_id in self.db_worker.get_all_users_info():
            if url_id in self.parsers:
                student_info = self.parsers[url_id](int(student_id))
                await self.bot.send_message(
                    user_id,
                    f"Информация о студенте {student_id}:\n{student_info}"
                )
    
    async def main_command(self, message: Message, state: FSMContext):
        """Обработчик команды /start, /menu"""
        await state.clear()  # Очистка состояния перед началом
        await message.answer(
            "Привет! Я бот для получения информации о студентах.\n"
            "Нажмите",
            reply_markup=self.standard_keyboard
        )
    
    async def get_url_button(self, callback: Message, state: FSMContext):
        """Обработчик кнопки получения URL."""
        urls = self.db_worker.get_user_urls(callback.from_user.id)
        markup_urls = {}
        for data in urls:
            markup_urls[data[0]] = f'{data[1]}'
        inline_keyboard = [
            [InlineKeyboardButton(text=f'{i+1:02}: {markup_urls[url_id]}', callback_data=f"del_url_{url_id}")]
            for i, url_id in enumerate(markup_urls)
        ]
        inline_keyboard.append([InlineKeyboardButton(text="Добавить новый URL", callback_data="add_new_url")])
        inline_keyboard.append([InlineKeyboardButton(text="Назад", callback_data="back_to_menu")])
        markup = InlineKeyboardMarkup(
            inline_keyboard=inline_keyboard
        )
        out_text = ["Отслеживаемые списки:"]
        out_text.extend([f"{i+1:02}: {markup_urls[url_id]}" for i, url_id in enumerate(markup_urls)])
        await callback.message.edit_text('\n'.join(out_text), reply_markup=markup)
        await state.set_state(Register.waiting_for_url)

    async def url_button_handler(self, callback: Message, state: FSMContext):
        if callback.data == "back_to_menu":
            await callback.message.edit_text(
                "Вы вернулись в главное меню.",
                reply_markup=self.standard_keyboard
            )
            await state.clear()
        elif callback.data == "add_new_url":
            await callback.answer(
                "Введите новый URL:",
                reply_markup=ForceReply(input_field_placeholder="Введите URL")
            )
            await state.set_state(Register.waiting_for_new_url)
        elif callback.data.startswith("del_url_"):
            url_id = int(callback.data.split("_")[2])
            if self.db_worker.delete_url(url_id, callback.from_user.id):
                self.parsers.pop(url_id, None)

            await callback.answer("URL успешно удален!")
            await self.get_url_button(callback, state)
    
    async def get_student_button(self, callback: Message, state: FSMContext):
        """Обработчик кнопки получения student_id."""
        students = self.db_worker.get_user_student_ids(callback.from_user.id)

        inline_keyboard = [
            [InlineKeyboardButton(text=str(student_id[0]), callback_data=f"del_student_{student_id[0]}")]
            for student_id in students
        ]
        inline_keyboard.append([InlineKeyboardButton(text="Добавить нового студента", callback_data="add_new_student")])
        inline_keyboard.append([InlineKeyboardButton(text="Назад", callback_data="back_to_menu")])
        markup = InlineKeyboardMarkup(
            inline_keyboard=inline_keyboard
        )

        await callback.message.edit_text("Отслеживаемые студенты, нажмите на того, которого надо удалить", reply_markup=markup)
        await state.set_state(Register.waiting_for_student_number)

    async def student_button_handler(self, callback: Message, state: FSMContext):
        if callback.data == "back_to_menu":
            await callback.message.edit_text(
                "Вы вернулись в главное меню.",
                reply_markup=self.standard_keyboard
            )
            await state.clear()
        elif callback.data == "add_new_student":
            await callback.answer(
                "Введите новый уникальный идентификатор студента:",
                reply_markup=ForceReply(input_field_placeholder="Введите уникальный идентификатор студента")
            )
            await state.set_state(Register.waiting_for_new_student_number)
        elif callback.data.startswith("del_student_"):
            student_id = int(callback.data.split("_")[2])
            self.db_worker.delete_student_id(student_id, callback.from_user.id)

            await callback.answer("Студент успешно удален!")
            await self.get_student_button(callback, state)
    
    async def callback_handler(self, callback: types.CallbackQuery, state: FSMContext):
        if callback.data == "urls":
            await self.get_url_button(callback, state)
        elif callback.data == "student_number":
            await self.get_student_button(callback, state)
        elif callback.data == "give_info_now":
            for student_id, _, url_id in self.db_worker.get_user_info(callback.from_user.id):
                if url_id in self.parsers:
                    student_info = self.parsers[url_id](int(student_id))
                    await callback.message.answer(
                        f"Информация о студенте {student_id}:\n{student_info}",
                    )
                else:
                    await callback.message.answer(
                        f"Нет информации для студента {student_id}.",
                    )
    
    async def handle_new_url(self, message: Message, state: FSMContext):
        """Обработчик ввода нового URL."""
        new_url = message.text.strip()
        user_id = message.from_user.id
        if new_url:  # TODO: добавить проверку на корректность URL
            url_id = self.db_worker.add_url(new_url, user_id)
            if not url_id in self.parsers:
                self.parsers[url_id] = Parser(new_url)
            await self.main_command(message, state)
            await state.clear()
        else:
            await message.answer("Пожалуйста, введите корректный URL.")
    
    async def handle_new_student(self, message: Message, state: FSMContext):
        """Обработчик ввода нового URL."""
        new_student_id = message.text.strip()
        user_id = message.from_user.id
        if new_student_id.isdigit():
            self.db_worker.add_user(new_student_id, user_id)
            await self.main_command(message, state)
            await state.clear()
        else:
            await message.answer("Пожалуйста, введите корректный уникальный идентификатор студента.")
    

if __name__ == "__main__":
    TOKEN = "8295045989:AAGPV2gMaBEPjHKw6p3Nu6PNKY7_o1nQPrg"
    bot_ruler = BotRuler(TOKEN)
    asyncio.run(bot_ruler.start_polling())
