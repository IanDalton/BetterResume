"""Tests for logging setup and request/user context propagation."""

import logging

import utils.logging_utils as lu


def test_context_filter_injects_ids():
    lu.new_request_id()
    lu.set_user_context("user_9")
    record = logging.LogRecord("betterresume", logging.INFO, __file__, 1, "msg", None, None)

    assert lu.ContextFilter().filter(record) is True
    assert record.user_id == "user_9"
    assert record.request_id != "-"

    lu.clear_request_id()
    lu.clear_user_context()
    record2 = logging.LogRecord("betterresume", logging.INFO, __file__, 1, "msg", None, None)
    lu.ContextFilter().filter(record2)
    assert record2.user_id == "-"
    assert record2.request_id == "-"


def test_new_request_id_unique():
    assert lu.new_request_id() != lu.new_request_id()


def test_setup_logging_idempotent(monkeypatch):
    monkeypatch.setattr(lu, "_initialized", False)
    lu.setup_logging()
    base = logging.getLogger("betterresume")
    handler_count = len(base.handlers)

    lu.setup_logging()
    assert len(base.handlers) == handler_count, "setup_logging must not duplicate handlers"
    assert base.propagate is False


def test_setup_logging_honors_log_level_env(monkeypatch):
    monkeypatch.setattr(lu, "_initialized", False)
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    # Use fresh logger state: setLevel is applied to named loggers
    lu.setup_logging()
    assert logging.getLogger("betterresume.agent").level == logging.DEBUG
