import os
import logging
import json
import contextlib
import psycopg
from psycopg_pool import ConnectionPool, AsyncConnectionPool
from pgvector.psycopg import register_vector, register_vector_async
from typing import Optional, Dict, Any, Tuple, List

# Global connection pools
_pool: Optional[ConnectionPool] = None
_async_pool: Optional[AsyncConnectionPool] = None

def _read_int_env(name: str, default: int, min_value: int = 1) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logging.getLogger("betterresume.db_storage").warning("Invalid %s=%r; using %d", name, raw, default)
        return default
    return max(min_value, value)

def _get_pool_sizes() -> Tuple[int, int, int, int]:
    sync_min = _read_int_env("DB_POOL_MIN_SIZE", 1)
    sync_max = _read_int_env("DB_POOL_MAX_SIZE", 5)
    async_min = _read_int_env("ASYNC_DB_POOL_MIN_SIZE", sync_min)
    async_max = _read_int_env("ASYNC_DB_POOL_MAX_SIZE", sync_max)

    if sync_min > sync_max:
        sync_min = sync_max
    if async_min > async_max:
        async_min = async_max
    return sync_min, sync_max, async_min, async_max

def _configure_sync(conn):
    try:
        register_vector(conn)
    except Exception as e:
         logging.getLogger("betterresume.db_storage").warning("Failed to register vector in sync pool (maybe extension missing?): %s", e)

async def _configure_async(conn):
    try:
        await register_vector_async(conn)
    except Exception as e:
         logging.getLogger("betterresume.db_storage").warning("Failed to register vector in async pool (maybe extension missing?): %s", e)

def init_db_pool(db_url: Optional[str] = None):
    """Initialize the global database connection pool."""
    global _pool
    if _pool is not None:
        return

    url = db_url or os.getenv("DATABASE_URL")
    if url and url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://")
    
    if not url:
        logging.getLogger("betterresume.db_storage").warning("No DATABASE_URL found, skipping pool initialization")
        return

    sync_min, sync_max, _, _ = _get_pool_sizes()
    logging.getLogger("betterresume.db_storage").info(
        "Initializing sync DB pool min=%d max=%d",
        sync_min,
        sync_max,
    )

    # Initialize pool with conservative defaults to avoid exhausting Postgres connections
    _pool = ConnectionPool(
        conninfo=url,
        min_size=sync_min,
        max_size=sync_max,
        kwargs={"autocommit": True},
        configure=_configure_sync,
    )
    logging.getLogger("betterresume.db_storage").info("Database connection pool initialized")

async def init_async_db_pool(db_url: Optional[str] = None):
    """Initialize the global async database connection pool."""
    global _async_pool
    if _async_pool is not None:
        return

    url = db_url or os.getenv("DATABASE_URL")
    if url and url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://")
    
    if not url:
        logging.getLogger("betterresume.db_storage").warning("No DATABASE_URL found, skipping async pool initialization")
        return

    _, _, async_min, async_max = _get_pool_sizes()
    logging.getLogger("betterresume.db_storage").info(
        "Initializing async DB pool min=%d max=%d",
        async_min,
        async_max,
    )

    _async_pool = AsyncConnectionPool(
        conninfo=url,
        min_size=async_min,
        max_size=async_max,
        kwargs={"autocommit": True},
        configure=_configure_async,
    )
    logging.getLogger("betterresume.db_storage").info("Async database connection pool initialized")

def close_db_pool():
    """Close the global database connection pool."""
    global _pool
    if _pool:
        _pool.close()
        _pool = None
        logging.getLogger("betterresume.db_storage").info("Database connection pool closed")

async def close_async_db_pool():
    """Close the global async database connection pool."""
    global _async_pool
    if _async_pool:
        await _async_pool.close()
        _async_pool = None
        logging.getLogger("betterresume.db_storage").info("Async database connection pool closed")

def get_async_pool() -> Optional[AsyncConnectionPool]:
    return _async_pool

class DBStorage:
    """
    Utility class to manage file and cache storage in Postgres.
    """
    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or os.getenv("DATABASE_URL")
        if self.db_url and self.db_url.startswith("postgresql+asyncpg://"):
            self.db_url = self.db_url.replace("postgresql+asyncpg://", "postgresql://")
        self.logger = logging.getLogger("betterresume.db_storage")

    @contextlib.contextmanager
    def _get_conn(self):
        """
        Returns a context manager that yields a connection.
        Uses the global pool if available and matching configuration,
        otherwise creates a dedicated connection (and logs a warning if appropriate).
        """
        global _pool
        
        if _pool is None:
             init_db_pool(self.db_url)
        
        # Check if we can use the global pool
        # We assume if self.db_url matches the one used for init_db_pool (implicitly), we use the pool.
        # Since we don't store the pool's URL, we'll assume if _pool exists, it's the right one 
        # for standard app usage.
        if _pool:
            self.logger.debug("Using pooled DB connection")
            with _pool.connection() as conn:
                yield conn
            return

        # Fallback to creating a new connection
        self.logger.warning("Creating new connection (no pool available)")
        conn = psycopg.connect(self.db_url, autocommit=True)
        try:
            yield conn
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def init_schema(self):
        """Initialize database schema if not exists."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    # Create extension
                    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                    
                    # Create users table first as others depend on it
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS users (
                          user_id TEXT PRIMARY KEY,
                          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                    
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS resume_vectors (
                          id TEXT PRIMARY KEY,
                          user_id TEXT NOT NULL,
                          content TEXT,
                          embedding vector(768)
                        );
                    """)
                    
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_resume_vectors_embedding
                        ON resume_vectors USING ivfflat (embedding) WITH (lists = 100);
                    """)
                    
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS resume_requests (
                          id BIGSERIAL PRIMARY KEY,
                          user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                          job_posting TEXT NOT NULL,
                          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                    
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS job_experiences (
                          id BIGSERIAL PRIMARY KEY,
                          user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                          company TEXT NOT NULL,
                          description TEXT NOT NULL,
                          type TEXT NOT NULL,
                          role TEXT,
                          location TEXT,
                          start_date TEXT,
                          end_date TEXT,
                          raw JSONB,
                          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                    
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS user_files (
                            user_id TEXT NOT NULL,
                            file_type TEXT NOT NULL,
                            filename TEXT NOT NULL,
                            content BYTEA,
                            mime_type TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            PRIMARY KEY (user_id, file_type)
                        );
                    """)
                    
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS resume_generation_cache (
                            user_id TEXT NOT NULL,
                            cache_key TEXT NOT NULL,
                            data JSONB NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            PRIMARY KEY (user_id, cache_key)
                        );
                    """)
                    self.logger.info("Database schema initialized successfully")
        except Exception as e:
            self.logger.error("Failed to initialize database schema: %s", e)
            # Don't raise here, let the app try to run, maybe tables exist but something else failed

    def _ensure_user(self, user_id: str):
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO users (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING",
                        (user_id,),
                    )
        except Exception as e:
            self.logger.exception("Failed to ensure user exists: %s", e)
            raise

    def save_file(self, user_id: str, file_type: str, content: bytes, filename: str, mime_type: Optional[str] = None):
        """Upsert a file for a user."""
        try:
            self._ensure_user(user_id)
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
            self._ensure_user(user_id)
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

    def replace_job_experiences(self, user_id: str, records: List[Dict[str, Any]]):
        """Replace all job experience rows for a user with provided records."""
        try:
            self._ensure_user(user_id)
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM job_experiences WHERE user_id = %s", (user_id,))
                    for rec in records:
                        cur.execute(
                            """
                            INSERT INTO job_experiences (
                                user_id, company, description, type, role, location, start_date, end_date, raw
                            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            """,
                            (
                                user_id,
                                rec.get("company", ""),
                                rec.get("description", ""),
                                rec.get("type", ""),
                                rec.get("role"),
                                rec.get("location"),
                                rec.get("start_date"),
                                rec.get("end_date"),
                                json.dumps(rec),
                            ),
                        )
            self.logger.info("Replaced %d job experience rows for user=%s", len(records), user_id)
        except Exception as e:
            self.logger.exception("Failed to replace job experiences: %s", e)
            raise

    def get_job_experiences(self, user_id: str, type_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve job experiences, optionally filtered by type."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    query = "SELECT raw FROM job_experiences WHERE user_id = %s"
                    params = [user_id]
                    if type_filter:
                        query += " AND LOWER(TRIM(type)) = LOWER(TRIM(%s))"
                        params.append(type_filter)
                    
                    cur.execute(query, params)
                    rows = cur.fetchall()
                    return [row[0] if isinstance(row[0], dict) else json.loads(row[0]) for row in rows]
        except Exception as e:
            self.logger.exception("Failed to get job experiences: %s", e)
            return []

    def insert_resume_request(self, user_id: str, job_posting: str):
        """Insert a resume request row."""
        try:
            self._ensure_user(user_id)
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO resume_requests (user_id, job_posting) VALUES (%s, %s)",
                        (user_id, job_posting),
                    )
        except Exception as e:
            self.logger.exception("Failed to insert resume request: %s", e)
            raise

    def _ensure_donations_table(self):
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS donations (
                            id BIGSERIAL PRIMARY KEY,
                            user_id TEXT,
                            amount INTEGER NOT NULL,
                            currency TEXT NOT NULL,
                            reason TEXT NOT NULL,
                            stripe_session_id TEXT UNIQUE,
                            status TEXT DEFAULT 'completed',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
        except Exception as e:
            self.logger.exception("Failed to ensure donations table: %s", e)

    def record_donation(self, user_id: Optional[str], amount: int, currency: str, reason: str, stripe_session_id: str, status: str = 'completed'):
        try:
            self._ensure_donations_table()
            if user_id:
                self._ensure_user(user_id)
            
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO donations (user_id, amount, currency, reason, stripe_session_id, status)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (stripe_session_id) DO NOTHING
                        """,
                        (user_id, amount, currency, reason, stripe_session_id, status)
                    )
            self.logger.info("Recorded donation: user=%s amount=%d %s reason=%s", user_id, amount, currency, reason)
        except Exception as e:
            self.logger.exception("Failed to record donation: %s", e)

    def get_job_success_count(self) -> int:
        try:
            self._ensure_donations_table()
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM donations WHERE reason = 'job' AND status = 'completed'")
                    row = cur.fetchone()
                    return row[0] if row else 0
        except Exception as e:
            self.logger.exception("Failed to get job success count: %s", e)
            return 0
