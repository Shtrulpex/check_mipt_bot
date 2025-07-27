import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from aiogram.filters import CommandStart, Command
from aiogram.types import ForceReply, InlineKeyboardMarkup, InlineKeyboardButton
import requests

from parser.parser import Parser


class Register(StatesGroup):
    waiting_for_student_number = State()
    waiting_for_new_student_number = State()
    waiting_for_url = State()
    waiting_for_new_url = State()

class BotRuler:
    def __init__(self, token, db_worker):
        self.bot = Bot(token=token)
        self.dp = Dispatcher()
        self.scheduler = AsyncIOScheduler()
        for i in range(9, 23):
            self.scheduler.add_job(self.update_parsers, 'cron', hour=i, minute=3)
        self.scheduler.add_job(self.send_daily_message, 'cron', hour=10, minute=0)
        self.scheduler.add_job(self.send_daily_message, 'cron', hour=23, minute=0)
        self.db_worker = db_worker
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
        self.init_logger()
    
    def init_logger(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        
        handler = logging.FileHandler(os.path.join(os.getenv("LOG_DIR"), 'bot.log'))
        handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        handler.setFormatter(file_formatter)
        
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter('%(asctime)s | %(levelname)-8s | Bot:    %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        console_handler.setFormatter(console_formatter)
        
        self.logger.addHandler(handler)
        self.logger.addHandler(console_handler)

    async def start_polling(self):
        self.scheduler.start()
        await self.dp.start_polling(self.bot)

    async def update_parsers(self):
        """Обновляет парсеры для всех URL."""
        try:
            self.logger.info("Updating parsers for all URLs.")
            for k in self.parsers:
                self.parsers[k].load_html()
        except Exception as e:
            self.logger.error("Error updating parsers: %s", str(e))

    async def send_daily_message(self):
        try:
            self.logger.info("Sending daily message to all users.")
            for student_id, user_id, url_id in self.db_worker.get_all_users_info():
                if url_id in self.parsers:
                    try:
                        student_info = self.parsers[url_id](int(student_id))
                        await self.bot.send_message(
                            user_id,
                            f"Информация о студенте {student_id}:\n{student_info}"
                        )
                    except Exception as e:
                        self.logger.error("Error getting info for student %s and url %s: %s", student_id, self.parsers[url_id].url, str(e))
                        await self.bot.send_message(
                            user_id,
                            f"Не удалось получить информацию о студенте {student_id}. Проверьте URL {self.parsers[url_id].url}."
                        )
            self.logger.info("Sending finished successfully.")
        except Exception as e:
            self.logger.error("Error sending daily message: %s", str(e))
    
    async def main_command(self, message: Message, state: FSMContext):
        """Обработчик команды /start, /menu"""
        self.logger.info("User %s went to menu.", message.from_user.id)
        await state.clear()  # Очистка состояния перед началом
        await message.answer(
            "Привет! Я бот для получения информации о студентах.\n"
            "Нажмите одну из кнопок ниже, чтобы начать.",
            reply_markup=self.standard_keyboard
        )
    
    async def get_url_button(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработчик кнопки получения URL."""
        try:
            self.logger.info(f"User {callback.from_user.id} requested URL list.")
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
        except Exception as e:
            self.logger.error("Error in get_url_button for user_id=%s", user_id)
            await callback.answer("Произошла ошибка при получении списка URL.")

    async def url_button_handler(self, callback: types.CallbackQuery, state: FSMContext):
        try:
            if callback.data == "back_to_menu":
                self.logger.info("User %s returned to main menu.", callback.from_user.id)
                await callback.message.edit_text(
                    "Вы вернулись в главное меню.",
                    reply_markup=self.standard_keyboard
                )
                await state.clear()
            elif callback.data == "add_new_url":
                self.logger.info("User %s requested to add a new URL.", callback.from_user.id)
                await callback.answer(
                    "Введите новый URL:",
                    reply_markup=ForceReply(input_field_placeholder="Введите URL")
                )
                await state.set_state(Register.waiting_for_new_url)
            elif callback.data.startswith("del_url_"):
                url_id = int(callback.data.split("_")[2])
                self.logger.info("User %s requested to delete a URL_%s", callback.from_user.id, url_id)
                if self.db_worker.delete_url(url_id, callback.from_user.id):
                    self.parsers.pop(url_id, None)
                self.logger.info("URL %s deleted successfully for user %s.", url_id, callback.from_user.id)

                await callback.answer("URL успешно удален!")
                await self.get_url_button(callback, state)
            else:
                self.logger.warning("Unknown callback data: %s", callback.data)
        except Exception as e:
            self.logger.error("Error in url_button_handler from user_id=%s", callback.from_user.id)
            await callback.answer("Произошла внутренняя ошибка. Попробуйте позже.")
    
    async def get_student_button(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработчик кнопки получения student_id."""
        try:
            self.logger.info("User %s requested student list.", callback.from_user.id)
            students = self.db_worker.get_user_student_ids(callback.from_user.id)

            inline_keyboard = [
                [InlineKeyboardButton(text=str(student_id[0]), callback_data=f"del_student_{student_id[0]}")]
                for student_id in students
            ]
            self.logger.debug("Students found: %s", students)
            inline_keyboard.append([InlineKeyboardButton(text="Добавить нового студента", callback_data="add_new_student")])
            inline_keyboard.append([InlineKeyboardButton(text="Назад", callback_data="back_to_menu")])
            markup = InlineKeyboardMarkup(
                inline_keyboard=inline_keyboard
            )

            await callback.message.edit_text("Отслеживаемые студенты, нажмите на того, которого надо удалить", reply_markup=markup)
            await state.set_state(Register.waiting_for_student_number)
        except Exception as e:
            self.logger.error("Error in get_student_button for user_id=%s", callback.from_user.id)
            await callback.answer("Произошла ошибка при получении списка студентов.")

    async def student_button_handler(self, callback: types.CallbackQuery, state: FSMContext):
        try:
            if callback.data == "back_to_menu":
                self.logger.info("User %s returned to main menu.", callback.from_user.id)
                await callback.message.edit_text(
                    "Вы вернулись в главное меню.",
                    reply_markup=self.standard_keyboard
                )
                await state.clear()
            elif callback.data == "add_new_student":
                self.logger.info("User %s requested to add a new student.", callback.from_user.id)
                await callback.answer(
                    "Введите новый уникальный идентификатор студента:",
                    reply_markup=ForceReply(input_field_placeholder="Введите уникальный идентификатор студента")
                )
                await state.set_state(Register.waiting_for_new_student_number)
            elif callback.data.startswith("del_student_"):
                student_id = int(callback.data.split("_")[2])
                self.logger.info("User %s requested to delete student_%s", callback.from_user.id, student_id)
                self.db_worker.delete_student_id(student_id, callback.from_user.id)
                self.logger.info("Student %s deleted successfully for user %s.", student_id, callback.from_user.id)

                await callback.answer("Студент успешно удален!")
                await self.get_student_button(callback, state)
        except Exception as e:
            self.logger.error("Error in student_button_handler for user_id=%s", callback.from_user.id)
            await callback.answer("Произошла внутренняя ошибка. Попробуйте позже.")
    
    async def callback_handler(self, callback: types.CallbackQuery, state: FSMContext):
        try:
            if callback.data == "urls":
                await self.get_url_button(callback, state)
            elif callback.data == "student_number":
                await self.get_student_button(callback, state)
            elif callback.data == "give_info_now":
                self.logger.info("User %s requested information for all students.", callback.from_user.id)
                info = self.db_worker.get_user_info(callback.from_user.id)
                self.logger.debug("User %s info: %s", callback.from_user.id, info)
                for student_id, _, url_id in info:
                    if url_id in self.parsers:
                        student_info = self.parsers[url_id](int(student_id))
                        await callback.message.answer(
                            f"Информация о студенте {student_id}:\n{student_info}",
                        )
                    else:
                        await callback.message.answer(
                            f"Нет информации для студента {student_id}.",
                        )
                if len(info) == 0:
                    await callback.answer("Добавьте, пожалуйста студента и/или URL")
        except Exception as e:
            self.logger.error("Error in callback_handler for user_id=%s", callback.from_user.id)
            await callback.answer("Произошла внутренняя ошибка. Попробуйте позже.")
    
    async def handle_new_url(self, message: Message, state: FSMContext):
        """Обработчик ввода нового URL."""
        try:
            new_url = message.text.strip()
            user_id = message.from_user.id
            if self._is_url_accessible(new_url):
                url_id = self.db_worker.add_url(new_url, user_id)
                self.logger.info("User %s added new URL: %s with id %s", user_id, new_url, url_id)
                if not url_id in self.parsers:
                    self.parsers[url_id] = Parser(new_url)
                await self.main_command(message, state)
                await state.clear()
            else:
                await message.answer("Пожалуйста, введите корректный URL.")
        except Exception as e:
            self.logger.error("Error handling new URL from user_id=%s: %s", message.from_user.id, str(e))
            await message.answer("Произошла ошибка при добавлении URL. Пожалуйста, попробуйте еще раз.")
    
    async def handle_new_student(self, message: Message, state: FSMContext):
        """Обработчик ввода нового URL."""
        try:
            new_student_id = message.text.strip()
            self.logger.info("User %s is adding a new student %s.", message.from_user.id, new_student_id)
            user_id = message.from_user.id
            if new_student_id.isdigit():
                self.db_worker.add_user(new_student_id, user_id)
                self.logger.info("User %s added student %s.", user_id, new_student_id)
                await self.main_command(message, state)
                await state.clear()
            else:
                await message.answer("Пожалуйста, введите корректный уникальный идентификатор студента.")
        except Exception as e:
            self.logger.error("Error handling new student from user_id=%s: %s", message.from_user.id, str(e))
            await message.answer("Произошла ошибка при добавлении студента. Пожалуйста, попробуйте еще раз.")
    
    def _is_url_accessible(self, url: str) -> bool:
        try:
            response = requests.get(url, timeout=5, allow_redirects=True)
            return response.status_code < 400
        except Exception:
            return False
