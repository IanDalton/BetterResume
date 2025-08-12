import logging
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


def setup_logging(level: int = logging.INFO) -> None:
    """Idempotently configure app logging with a consistent format and context filter.

    We keep handlers minimal and let Uvicorn capture stdout. Attaches a ContextFilter
    so logs include request_id and user_id automatically.
    """
    global _initialized
    if _initialized:
        return
    logger_names = [
        "betterresume",  # app-wide base
        "betterresume.api",
        "betterresume.bot",
        "betterresume.llm",
        "betterresume.chroma",
        "betterresume.writer",
        "betterresume.utils",
    ]
    fmt = "%(asctime)s %(levelname)s %(name)s req=%(request_id)s user=%(user_id)s - %(message)s"
    # Create a single stream handler
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(fmt))
    handler.addFilter(ContextFilter())
    for name in logger_names:
        lg = logging.getLogger(name)
        lg.setLevel(level)
        # Avoid duplicate handlers if hot-reloaded
        if not any(isinstance(h, logging.StreamHandler) for h in lg.handlers):
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
