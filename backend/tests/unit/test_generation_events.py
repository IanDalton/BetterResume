"""Generation events record the requested model alongside the model that served
the request, so a silently-degrading primary is visible on the dashboard."""

import contextlib
from unittest.mock import patch

from utils.db_storage import DBStorage
from tests.unit.test_app_settings_db import FakeConn, FakeCursor


def _patch_conn(cursor):
    @contextlib.contextmanager
    def fake_get_conn(self):
        yield FakeConn(cursor)

    return patch.object(DBStorage, "_get_conn", fake_get_conn)


def test_record_generation_event_persists_fallback_columns():
    cur = FakeCursor()
    with _patch_conn(cur):
        DBStorage().record_generation_event(
            user_id="u1",
            model="google-gla:gemini-2.5-flash-lite",
            requested_model="openrouter:qwen/qwen3-coder-30b-a3b-instruct",
            format="word",
            language="en",
            duration_ms=1234,
            status="success",
            fallback_used=True,
        )
    sql, params = cur.executed[0]
    assert "requested_model" in sql and "fallback_used" in sql
    assert "openrouter:qwen/qwen3-coder-30b-a3b-instruct" in params
    assert True in params


def test_record_generation_event_defaults_are_backwards_compatible():
    cur = FakeCursor()
    with _patch_conn(cur):
        DBStorage().record_generation_event(user_id="u1", model="m", status="success")
    _, params = cur.executed[0]
    assert False in params, "fallback_used must default to False"
