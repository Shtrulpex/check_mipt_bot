from contextlib import contextmanager

from psycopg2 import pool


class DatabaseWorker:
    def __init__(self):
        """Инициализация соединения с базой данных."""
        self.pool = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dbname="check_mipt_bot_db",
            user="bot_user",
            password="qwerty",
            host="localhost",  # TODO: заменить переменные
            port="5432"
        )
        self._create_tables()
    
    @contextmanager
    def get_cursor(self):
        conn = self.pool.getconn()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        finally:
            cursor.close()
            self.pool.putconn(conn)
    
    def _create_tables(self):
        """Создание таблицы users, если она не существует."""
        with self.get_cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY NOT NULL,
                    student_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    UNIQUE (student_id, user_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user2url (
                    id SERIAL PRIMARY KEY NOT NULL,
                    user_id INTEGER NOT NULL,
                    url_id INTEGER NOT NULL,
                    UNIQUE (user_id, url_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS urls (
                    url_id SERIAL PRIMARY KEY NOT NULL,
                    url TEXT NOT NULL UNIQUE
                )
            """)

    def add_user(self, student_id: int, user_id: int):
        """Добавление пользователя в базу данных."""
        with self.get_cursor() as cur:
            cur.execute("""
                INSERT INTO users (student_id, user_id)
                VALUES (%s, %s)
                ON CONFLICT (student_id, user_id) DO NOTHING
            """, (student_id, user_id))  # TODO: добавить возможность одному user_id иметь несколько student_id

    def update_user(self, student_id: int, user_id: int):
        """Обновление информации о пользователе."""
        with self.get_cursor() as cur:
            cur.execute("""
                UPDATE users
                SET student_id = %s
                WHERE user_id = %s
            """, (student_id, user_id))

    def add_url(self, url: str, user_id: int):
        """Добавление URL в базу данных."""
        with self.get_cursor() as cur:
            cur.execute("""
                INSERT INTO urls (url)
                VALUES (%s)
                ON CONFLICT (url) DO NOTHING
            """, (url,))

            cur.execute("""
                SELECT url_id FROM urls WHERE url = %s
            """, (url,))
            url_id = cur.fetchone()
            if url_id:
                url_id = url_id[0]
                cur.execute("""
                    INSERT INTO user2url (user_id, url_id)
                    VALUES (%s, %s)
                    ON CONFLICT (user_id, url_id) DO NOTHING
                """, (user_id, url_id))
            return url_id

    def get_user_info(self, user_id: int):
        """Получение информации о пользователе по user_id."""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT student_id, url, url_id FROM users
                JOIN user2url USING (user_id) 
                JOIN urls USING (url_id)
                WHERE user_id = %s
            """, (user_id,))
            return cur.fetchall()
    
    def delete_url(self, url_id: int, user_id: int):
        """Удаление URL из базы данных."""
        with self.get_cursor() as cur:
            cur.execute("""
                DELETE FROM user2url
                WHERE url_id = %s AND user_id = %s
            """, (url_id, user_id))

            cur.execute("""
                SELECT COUNT(*) FROM user2url WHERE url_id = %s
            """, (url_id,))
            count = cur.fetchone()[0]
            if count == 0:
                cur.execute("""
                    DELETE FROM urls
                    WHERE url_id = %s
                """, (url_id,))
                return True
        return False

    def get_urls(self):
        """Получение всех URL из базы данных."""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT url_id, url FROM urls
            """)
            return cur.fetchall()
    
    def get_all_users_info(self):
        """Получение информации о всех пользователях."""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT student_id, user_id, url_id FROM users
                JOIN user2url USING (user_id)
            """)
            return cur.fetchall()
    
    def get_user_urls(self, user_id: int):
        """Получение всех URL для конкретного пользователя."""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT url_id, url FROM user2url
                JOIN urls USING (url_id)
                WHERE user_id = %s
            """, (user_id,))
            return cur.fetchall()
    
    def get_user_student_ids(self, user_id: int):
        """Получение всех student_id для конкретного пользователя."""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT student_id FROM users
                WHERE user_id = %s
            """, (user_id,))
            return cur.fetchall()
    
    def delete_student_id(self, student_id: int, user_id: int):
        """Удаление student_id для конкретного пользователя."""
        with self.get_cursor() as cur:
            cur.execute("""
                DELETE FROM users
                WHERE student_id = %s AND user_id = %s
            """, (student_id, user_id))

DB_worker_unit = DatabaseWorker()
