import logging
import logging.handlers
import os
from contextvars import ContextVar
from typing import Optional
import uuid

# Context variables to carry through async tasks
request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
user_id_var: ContextVar[Optional[str]] = ContextVar("log_user_id", default=None)


class ContextFilter(logging.Filter):
    """Inject request_id and user_id into log records if set in contextvars."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        rid = request_id_var.get() or "-"
        uid = user_id_var.get() or "-"
        # Attach attributes so formatters can use them
        setattr(record, "request_id", rid)
        setattr(record, "user_id", uid)
        return True


_initialized = False


def setup_logging(level: Optional[int] = None) -> None:
    """Idempotently configure app logging with a consistent format and context filter.

    We keep handlers minimal and let Uvicorn capture stdout. Attaches a ContextFilter
    so logs include request_id and user_id automatically.

    Environment overrides:
        LOG_LEVEL — DEBUG/INFO/WARNING/ERROR (default INFO)
        LOG_FILE  — when set, also writes to a rotating file (5 MB x 3 backups)
    """
    global _initialized
    if _initialized:
        return
    if level is None:
        level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logger_names = [
        "betterresume",  # app-wide base
        "betterresume.api",
        "betterresume.bot",
        "betterresume.agent",
        "betterresume.embeddings",
        "betterresume.pgvector",
        "betterresume.auth",
        "betterresume.db_storage",
        "betterresume.writer",
        "betterresume.utils",
    ]
    fmt = "%(asctime)s %(levelname)s %(name)s req=%(request_id)s user=%(user_id)s - %(message)s"
    formatter = logging.Formatter(fmt)
    context_filter = ContextFilter()

    handlers: list[logging.Handler] = []
    stream_handler = logging.StreamHandler()
    handlers.append(stream_handler)

    log_file = os.getenv("LOG_FILE")
    if log_file:
        try:
            file_handler = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
            handlers.append(file_handler)
        except OSError:
            logging.getLogger("betterresume").warning("Could not open LOG_FILE=%s", log_file)

    for handler in handlers:
        handler.setLevel(level)
        handler.setFormatter(formatter)
        handler.addFilter(context_filter)

    for name in logger_names:
        lg = logging.getLogger(name)
        lg.setLevel(level)
        for handler in handlers:
            # Avoid duplicate handlers if hot-reloaded
            if not any(type(h) is type(handler) for h in lg.handlers):
                lg.addHandler(handler)
        lg.propagate = False  # prevent double printing via root
    _initialized = True


def new_request_id() -> str:
    rid = uuid.uuid4().hex
    request_id_var.set(rid)
    return rid


def set_user_context(user_id: Optional[str]) -> None:
    user_id_var.set(user_id)


def clear_request_id() -> None:
    request_id_var.set(None)


def clear_user_context() -> None:
    user_id_var.set(None)
