"""The judge model is chosen in the admin dashboard, like every other task.

Before this, the judge was pinned by the `JUDGE_MODEL` env var only, which is
how a stale default (`google-gla:...`) kept failing every eval cell's scoring
step long after the dashboard could change everything else.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import require_admin
from api.routers import admin as admin_router
from llm import model_config


def _cfg(judge="openrouter:configured/judge"):
    return model_config.ModelConfig(
        generation=model_config.TaskModels("openrouter:g", None),
        translation=model_config.TaskModels("openrouter:t", None),
        import_=model_config.TaskModels("openrouter:i", None),
        judge=model_config.TaskModels(judge, None),
    )


def _client():
    app = FastAPI()
    app.include_router(admin_router.router, prefix="/resume")
    app.dependency_overrides[require_admin] = lambda: {"email": "admin@example.com"}
    return TestClient(app)


# ---------------------------------------------------------------------------
# Configuration layer
# ---------------------------------------------------------------------------

def test_judge_is_a_configurable_task():
    assert "judge" in model_config.TASKS
    assert "judge" not in model_config.TASKS_WITH_FALLBACK


def test_judge_does_not_inherit_the_generation_model(monkeypatch):
    """Scoring a resume with the same model that wrote it is self-grading."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DEFAULT_MODEL", "openrouter:some/generation-model")
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    model_config.invalidate_cache()
    cfg = model_config.get_model_config(force_refresh=True)
    assert cfg.generation.primary == "openrouter:some/generation-model"
    assert cfg.judge.primary == model_config.SHIPPED_JUDGE_MODEL


def test_judge_env_var_seeds_the_task(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("JUDGE_MODEL", "openrouter:env/judge")
    model_config.invalidate_cache()
    assert model_config.get_model_config(force_refresh=True).judge.primary == "openrouter:env/judge"


def test_saving_a_judge_fallback_is_rejected():
    with pytest.raises(ValueError, match="does not support a fallback"):
        model_config.set_task_models("judge", "openrouter:a/b", "openrouter:c/d")


def test_saving_an_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="Unknown model provider"):
        model_config.set_task_models("generation", "google-gla-typo:x", None)


def test_saving_normalizes_a_legacy_prefix():
    with patch("llm.model_config.DBStorage.set_app_setting") as setter, \
         patch("llm.model_config.invalidate_cache"):
        model_config.set_task_models("judge", "google-gla:gemini-2.5-flash-lite", None)
    stored = setter.call_args[0][1]
    assert stored == {"primary": "google:gemini-2.5-flash-lite", "fallback": None}


# ---------------------------------------------------------------------------
# API layer
# ---------------------------------------------------------------------------

def test_fixtures_endpoint_reports_the_configured_judge():
    with patch("api.routers.admin.get_model_config", return_value=_cfg()):
        body = _client().get("/resume/admin/evals/fixtures").json()
    assert body["default_judge_model"] == "openrouter:configured/judge"


def test_eval_run_without_a_judge_model_uses_the_configured_one():
    captured = {}

    async def _fake_run_eval(spec, **kwargs):
        captured["judge"] = spec.judge_model
        return "run"

    with patch("api.routers.admin.get_model_config", return_value=_cfg()), \
         patch("api.routers.admin.run_eval", AsyncMock(side_effect=_fake_run_eval)), \
         patch("api.routers.admin.DBStorage.finish_eval_run"):
        resp = _client().post("/resume/admin/evals", json={
            "models": ["openrouter:a"], "jd_ids": ["senior_swe"], "data_source": "fixture",
        })
    assert resp.status_code == 202
    assert captured["judge"] == "openrouter:configured/judge"


def test_eval_run_can_still_pin_a_judge_model():
    captured = {}

    async def _fake_run_eval(spec, **kwargs):
        captured["judge"] = spec.judge_model
        return "run"

    with patch("api.routers.admin.get_model_config", return_value=_cfg()), \
         patch("api.routers.admin.run_eval", AsyncMock(side_effect=_fake_run_eval)), \
         patch("api.routers.admin.DBStorage.finish_eval_run"):
        _client().post("/resume/admin/evals", json={
            "models": ["openrouter:a"], "jd_ids": ["senior_swe"], "data_source": "fixture",
            "judge_model": "openrouter:pinned/judge",
        })
    assert captured["judge"] == "openrouter:pinned/judge"


def test_eval_run_can_disable_the_judge():
    captured = {}

    async def _fake_run_eval(spec, **kwargs):
        captured["judge"] = spec.judge_model
        return "run"

    with patch("api.routers.admin.get_model_config", return_value=_cfg()), \
         patch("api.routers.admin.run_eval", AsyncMock(side_effect=_fake_run_eval)), \
         patch("api.routers.admin.DBStorage.finish_eval_run"):
        _client().post("/resume/admin/evals", json={
            "models": ["openrouter:a"], "jd_ids": ["senior_swe"], "data_source": "fixture",
            "judge_model": "",
        })
    assert captured["judge"] is None


def test_put_model_config_accepts_the_judge_task():
    from llm.model_probe import ProbeResult

    with patch("api.routers.admin.set_task_models") as setter, \
         patch("api.routers.admin.probe_model", AsyncMock(return_value=ProbeResult(True))), \
         patch("api.routers.admin.get_model_config", return_value=_cfg()), \
         patch("api.routers.admin.DBStorage.get_app_settings_meta", return_value={}):
        resp = _client().put("/resume/admin/model-config", json={
            "task": "judge", "primary": "openrouter:new/judge", "fallback": None,
        })
    assert resp.status_code == 200
    assert setter.call_args[0][:3] == ("judge", "openrouter:new/judge", None)


def test_judge_uses_the_configured_model_and_openrouter_routing(monkeypatch):
    from evals.evaluators.llm_judge import LLMJudge

    # Resolving an `openrouter:` model builds its provider, which wants a key.
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    with patch("evals.evaluators.llm_judge.get_model_config", return_value=_cfg()):
        judge = LLMJudge()
    assert judge._agent.model.model_name == "configured/judge"
    settings = judge._agent.model_settings
    assert settings["openrouter_provider"]["require_parameters"] is True
