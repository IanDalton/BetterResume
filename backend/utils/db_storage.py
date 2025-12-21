import os
import logging
import json
import psycopg
from typing import Optional, Dict, Any, Tuple

class DBStorage:
    """
    Utility class to manage file and cache storage in Postgres.
    """
    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or os.getenv("DATABASE_URL")
        if self.db_url and self.db_url.startswith("postgresql+asyncpg://"):
            self.db_url = self.db_url.replace("postgresql+asyncpg://", "postgresql://")
        self.logger = logging.getLogger("betterresume.db_storage")

    def _get_conn(self):
        return psycopg.connect(self.db_url, autocommit=True)

    def save_file(self, user_id: str, file_type: str, content: bytes, filename: str, mime_type: Optional[str] = None):
        """Upsert a file for a user."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO user_files (user_id, file_type, filename, content, mime_type, updated_at)
                        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT (user_id, file_type) 
                        DO UPDATE SET 
                            filename = EXCLUDED.filename,
                            content = EXCLUDED.content,
                            mime_type = EXCLUDED.mime_type,
                            updated_at = CURRENT_TIMESTAMP;
                        """,
                        (user_id, file_type, filename, content, mime_type)
                    )
            self.logger.info("Saved file user=%s type=%s name=%s size=%d", user_id, file_type, filename, len(content))
        except Exception as e:
            self.logger.exception("Failed to save file: %s", e)
            raise

    def get_file(self, user_id: str, file_type: str) -> Optional[Tuple[bytes, str, str]]:
        """Retrieve a file. Returns (content, filename, mime_type) or None."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT content, filename, mime_type FROM user_files WHERE user_id = %s AND file_type = %s",
                        (user_id, file_type)
                    )
                    row = cur.fetchone()
                    if row:
                        return (row[0], row[1], row[2])
            return None
        except Exception as e:
            self.logger.exception("Failed to get file: %s", e)
            return None

    def delete_file(self, user_id: str, file_type: str):
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM user_files WHERE user_id = %s AND file_type = %s", (user_id, file_type))
        except Exception as e:
            self.logger.exception("Failed to delete file: %s", e)

    def save_cache(self, user_id: str, cache_key: str, data: Dict[str, Any]):
        """Upsert cache entry."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO resume_generation_cache (user_id, cache_key, data, created_at)
                        VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT (user_id, cache_key)
                        DO UPDATE SET data = EXCLUDED.data, created_at = CURRENT_TIMESTAMP;
                        """,
                        (user_id, cache_key, json.dumps(data))
                    )
        except Exception as e:
            self.logger.exception("Failed to save cache: %s", e)

    def get_cache(self, user_id: str, cache_key: str) -> Optional[Dict[str, Any]]:
        """Retrieve cache entry."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT data FROM resume_generation_cache WHERE user_id = %s AND cache_key = %s",
                        (user_id, cache_key)
                    )
                    row = cur.fetchone()
                    if row:
                        return row[0] if isinstance(row[0], dict) else json.loads(row[0])
            return None
        except Exception as e:
            self.logger.exception("Failed to get cache: %s", e)
            return None

    def clear_user_data(self, user_id: str):
        """Delete all files and cache for a user."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM user_files WHERE user_id = %s", (user_id,))
                    cur.execute("DELETE FROM resume_generation_cache WHERE user_id = %s", (user_id,))
        except Exception as e:
            self.logger.exception("Failed to clear user data: %s", e)
