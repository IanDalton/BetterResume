import os
import logging
import json
import contextlib
import math
import re
from collections import Counter
import psycopg
from psycopg.adapt import Loader
from psycopg.types.json import Json
from psycopg_pool import ConnectionPool, AsyncConnectionPool
from pgvector.psycopg import register_vector, register_vector_async
from typing import Optional, Dict, Any, Tuple, List


class _RawBytesLoader(Loader):
    """Return text columns as raw bytes instead of decoding them.

    Some rows hold bytes that aren't valid UTF-8 (a SQL_ASCII client_encoding
    used at insert time let non-UTF8 bytes — e.g. Windows-1252 smart quotes /
    em-dashes pasted into job postings — land in the column without validation).
    Any server-side text function or encoding conversion over such a value
    raises CharacterNotInRepertoire. Loading the raw bytes and decoding them in
    Python with errors='replace' sidesteps that entirely.
    """

    def load(self, data):
        return bytes(data) if data is not None else None


def _decode_loose(value: Any) -> Optional[str]:
    """Decode a value that may arrive as raw bytes (see _RawBytesLoader)."""
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", "replace")
    return str(value)


# Stopwords for job-posting keyword mining. Usage skews English + Spanish
# (Argentina), so we strip the most common words of both languages plus a few
# generic recruiting boilerplate terms that would otherwise dominate.
_KEYWORD_STOPWORDS = frozenset(
    # English
    "the and for you with our are will that have this from your has not but all "
    "can who out who's they them their what when where which while about into over "
    "more most some such than then they these those been being were was being "
    "able role work team join looking experience years job position company within "
    "must should would could able also like able per via etc inc ltd new use using "
    # Spanish
    "que con los las del una uno por para como mas más pero sus sí son está están "
    "este esta estos estas entre sobre desde hasta cuando donde porque muy ser eres "
    "tener tiene tienes trabajo empresa puesto experiencia años buscamos buscando "
    "nuestra nuestro nuestros además también equipo perfil tareas funciones área "
    "conocimientos requisitos ofrecemos zona horario remoto modalidad proyecto "
    "personal salud cliente clientes servicio".split()
)


def _top_job_keywords(conn, days: int, limit: int = 25) -> List[Dict[str, Any]]:
    """Top keywords across recent job postings (bounded, UTF-8-tolerant).

    Reads ``job_posting`` with the same raw-bytes / SQL_ASCII passthrough used
    for the recent-requests preview (postings may contain invalid UTF-8), then
    tokenizes and counts in Python. The scan is bounded so a busy window can't
    pull unbounded text. Returns ``[]`` on any error so it never 500s the
    dashboard.
    """
    with conn.cursor() as raw_cur:
        raw_cur.adapters.register_loader("text", _RawBytesLoader)
        raw_cur.adapters.register_loader("varchar", _RawBytesLoader)
        raw_cur.execute("SET client_encoding TO 'SQL_ASCII'")
        try:
            raw_cur.execute(
                """
                SELECT job_posting
                FROM resume_requests
                WHERE created_at >= CURRENT_DATE - %s::int
                ORDER BY created_at DESC LIMIT 3000
                """,
                (days,),
            )
            rows = raw_cur.fetchall()
        finally:
            raw_cur.execute("RESET client_encoding")

    counter: Counter = Counter()
    for (raw,) in rows:
        text = (_decode_loose(raw) or "").lower()
        for token in re.findall(r"[^\W\d_]{3,}", text, flags=re.UNICODE):
            if token not in _KEYWORD_STOPWORDS:
                counter[token] += 1
    return [{"term": term, "count": count} for term, count in counter.most_common(limit)]

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

def _sanitize_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_json_value(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_sanitize_json_value(val) for val in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value

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
        open=False,
    )
    await _async_pool.open()
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

                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS generation_events (
                            id BIGSERIAL PRIMARY KEY,
                            user_id TEXT NOT NULL,
                            model TEXT,
                            format TEXT,
                            language TEXT,
                            duration_ms INTEGER,
                            status TEXT NOT NULL DEFAULT 'success',
                            error TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                    cur.execute("ALTER TABLE generation_events ADD COLUMN IF NOT EXISTS requested_model TEXT;")
                    cur.execute("ALTER TABLE generation_events ADD COLUMN IF NOT EXISTS fallback_used BOOLEAN NOT NULL DEFAULT FALSE;")

                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS app_settings (
                            key         TEXT PRIMARY KEY,
                            value       JSONB NOT NULL,
                            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_by  TEXT
                        );
                    """)

                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS eval_runs (
                            id           UUID PRIMARY KEY,
                            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            finished_at  TIMESTAMPTZ,
                            created_by   TEXT NOT NULL,
                            status       TEXT NOT NULL,
                            data_source  TEXT NOT NULL,
                            judge_model  TEXT,
                            models       JSONB NOT NULL,
                            jd_ids       JSONB NOT NULL,
                            custom_jd    TEXT,
                            notes        TEXT
                        );
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS eval_results (
                            id                UUID PRIMARY KEY,
                            run_id            UUID NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
                            model             TEXT NOT NULL,
                            jd_id             TEXT NOT NULL,
                            status            TEXT NOT NULL,
                            error             TEXT,
                            duration_ms       INTEGER,
                            input_tokens      INTEGER,
                            output_tokens     INTEGER,
                            fallback_used     BOOLEAN NOT NULL DEFAULT FALSE,
                            schema_score      REAL,
                            schema_passed     BOOLEAN,
                            schema_errors     JSONB,
                            ats_score         REAL,
                            ats_coverage      REAL,
                            missing_keywords  JSONB,
                            judge_overall     REAL,
                            judge_relevance   REAL,
                            judge_quality     REAL,
                            judge_coherence   REAL,
                            judge_reasoning   TEXT,
                            composite_score   REAL,
                            resume_json       JSONB,
                            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        );
                    """)
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_eval_results_run ON eval_results(run_id);")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_eval_results_model ON eval_results(model);")

                    cur.execute("ALTER TABLE job_experiences ADD COLUMN IF NOT EXISTS migrated_at TIMESTAMP;")

                    # Matches get_unmigrated_legacy_rows' predicate so the
                    # every-boot backfill check is an index lookup instead of a
                    # full table scan (the index is near-empty once migrated).
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_job_experiences_legacy_unmigrated
                        ON job_experiences (id)
                        WHERE LOWER(TRIM(type)) IN ('info', 'language') AND migrated_at IS NULL;
                    """)

                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS user_profile (
                          user_id TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                          full_name TEXT,
                          email TEXT,
                          phone TEXT,
                          address TEXT,
                          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)

                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS user_profile_links (
                          id BIGSERIAL PRIMARY KEY,
                          user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                          kind TEXT NOT NULL,
                          label TEXT,
                          url TEXT NOT NULL,
                          sort_order INTEGER DEFAULT 0,
                          source_job_experience_id BIGINT UNIQUE,
                          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)

                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS user_languages (
                          id BIGSERIAL PRIMARY KEY,
                          user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                          name TEXT NOT NULL,
                          proficiency TEXT,
                          sort_order INTEGER DEFAULT 0,
                          source_job_experience_id BIGINT UNIQUE,
                          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                        clean_rec = _sanitize_json_value(rec) if isinstance(rec, dict) else rec
                        cur.execute(
                            """
                            INSERT INTO job_experiences (
                                user_id, company, description, type, role, location, start_date, end_date, raw
                            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            """,
                            (
                                user_id,
                                clean_rec.get("company", ""),
                                clean_rec.get("description", ""),
                                clean_rec.get("type", ""),
                                clean_rec.get("role"),
                                clean_rec.get("location"),
                                clean_rec.get("start_date"),
                                clean_rec.get("end_date"),
                                json.dumps(clean_rec, allow_nan=False),
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

    def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve the dedicated profile row for a user, or None if never set."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT full_name, email, phone, address FROM user_profile WHERE user_id = %s",
                        (user_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        return None
                    return {"full_name": row[0], "email": row[1], "phone": row[2], "address": row[3]}
        except Exception as e:
            self.logger.exception("Failed to get user profile: %s", e)
            return None

    def upsert_user_profile(self, user_id: str, full_name: Optional[str], email: Optional[str],
                             phone: Optional[str], address: Optional[str]):
        """Insert or update the dedicated profile row for a user."""
        try:
            self._ensure_user(user_id)
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO user_profile (user_id, full_name, email, phone, address, updated_at)
                        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT (user_id)
                        DO UPDATE SET full_name = EXCLUDED.full_name, email = EXCLUDED.email,
                                      phone = EXCLUDED.phone, address = EXCLUDED.address,
                                      updated_at = CURRENT_TIMESTAMP;
                        """,
                        (user_id, full_name, email, phone, address),
                    )
        except Exception as e:
            self.logger.exception("Failed to upsert user profile: %s", e)
            raise

    def list_profile_links(self, user_id: str) -> List[Dict[str, Any]]:
        """Retrieve a user's profile links (portfolio/github/linkedin/etc.), in order."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT kind, label, url FROM user_profile_links
                        WHERE user_id = %s ORDER BY sort_order, id
                        """,
                        (user_id,),
                    )
                    return [{"kind": r[0], "label": r[1], "url": r[2]} for r in cur.fetchall()]
        except Exception as e:
            self.logger.exception("Failed to list profile links: %s", e)
            return []

    def replace_profile_links(self, user_id: str, links: List[Dict[str, Any]]):
        """Replace all profile links for a user with the provided list."""
        try:
            self._ensure_user(user_id)
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM user_profile_links WHERE user_id = %s", (user_id,))
                    for i, link in enumerate(links):
                        cur.execute(
                            """
                            INSERT INTO user_profile_links (user_id, kind, label, url, sort_order)
                            VALUES (%s, %s, %s, %s, %s)
                            """,
                            (user_id, link.get("kind", "other"), link.get("label"), link.get("url", ""), i),
                        )
            self.logger.info("Replaced %d profile links for user=%s", len(links), user_id)
        except Exception as e:
            self.logger.exception("Failed to replace profile links: %s", e)
            raise

    def get_user_languages(self, user_id: str) -> List[Dict[str, Any]]:
        """Retrieve a user's languages, in order."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT name, proficiency FROM user_languages
                        WHERE user_id = %s ORDER BY sort_order, id
                        """,
                        (user_id,),
                    )
                    return [{"name": r[0], "proficiency": r[1]} for r in cur.fetchall()]
        except Exception as e:
            self.logger.exception("Failed to get user languages: %s", e)
            return []

    def replace_user_languages(self, user_id: str, languages: List[Dict[str, Any]]):
        """Replace all languages for a user with the provided list."""
        try:
            self._ensure_user(user_id)
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM user_languages WHERE user_id = %s", (user_id,))
                    for i, lang in enumerate(languages):
                        cur.execute(
                            """
                            INSERT INTO user_languages (user_id, name, proficiency, sort_order)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (user_id, lang.get("name", ""), lang.get("proficiency"), i),
                        )
            self.logger.info("Replaced %d languages for user=%s", len(languages), user_id)
        except Exception as e:
            self.logger.exception("Failed to replace user languages: %s", e)
            raise

    def upsert_profile_field_from_legacy(self, user_id: str, field: str, value: str):
        """Set a single profile column, used by the legacy backfill (one field per legacy row)."""
        assert field in ("full_name", "email", "phone", "address")
        # No _ensure_user: the user_id comes from a job_experiences row, whose
        # FK already guarantees the user exists (same for the other
        # *_from_legacy helpers below).
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO user_profile (user_id, {field}, updated_at)
                        VALUES (%s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT (user_id)
                        DO UPDATE SET {field} = EXCLUDED.{field}, updated_at = CURRENT_TIMESTAMP;
                        """,
                        (user_id, value),
                    )
        except Exception as e:
            self.logger.exception("Failed to upsert profile field %s for user=%s: %s", field, user_id, e)
            raise

    def insert_profile_link_from_legacy(self, user_id: str, kind: str, label: Optional[str], url: str,
                                         source_job_experience_id: int, sort_order: int = 0):
        """Insert a profile link tied to its legacy source row; a no-op if already migrated."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO user_profile_links (user_id, kind, label, url, sort_order, source_job_experience_id)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (source_job_experience_id) DO NOTHING;
                        """,
                        (user_id, kind, label, url, sort_order, source_job_experience_id),
                    )
        except Exception as e:
            self.logger.exception("Failed to insert legacy profile link for user=%s: %s", user_id, e)
            raise

    def insert_language_from_legacy(self, user_id: str, name: str, proficiency: Optional[str],
                                     source_job_experience_id: int, sort_order: int = 0):
        """Insert a language tied to its legacy source row; a no-op if already migrated."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO user_languages (user_id, name, proficiency, sort_order, source_job_experience_id)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (source_job_experience_id) DO NOTHING;
                        """,
                        (user_id, name, proficiency, sort_order, source_job_experience_id),
                    )
        except Exception as e:
            self.logger.exception("Failed to insert legacy language for user=%s: %s", user_id, e)
            raise

    def get_unmigrated_legacy_rows(self, limit: int = 1000) -> List[Dict[str, Any]]:
        """Fetch legacy type='info'/'language' job_experiences rows not yet backfilled.

        Never deletes source rows; callers mark them migrated once copied so
        this can be safely rerun without double-processing.
        """
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, user_id, type, company, description, role, raw
                        FROM job_experiences
                        WHERE LOWER(TRIM(type)) IN ('info', 'language') AND migrated_at IS NULL
                        ORDER BY id
                        LIMIT %s
                        """,
                        (limit,),
                    )
                    rows = cur.fetchall()
                    return [
                        {
                            "id": r[0],
                            "user_id": r[1],
                            "type": r[2],
                            "company": r[3],
                            "description": r[4],
                            "role": r[5],
                            "raw": r[6] if isinstance(r[6], dict) else (json.loads(r[6]) if r[6] else {}),
                        }
                        for r in rows
                    ]
        except Exception as e:
            self.logger.exception("Failed to fetch unmigrated legacy rows: %s", e)
            return []

    def mark_job_experience_migrated(self, row_id: int):
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE job_experiences SET migrated_at = CURRENT_TIMESTAMP WHERE id = %s",
                        (row_id,),
                    )
        except Exception as e:
            self.logger.exception("Failed to mark job_experience %s migrated: %s", row_id, e)
            raise

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

    def record_generation_event(
        self,
        user_id: str,
        model: Optional[str] = None,
        format: Optional[str] = None,
        language: Optional[str] = None,
        duration_ms: Optional[int] = None,
        status: str = "success",
        error: Optional[str] = None,
        requested_model: Optional[str] = None,
        fallback_used: bool = False,
    ):
        """Insert a resume generation event row (used by the admin dashboard)."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO generation_events
                            (user_id, model, requested_model, format, language, duration_ms, status, error, fallback_used)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (user_id, model, requested_model, format, language, duration_ms, status,
                         (error or None) and str(error)[:2000], bool(fallback_used)),
                    )
            self.logger.info(
                "Recorded generation event user=%s status=%s duration_ms=%s", user_id, status, duration_ms
            )
        except Exception as e:
            self.logger.exception("Failed to record generation event: %s", e)
            raise

    # ------------------------------------------------------------------
    # Application settings (key/value, used for runtime model configuration)
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_json(value):
        """psycopg returns jsonb as a dict when the adapter is registered and a
        str otherwise; normalize both to a dict."""
        if value is None or isinstance(value, dict):
            return value
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return None

    def get_app_setting(self, key: str) -> Optional[Dict[str, Any]]:
        """Return the stored JSON value for `key`, or None if unset."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM app_settings WHERE key = %s", (key,))
                row = cur.fetchone()
        return self._coerce_json(row[0]) if row else None

    def set_app_setting(self, key: str, value: Dict[str, Any], updated_by: Optional[str] = None) -> None:
        """Upsert a settings row."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO app_settings (key, value, updated_by, updated_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value,
                        updated_by = EXCLUDED.updated_by,
                        updated_at = NOW()
                    """,
                    (key, Json(value), updated_by),
                )
        self.logger.info("app_setting %s updated by %s", key, updated_by)

    def get_app_settings_meta(self, prefix: str = "") -> Dict[str, Dict[str, Any]]:
        """Return {key: {value, updated_at, updated_by}} for keys starting with `prefix`."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT key, value, updated_at, updated_by FROM app_settings WHERE key LIKE %s ORDER BY key",
                    (f"{prefix}%",),
                )
                rows = cur.fetchall()
        return {
            r[0]: {
                "value": self._coerce_json(r[1]),
                "updated_at": r[2].isoformat() if r[2] else None,
                "updated_by": r[3],
            }
            for r in rows
        }

    # ------------------------------------------------------------------
    # Eval runs (model-evaluation dashboard: run/result persistence)
    # ------------------------------------------------------------------

    _EVAL_RESULT_COLUMNS = (
        "id", "run_id", "model", "jd_id", "status", "error", "duration_ms",
        "input_tokens", "output_tokens", "fallback_used", "schema_score",
        "schema_passed", "schema_errors", "ats_score", "ats_coverage",
        "missing_keywords", "judge_overall", "judge_relevance", "judge_quality",
        "judge_coherence", "judge_reasoning", "composite_score", "resume_json",
        "created_at",
    )

    _EVAL_RUN_COLUMNS = (
        "id", "created_at", "finished_at", "created_by", "status",
        "data_source", "judge_model", "models", "jd_ids", "custom_jd", "notes",
    )

    def _row_to_dict(self, columns, row):
        out = {}
        for name, value in zip(columns, row):
            if name in ("schema_errors", "missing_keywords", "resume_json", "models", "jd_ids"):
                value = self._coerce_json(value) if not isinstance(value, list) else value
            elif name in ("created_at", "finished_at") and value is not None:
                value = value.isoformat()
            elif name in ("id", "run_id") and value is not None:
                value = str(value)
            out[name] = value
        return out

    def create_eval_run(self, run_id: str, created_by: str, data_source: str,
                        judge_model: Optional[str], models: list, jd_ids: list,
                        custom_jd: Optional[str], notes: Optional[str]) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO eval_runs
                        (id, created_by, status, data_source, judge_model, models, jd_ids, custom_jd, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (run_id, created_by, "running", data_source, judge_model,
                     Json(list(models)), Json(list(jd_ids)), custom_jd, notes),
                )
        self.logger.info("Eval run %s created by %s", run_id, created_by)

    def finish_eval_run(self, run_id: str, status: str) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE eval_runs SET status = %s, finished_at = NOW() WHERE id = %s",
                    (status, run_id),
                )

    def insert_eval_result(self, result: Dict[str, Any]) -> None:
        columns = [c for c in self._EVAL_RESULT_COLUMNS if c != "created_at"]
        json_columns = {"schema_errors", "missing_keywords", "resume_json"}
        values = [
            Json(result.get(c)) if c in json_columns and result.get(c) is not None else result.get(c)
            for c in columns
        ]
        placeholders = ", ".join(["%s"] * len(columns))
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO eval_results ({', '.join(columns)}) VALUES ({placeholders})",
                    tuple(values),
                )

    def list_eval_runs(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {', '.join(self._EVAL_RUN_COLUMNS)} FROM eval_runs "
                    "ORDER BY created_at DESC LIMIT %s OFFSET %s",
                    (limit, offset),
                )
                rows = cur.fetchall()
        return [self._row_to_dict(self._EVAL_RUN_COLUMNS, r) for r in rows]

    def get_eval_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {', '.join(self._EVAL_RUN_COLUMNS)} FROM eval_runs WHERE id = %s",
                    (run_id,),
                )
                row = cur.fetchone()
        return self._row_to_dict(self._EVAL_RUN_COLUMNS, row) if row else None

    def get_eval_results(self, run_id: str) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {', '.join(self._EVAL_RESULT_COLUMNS)} FROM eval_results "
                    "WHERE run_id = %s ORDER BY model, jd_id",
                    (run_id,),
                )
                rows = cur.fetchall()
        return [self._row_to_dict(self._EVAL_RESULT_COLUMNS, r) for r in rows]

    def get_eval_result(self, result_id: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {', '.join(self._EVAL_RESULT_COLUMNS)} FROM eval_results WHERE id = %s",
                    (result_id,),
                )
                row = cur.fetchone()
        return self._row_to_dict(self._EVAL_RESULT_COLUMNS, row) if row else None

    def mark_running_evals_interrupted(self) -> int:
        """A container restart leaves 'running' rows behind; close them out."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE eval_runs SET status = 'interrupted', finished_at = NOW() WHERE status = 'running'"
                )
                return cur.rowcount or 0

    def get_eval_model_comparison(self) -> List[Dict[str, Any]]:
        """Per-model aggregate across every stored eval result."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT model,
                           COUNT(DISTINCT run_id)                                    AS runs,
                           COUNT(*)                                                  AS cells,
                           AVG(CASE WHEN status = 'success' THEN 1.0 ELSE 0.0 END)   AS success_rate,
                           AVG(composite_score)                                      AS avg_composite,
                           AVG(schema_score)                                         AS avg_schema,
                           AVG(ats_score)                                            AS avg_ats,
                           AVG(judge_overall)                                        AS avg_judge,
                           AVG(duration_ms)                                          AS avg_duration_ms,
                           MAX(created_at)                                           AS last_run_at
                    FROM eval_results
                    GROUP BY model
                    ORDER BY AVG(composite_score) DESC NULLS LAST
                    """
                )
                rows = cur.fetchall()
        def _f(v):
            return round(float(v), 4) if v is not None else None
        return [
            {
                "model": r[0], "runs": int(r[1]), "cells": int(r[2]),
                "success_rate": _f(r[3]), "avg_composite": _f(r[4]),
                "avg_schema": _f(r[5]), "avg_ats": _f(r[6]), "avg_judge": _f(r[7]),
                "avg_duration_ms": int(r[8]) if r[8] is not None else None,
                "last_run_at": r[9].isoformat() if r[9] else None,
            }
            for r in rows
        ]

    def get_admin_stats(self, days: int = 30) -> Dict[str, Any]:
        """Aggregate statistics about stored resumes for the admin dashboard."""
        stats: Dict[str, Any] = {
            "totals": {},
            "generations_per_day": [],
            "requests_per_day": [],
            "requests_by_hour": [],
            "requests_by_weekday": [],
            "user_request_distribution": [],
            "by_model": [],
            "by_format": [],
            "by_language": [],
            "by_status": [],
            "duration_percentiles": {"p50_ms": None, "p95_ms": None},
            "top_keywords": [],
            "top_users": [],
            "recent_requests": [],
            "recent_errors": [],
            "donations": {},
        }
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM users")
                stats["totals"]["users"] = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*), COUNT(DISTINCT user_id) FROM resume_requests")
                row = cur.fetchone()
                stats["totals"]["resume_requests"] = row[0]
                stats["totals"]["requesting_users"] = row[1]

                cur.execute(
                    """
                    SELECT COUNT(*),
                           COUNT(*) FILTER (WHERE status = 'success'),
                           COALESCE(AVG(duration_ms) FILTER (WHERE status = 'success'), 0)
                    FROM generation_events
                    """
                )
                row = cur.fetchone()
                total_gen, success_gen, avg_ms = row
                stats["totals"]["generations"] = total_gen
                stats["totals"]["successful_generations"] = success_gen
                stats["totals"]["success_rate"] = round(success_gen / total_gen, 4) if total_gen else None
                stats["totals"]["avg_duration_ms"] = int(avg_ms or 0)

                cur.execute(
                    """
                    SELECT COUNT(*) FILTER (WHERE fallback_used),
                           COUNT(*)
                    FROM generation_events
                    WHERE created_at >= CURRENT_DATE - %s::int
                    """,
                    (days,),
                )
                fb_row = cur.fetchone() or (0, 0)
                fallback_count, event_count = int(fb_row[0] or 0), int(fb_row[1] or 0)
                stats["totals"]["fallback_generations"] = fallback_count
                stats["totals"]["fallback_rate"] = round(fallback_count / event_count, 4) if event_count else None

                cur.execute(
                    """
                    SELECT DATE(created_at) AS day, COUNT(*)
                    FROM generation_events
                    WHERE created_at >= CURRENT_DATE - %s::int
                    GROUP BY day ORDER BY day
                    """,
                    (days,),
                )
                stats["generations_per_day"] = [
                    {"day": str(r[0]), "count": r[1]} for r in cur.fetchall()
                ]

                cur.execute(
                    """
                    SELECT DATE(created_at) AS day, COUNT(*)
                    FROM resume_requests
                    WHERE created_at >= CURRENT_DATE - %s::int
                    GROUP BY day ORDER BY day
                    """,
                    (days,),
                )
                stats["requests_per_day"] = [
                    {"day": str(r[0]), "count": r[1]} for r in cur.fetchall()
                ]

                # Requests by hour of day (0-23), zero-filled.
                cur.execute(
                    """
                    SELECT EXTRACT(HOUR FROM created_at)::int AS hr, COUNT(*)
                    FROM resume_requests
                    WHERE created_at >= CURRENT_DATE - %s::int
                    GROUP BY hr
                    """,
                    (days,),
                )
                hour_counts = {int(r[0]): r[1] for r in cur.fetchall()}
                stats["requests_by_hour"] = [
                    {"hour": h, "count": hour_counts.get(h, 0)} for h in range(24)
                ]

                # Requests by weekday (0=Sunday .. 6=Saturday), zero-filled.
                cur.execute(
                    """
                    SELECT EXTRACT(DOW FROM created_at)::int AS dow, COUNT(*)
                    FROM resume_requests
                    WHERE created_at >= CURRENT_DATE - %s::int
                    GROUP BY dow
                    """,
                    (days,),
                )
                weekday_counts = {int(r[0]): r[1] for r in cur.fetchall()}
                stats["requests_by_weekday"] = [
                    {"weekday": d, "count": weekday_counts.get(d, 0)} for d in range(7)
                ]

                # How sticky is usage: distribution of lifetime requests per user.
                cur.execute(
                    """
                    SELECT bucket, COUNT(*) FROM (
                        SELECT CASE
                                 WHEN c = 1 THEN '1'
                                 WHEN c <= 3 THEN '2-3'
                                 WHEN c <= 10 THEN '4-10'
                                 ELSE '11+'
                               END AS bucket
                        FROM (
                            SELECT user_id, COUNT(*) AS c
                            FROM resume_requests GROUP BY user_id
                        ) per_user
                    ) bucketed
                    GROUP BY bucket
                    ORDER BY array_position(ARRAY['1','2-3','4-10','11+'], bucket)
                    """
                )
                stats["user_request_distribution"] = [
                    {"bucket": r[0], "count": r[1]} for r in cur.fetchall()
                ]

                cur.execute(
                    """
                    SELECT COALESCE(model, 'unknown'), COUNT(*)
                    FROM generation_events GROUP BY 1 ORDER BY 2 DESC
                    """
                )
                stats["by_model"] = [{"model": r[0], "count": r[1]} for r in cur.fetchall()]

                cur.execute(
                    """
                    SELECT COALESCE(format, 'unknown'), COUNT(*)
                    FROM generation_events GROUP BY 1 ORDER BY 2 DESC
                    """
                )
                stats["by_format"] = [{"format": r[0], "count": r[1]} for r in cur.fetchall()]

                cur.execute(
                    """
                    SELECT COALESCE(LOWER(language), 'unknown'), COUNT(*)
                    FROM generation_events GROUP BY 1 ORDER BY 2 DESC
                    """
                )
                stats["by_language"] = [{"language": r[0], "count": r[1]} for r in cur.fetchall()]

                cur.execute(
                    """
                    SELECT COALESCE(status, 'unknown'), COUNT(*)
                    FROM generation_events GROUP BY 1 ORDER BY 2 DESC
                    """
                )
                stats["by_status"] = [{"status": r[0], "count": r[1]} for r in cur.fetchall()]

                try:
                    cur.execute(
                        """
                        SELECT created_at, user_id, model, format, status, error
                        FROM generation_events
                        WHERE status <> 'success'
                        ORDER BY created_at DESC
                        LIMIT 50
                        """
                    )
                    stats["recent_errors"] = [
                        {
                            "created_at": str(r[0]),
                            "user_id": r[1],
                            "model": r[2],
                            "format": r[3],
                            "status": r[4],
                            "error": r[5],
                        }
                        for r in cur.fetchall()
                    ]
                except Exception:
                    self.logger.exception("Failed to load recent_errors")
                    stats["recent_errors"] = []

                cur.execute(
                    """
                    SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_ms),
                           PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms)
                    FROM generation_events
                    WHERE status = 'success' AND duration_ms IS NOT NULL
                    """
                )
                row = cur.fetchone()
                stats["duration_percentiles"] = {
                    "p50_ms": int(row[0]) if row and row[0] is not None else None,
                    "p95_ms": int(row[1]) if row and row[1] is not None else None,
                }

                cur.execute(
                    """
                    SELECT user_id, COUNT(*) AS cnt, MAX(created_at)
                    FROM resume_requests GROUP BY user_id ORDER BY cnt DESC LIMIT 10
                    """
                )
                stats["top_users"] = [
                    {"user_id": r[0], "requests": r[1], "last_request": str(r[2])} for r in cur.fetchall()
                ]

                # Job postings are user-pasted and may contain bytes that aren't
                # valid UTF-8 (see _RawBytesLoader). Read the raw column with NO
                # server-side text function — LEFT()/conversion would decode the
                # column and raise CharacterNotInRepertoire before we ever see it.
                # client_encoding='SQL_ASCII' makes the server→client transfer a
                # raw passthrough regardless of the database encoding; we then
                # truncate and decode tolerantly in Python. Guarded so this
                # non-critical preview can never 500 the whole dashboard.
                try:
                    with conn.cursor() as raw_cur:
                        raw_cur.adapters.register_loader("text", _RawBytesLoader)
                        raw_cur.adapters.register_loader("varchar", _RawBytesLoader)
                        raw_cur.execute("SET client_encoding TO 'SQL_ASCII'")
                        try:
                            raw_cur.execute(
                                """
                                SELECT user_id, job_posting, created_at
                                FROM resume_requests ORDER BY created_at DESC LIMIT 20
                                """
                            )
                            rows = raw_cur.fetchall()
                        finally:
                            raw_cur.execute("RESET client_encoding")
                    stats["recent_requests"] = [
                        {
                            "user_id": _decode_loose(r[0]),
                            "job_posting_preview": (_decode_loose(r[1]) or "")[:200],
                            "created_at": str(r[2]),
                        }
                        for r in rows
                    ]
                except Exception:
                    self.logger.exception("Failed to load recent_requests preview")
                    stats["recent_requests"] = []

                # Job-market mining: top keywords across recent postings. Reads
                # job_posting text (same raw-bytes path as above), so guard it.
                try:
                    stats["top_keywords"] = _top_job_keywords(conn, days)
                except Exception:
                    self.logger.exception("Failed to compute top_keywords")
                    stats["top_keywords"] = []

                try:
                    cur.execute(
                        """
                        SELECT COUNT(*), COALESCE(SUM(amount), 0), COALESCE(currency, 'usd')
                        FROM donations WHERE status = 'completed' GROUP BY currency
                        """
                    )
                    stats["donations"] = {
                        "by_currency": [
                            {"currency": r[2], "count": r[0], "total_amount": r[1]} for r in cur.fetchall()
                        ]
                    }
                except Exception:
                    # donations table may not exist yet
                    stats["donations"] = {"by_currency": []}
        return stats

    def get_generation_events(self, limit: int = 10000) -> list:
        """Return all generation events (newest first) for CSV export. Admin only."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, created_at, user_id, model, requested_model, fallback_used, format,
                           language, duration_ms, status, error
                    FROM generation_events
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                return [
                    {
                        "id": r[0],
                        "created_at": str(r[1]),
                        "user_id": r[2],
                        "model": r[3],
                        "requested_model": r[4],
                        "fallback_used": r[5],
                        "format": r[6],
                        "language": r[7],
                        "duration_ms": r[8],
                        "status": r[9],
                        "error": r[10],
                    }
                    for r in cur.fetchall()
                ]

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
