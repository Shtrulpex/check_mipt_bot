from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import logging
import os

from psycopg2 import Error as Psycopg2Error
from psycopg2 import pool


@dataclass(frozen=True)
class Source:
    id: int
    url: str
    provider: str
    title: str | None = None


@dataclass(frozen=True)
class Tracking:
    id: int
    user_id: int
    source_id: int
    applicant_id: str
    url: str
    provider: str
    title: str | None = None


class DatabaseWorker:
    """Persistence for exact (source, applicant id) tracking pairs."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.pool = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT"),
        )
        self._create_tables()

    @contextmanager
    def get_cursor(self):
        conn = self.pool.getconn()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Psycopg2Error as exc:
            conn.rollback()
            self.logger.error("SQL query execution error: %s", exc.pgerror)
            raise
        except Exception:
            conn.rollback()
            self.logger.exception("Database operation failed")
            raise
        finally:
            cursor.close()
            self.pool.putconn(conn)

    def _create_tables(self) -> None:
        with self.get_cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    id SERIAL PRIMARY KEY,
                    url TEXT NOT NULL UNIQUE,
                    provider TEXT NOT NULL,
                    title TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS trackings (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    applicant_id TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (user_id, source_id, applicant_id)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS trackings_user_id_idx ON trackings(user_id)")

    def add_tracking(
        self, url: str, provider: str, applicant_id: str, user_id: int
    ) -> tuple[int, int]:
        with self.get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO sources (url, provider)
                VALUES (%s, %s)
                ON CONFLICT (url) DO UPDATE SET provider = EXCLUDED.provider
                RETURNING id
                """,
                (url, provider),
            )
            source_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO trackings (user_id, source_id, applicant_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, source_id, applicant_id)
                DO UPDATE SET applicant_id = EXCLUDED.applicant_id
                RETURNING id
                """,
                (user_id, source_id, applicant_id),
            )
            return cur.fetchone()[0], source_id

    def update_source_title(self, source_id: int, title: str) -> None:
        with self.get_cursor() as cur:
            cur.execute("UPDATE sources SET title = %s WHERE id = %s", (title, source_id))

    def get_sources(self) -> list[Source]:
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT s.id, s.url, s.provider, s.title
                FROM sources s
                JOIN trackings t ON t.source_id = s.id
                ORDER BY s.id
                """
            )
            return [Source(*row) for row in cur.fetchall()]

    def get_all_trackings(self) -> list[Tracking]:
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT t.id, t.user_id, t.source_id, t.applicant_id,
                       s.url, s.provider, s.title
                FROM trackings t
                JOIN sources s ON s.id = t.source_id
                ORDER BY t.user_id, t.id
                """
            )
            return [Tracking(*row) for row in cur.fetchall()]

    def get_user_trackings(self, user_id: int) -> list[Tracking]:
        with self.get_cursor() as cur:
            cur.execute(
                """
                SELECT t.id, t.user_id, t.source_id, t.applicant_id,
                       s.url, s.provider, s.title
                FROM trackings t
                JOIN sources s ON s.id = t.source_id
                WHERE t.user_id = %s
                ORDER BY t.id
                """,
                (user_id,),
            )
            return [Tracking(*row) for row in cur.fetchall()]

    def delete_tracking(self, tracking_id: int, user_id: int) -> int | None:
        """Delete one user's tracking and return a now-unused source id, if any."""
        with self.get_cursor() as cur:
            cur.execute(
                "DELETE FROM trackings WHERE id = %s AND user_id = %s RETURNING source_id",
                (tracking_id, user_id),
            )
            deleted = cur.fetchone()
            if not deleted:
                return None
            source_id = deleted[0]
            cur.execute("SELECT 1 FROM trackings WHERE source_id = %s LIMIT 1", (source_id,))
            if cur.fetchone() is not None:
                return None
            cur.execute("DELETE FROM sources WHERE id = %s", (source_id,))
            return source_id
