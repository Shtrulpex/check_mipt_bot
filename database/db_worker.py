from contextlib import contextmanager
import os
import logging

from psycopg2 import pool
from psycopg2 import Error as Psycopg2Error


class DatabaseWorker:
    def __init__(self):
        """Инициализация пула соединений с базой данных."""
        self.pool = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT")
        )
        self.init_logger()
        self._create_tables()
    
    def init_logger(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        
        handler = logging.FileHandler(os.path.join(os.getenv("LOG_DIR"), 'db.log'))
        
        handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        handler.setFormatter(file_formatter)
        
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter('%(asctime)s | %(levelname)-8s | DB:     %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        console_handler.setFormatter(console_formatter)
        
        self.logger.addHandler(handler)
        self.logger.addHandler(console_handler)
    
    @contextmanager
    def get_cursor(self):
        conn = self.pool.getconn()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Psycopg2Error as e:
            conn.rollback()
            self.logger.error("SQL query execution error: %s", e.pgerror)
            self.logger.debug(f"SQLSTATE: %s", e.pgcode)
            raise
        except Exception as e:
            conn.rollback()
            self.logger.error("Unknown error: %s", str(e))
            raise
        finally:
            cursor.close()
            self.pool.putconn(conn)
    
    def _create_tables(self):
        """Создание таблицы users, если она не существует."""
        with self.get_cursor() as cur:
            template = """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY NOT NULL,
                    student_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    UNIQUE (student_id, user_id)
                )
            """
            self.logger.debug(template)
            cur.execute(template)

            template = """
                CREATE TABLE IF NOT EXISTS user2url (
                    id SERIAL PRIMARY KEY NOT NULL,
                    user_id INTEGER NOT NULL,
                    url_id INTEGER NOT NULL,
                    UNIQUE (user_id, url_id)
                )
            """
            self.logger.debug(template)
            cur.execute(template)

            template = """
                CREATE TABLE IF NOT EXISTS urls (
                    url_id SERIAL PRIMARY KEY NOT NULL,
                    url TEXT NOT NULL UNIQUE
                )
            """
            self.logger.debug(template)
            cur.execute(template)

    def add_user(self, student_id: int, user_id: int):
        """Добавление пользователя в базу данных."""
        with self.get_cursor() as cur:
            template = """
                INSERT INTO users (student_id, user_id)
                VALUES (%s, %s)
                ON CONFLICT (student_id, user_id) DO NOTHING
            """
            self.logger.debug(template, student_id, user_id)
            cur.execute(template, (student_id, user_id))

    def update_user(self, student_id: int, user_id: int):
        """Обновление информации о пользователе."""
        with self.get_cursor() as cur:
            template = """
                UPDATE users
                SET student_id = %s
                WHERE user_id = %s
            """
            self.logger.debug(template, student_id, user_id)
            cur.execute(template, (student_id, user_id))

    def add_url(self, url: str, user_id: int):
        """Добавление URL в базу данных."""
        with self.get_cursor() as cur:
            template = """
                INSERT INTO urls (url)
                VALUES (%s)
                ON CONFLICT (url) DO NOTHING
            """
            self.logger.debug(template, url)
            cur.execute(template, (url,))

            template = """
                SELECT url_id FROM urls WHERE url = %s
            """
            self.logger.debug(template, url)
            cur.execute(template, (url,))
            url_id = cur.fetchone()
            if url_id:
                url_id = url_id[0]
                template = """
                    INSERT INTO user2url (user_id, url_id)
                    VALUES (%s, %s)
                    ON CONFLICT (user_id, url_id) DO NOTHING
                """
                self.logger.debug(template, user_id, url_id)
                cur.execute(template, (user_id, url_id))
            return url_id

    def get_user_info(self, user_id: int):
        """Получение информации о пользователе по user_id."""
        with self.get_cursor() as cur:
            template = """
                SELECT student_id, url, url_id FROM users
                JOIN user2url USING (user_id) 
                JOIN urls USING (url_id)
                WHERE user_id = %s
                ORDER BY student_id, url_id
            """
            self.logger.debug(template, user_id)
            cur.execute(template, (user_id,))
            return cur.fetchall()
    
    def delete_url(self, url_id: int, user_id: int):
        """Удаление URL из базы данных."""
        with self.get_cursor() as cur:
            template = """
                DELETE FROM user2url
                WHERE url_id = %s AND user_id = %s
            """
            self.logger.debug(template, url_id, user_id)
            cur.execute(template, (url_id, user_id))

            template = """
                SELECT COUNT(*) FROM user2url WHERE url_id = %s
            """
            self.logger.debug(template, url_id)
            cur.execute(template, (url_id,))
            count = cur.fetchone()[0]
            if count == 0:
                template = """
                    DELETE FROM urls
                    WHERE url_id = %s
                """
                self.logger.debug(template, url_id)
                cur.execute(template, (url_id,))
                return True
        return False

    def get_urls(self):
        """Получение всех URL из базы данных."""
        with self.get_cursor() as cur:
            template = """
                SELECT url_id, url FROM urls
            """
            self.logger.debug(template)
            cur.execute(template)
            return cur.fetchall()
    
    def get_all_users_info(self):
        """Получение информации о всех пользователях."""
        with self.get_cursor() as cur:
            template = """
                SELECT student_id, user_id, url_id FROM users
                JOIN user2url USING (user_id)
                ORDER BY user_id, student_id, url_id
            """
            self.logger.debug(template)
            cur.execute(template)
            return cur.fetchall()
    
    def get_user_urls(self, user_id: int):
        """Получение всех URL для конкретного пользователя."""
        with self.get_cursor() as cur:
            template = """
                SELECT url_id, url FROM user2url
                JOIN urls USING (url_id)
                WHERE user_id = %s
            """
            self.logger.debug(template, user_id)
            cur.execute(template, (user_id,))
            return cur.fetchall()
    
    def get_user_student_ids(self, user_id: int):
        """Получение всех student_id для конкретного пользователя."""
        with self.get_cursor() as cur:
            template = """
                SELECT student_id FROM users
                WHERE user_id = %s
            """
            self.logger.debug(template, user_id)
            cur.execute(template, (user_id,))
            return cur.fetchall()
    
    def delete_student_id(self, student_id: int, user_id: int):
        """Удаление student_id для конкретного пользователя."""
        with self.get_cursor() as cur:
            template = """
                DELETE FROM users
                WHERE student_id = %s AND user_id = %s
            """
            self.logger.debug(template, student_id, user_id)
            cur.execute(template, (student_id, user_id))
