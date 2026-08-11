"""Tests for the app_settings key/value accessors on DBStorage."""

import contextlib
import json
from unittest.mock import patch

from utils.db_storage import DBStorage


class FakeCursor:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, *a, **k):
        return self._cursor

    def commit(self):
        pass


def _patch_conn(cursor):
    @contextlib.contextmanager
    def fake_get_conn(self):
        yield FakeConn(cursor)

    return patch.object(DBStorage, "_get_conn", fake_get_conn)


def test_get_app_setting_returns_value():
    cur = FakeCursor(rows=[({"primary": "openrouter:a", "fallback": None},)])
    with _patch_conn(cur):
        assert DBStorage().get_app_setting("model.generation") == {
            "primary": "openrouter:a",
            "fallback": None,
        }
    assert "model.generation" in cur.executed[0][1]


def test_get_app_setting_returns_none_when_missing():
    with _patch_conn(FakeCursor(rows=[])):
        assert DBStorage().get_app_setting("model.generation") is None


def test_get_app_setting_parses_json_string_value():
    """psycopg may hand back a raw JSON string depending on adapter registration."""
    cur = FakeCursor(rows=[(json.dumps({"primary": "google-gla:x", "fallback": None}),)])
    with _patch_conn(cur):
        assert DBStorage().get_app_setting("model.import")["primary"] == "google-gla:x"


def test_set_app_setting_upserts_with_actor():
    cur = FakeCursor()
    with _patch_conn(cur):
        DBStorage().set_app_setting(
            "model.generation",
            {"primary": "openrouter:b", "fallback": "google-gla:c"},
            updated_by="admin@example.com",
        )
    sql, params = cur.executed[0]
    assert "INSERT INTO app_settings" in sql
    assert "ON CONFLICT (key) DO UPDATE" in sql
    assert params[0] == "model.generation"
    assert params[2] == "admin@example.com"


def test_get_app_settings_meta_returns_rows_by_key():
    cur = FakeCursor(rows=[
        ("model.generation", {"primary": "openrouter:b", "fallback": None}, None, "admin@example.com"),
    ])
    with _patch_conn(cur):
        meta = DBStorage().get_app_settings_meta("model.")
    assert meta["model.generation"]["value"]["primary"] == "openrouter:b"
    assert meta["model.generation"]["updated_by"] == "admin@example.com"
