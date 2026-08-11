"""Tests for runtime per-task model configuration."""

from unittest.mock import patch

import pytest

from llm import model_config


@pytest.fixture(autouse=True)
def _clear_cache():
    model_config.invalidate_cache()
    yield
    model_config.invalidate_cache()


def test_falls_back_to_env_when_no_row(monkeypatch):
    monkeypatch.setenv("DEFAULT_MODEL", "openrouter:env/primary")
    monkeypatch.delenv("TRANSLATION_MODEL", raising=False)
    with patch("llm.model_config.DBStorage.get_app_setting", return_value=None):
        cfg = model_config.get_model_config(force_refresh=True)
    assert cfg.generation.primary == "openrouter:env/primary"
    assert cfg.translation.primary == "openrouter:env/primary"


def test_env_task_override_used_when_present(monkeypatch):
    monkeypatch.setenv("DEFAULT_MODEL", "openrouter:env/primary")
    monkeypatch.setenv("IMPORT_MODEL", "google-gla:gemini-2.5-flash-lite")
    with patch("llm.model_config.DBStorage.get_app_setting", return_value=None):
        cfg = model_config.get_model_config(force_refresh=True)
    assert cfg.import_.primary == "google-gla:gemini-2.5-flash-lite"


def test_stored_row_overrides_env(monkeypatch):
    monkeypatch.setenv("DEFAULT_MODEL", "openrouter:env/primary")
    stored = {"primary": "openrouter:stored/x", "fallback": "google-gla:gemini-2.5-flash-lite"}
    with patch("llm.model_config.DBStorage.get_app_setting", return_value=stored):
        cfg = model_config.get_model_config(force_refresh=True)
    assert cfg.generation.primary == "openrouter:stored/x"
    assert cfg.generation.fallback == "google-gla:gemini-2.5-flash-lite"


def test_result_is_cached_within_ttl(monkeypatch):
    monkeypatch.setenv("DEFAULT_MODEL", "openrouter:env/primary")
    with patch("llm.model_config.DBStorage.get_app_setting", return_value=None) as mocked:
        model_config.get_model_config(force_refresh=True)
        model_config.get_model_config()
        model_config.get_model_config()
    # 3 tasks read once each on the first (uncached) call only
    assert mocked.call_count == len(model_config.TASKS)


def test_cache_expires_after_ttl(monkeypatch):
    monkeypatch.setenv("DEFAULT_MODEL", "openrouter:env/primary")
    fake_now = {"t": 1000.0}
    monkeypatch.setattr(model_config.time, "monotonic", lambda: fake_now["t"])
    with patch("llm.model_config.DBStorage.get_app_setting", return_value=None) as mocked:
        model_config.get_model_config(force_refresh=True)
        fake_now["t"] += model_config.CACHE_TTL_SECONDS + 1
        model_config.get_model_config()
    assert mocked.call_count == 2 * len(model_config.TASKS)


def test_db_failure_degrades_to_env(monkeypatch, caplog):
    monkeypatch.setenv("DEFAULT_MODEL", "openrouter:env/primary")
    with patch("llm.model_config.DBStorage.get_app_setting", side_effect=RuntimeError("db down")):
        cfg = model_config.get_model_config(force_refresh=True)
    assert cfg.generation.primary == "openrouter:env/primary"


def test_set_task_models_writes_and_invalidates(monkeypatch):
    monkeypatch.setenv("DEFAULT_MODEL", "openrouter:env/primary")
    with patch("llm.model_config.DBStorage.set_app_setting") as setter, \
         patch("llm.model_config.DBStorage.get_app_setting", return_value=None):
        model_config.get_model_config(force_refresh=True)
        model_config.set_task_models("generation", "openrouter:new/x", None, updated_by="a@b.c")
    args = setter.call_args.args
    assert args[0] == "model.generation"
    assert args[1] == {"primary": "openrouter:new/x", "fallback": None}
    assert model_config._CACHE["value"] is None, "write must invalidate the cache"


def test_set_task_models_rejects_unknown_task():
    with pytest.raises(ValueError):
        model_config.set_task_models("nonsense", "openrouter:x", None)


def test_set_task_models_rejects_unprefixed_model():
    with pytest.raises(ValueError):
        model_config.set_task_models("generation", "gpt-4o-mini-no-provider", None)


def test_for_task_lookup():
    cfg = model_config.ModelConfig(
        generation=model_config.TaskModels("a:1", None),
        translation=model_config.TaskModels("b:2", None),
        import_=model_config.TaskModels("c:3", None),
    )
    assert cfg.for_task("import").primary == "c:3"
    with pytest.raises(ValueError):
        cfg.for_task("bogus")
