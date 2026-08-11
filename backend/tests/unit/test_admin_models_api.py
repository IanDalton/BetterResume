"""Tests for the admin model-catalog and model-config endpoints."""

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import require_admin
from api.routers import admin as admin_router
from llm import model_config
from llm.model_probe import ProbeResult
from llm.openrouter_catalog import CatalogModel, CatalogUnavailable

CATALOG = [
    CatalogModel("a/tool-model", "openrouter:a/tool-model", "Tool Model", 128000, 0.2, 0.8, True, True),
    CatalogModel("b/plain-model", "openrouter:b/plain-model", "Plain Model", 32000, 0.1, 0.3, False, False),
]


def _client():
    app = FastAPI()
    app.include_router(admin_router.router)
    app.dependency_overrides[require_admin] = lambda: {"email": "daltioan@gmail.com"}
    return TestClient(app)


def test_models_requires_auth():
    app = FastAPI()
    app.include_router(admin_router.router)
    assert TestClient(app).get("/admin/models").status_code == 401


def test_get_model_config_requires_auth():
    app = FastAPI()
    app.include_router(admin_router.router)
    assert TestClient(app).get("/admin/model-config").status_code == 401


def test_put_model_config_requires_auth():
    app = FastAPI()
    app.include_router(admin_router.router)
    resp = TestClient(app).put("/admin/model-config", json={
        "task": "generation", "primary": "openrouter:x", "fallback": None,
    })
    assert resp.status_code == 401


def test_models_defaults_to_tool_capable_only():
    with patch("api.routers.admin.fetch_models", AsyncMock(return_value=CATALOG)):
        resp = _client().get("/admin/models")
    ids = [m["id"] for m in resp.json()["models"]]
    assert ids == ["a/tool-model"]


def test_models_show_all_includes_non_tool_models():
    with patch("api.routers.admin.fetch_models", AsyncMock(return_value=CATALOG)):
        resp = _client().get("/admin/models?tools_only=false")
    assert len(resp.json()["models"]) == 2


def test_models_search_filters_by_id_and_name():
    with patch("api.routers.admin.fetch_models", AsyncMock(return_value=CATALOG)):
        resp = _client().get("/admin/models?tools_only=false&q=plain")
    assert [m["id"] for m in resp.json()["models"]] == ["b/plain-model"]


def test_models_503_when_feed_unavailable():
    with patch("api.routers.admin.fetch_models", AsyncMock(side_effect=CatalogUnavailable("down"))):
        resp = _client().get("/admin/models")
    assert resp.status_code == 503


def test_get_model_config_returns_all_tasks():
    cfg = model_config.ModelConfig(
        generation=model_config.TaskModels("openrouter:g", "openrouter:f"),
        translation=model_config.TaskModels("openrouter:t", None),
        import_=model_config.TaskModels("openrouter:i", None),
        judge=model_config.TaskModels("openrouter:j", None),
    )
    with patch("api.routers.admin.get_model_config", return_value=cfg), \
         patch("api.routers.admin.DBStorage.get_app_settings_meta", return_value={}):
        body = _client().get("/admin/model-config").json()
    assert body["tasks"]["generation"]["primary"] == "openrouter:g"
    assert body["tasks"]["generation"]["fallback"] == "openrouter:f"
    assert set(body["tasks"]) == {"generation", "translation", "import", "judge"}
    # The judge runs one standalone call, so the UI must not offer it a fallback slot.
    assert body["tasks"]["generation"]["supports_fallback"] is True
    assert body["tasks"]["judge"]["supports_fallback"] is False


def test_put_model_config_persists_and_returns_new_state():
    cfg = model_config.ModelConfig(
        generation=model_config.TaskModels("openrouter:new", None),
        translation=model_config.TaskModels("openrouter:t", None),
        import_=model_config.TaskModels("openrouter:i", None),
        judge=model_config.TaskModels("openrouter:j", None),
    )
    with patch("api.routers.admin.set_task_models") as setter, \
         patch("api.routers.admin.probe_model", AsyncMock(return_value=ProbeResult(True))), \
         patch("api.routers.admin.get_model_config", return_value=cfg), \
         patch("api.routers.admin.DBStorage.get_app_settings_meta", return_value={}):
        resp = _client().put("/admin/model-config", json={
            "task": "generation", "primary": "openrouter:new", "fallback": None,
        })
    assert resp.status_code == 200
    setter.assert_called_once_with("generation", "openrouter:new", None, updated_by="daltioan@gmail.com")
    assert resp.json()["tasks"]["generation"]["primary"] == "openrouter:new"


def test_put_model_config_400_on_invalid_model_string():
    """Rejected on shape alone -- no request is made to a nonexistent model."""
    with patch("api.routers.admin.probe_model", AsyncMock(side_effect=AssertionError("must not probe"))):
        resp = _client().put("/admin/model-config", json={
            "task": "generation", "primary": "no-provider", "fallback": None,
        })
    assert resp.status_code == 400
    assert "provider-prefixed" in resp.json()["detail"]


def test_put_model_config_rejects_a_model_that_fails_its_live_check():
    """The reported production failure: a tool-capable-on-paper model whose
    endpoints reject the forced tool call our agents send."""
    failed = ProbeResult(False, "ModelHTTPError: status_code: 404, No endpoints found that "
                                "support the provided 'tool_choice' value")
    with patch("api.routers.admin.set_task_models") as setter, \
         patch("api.routers.admin.probe_model", AsyncMock(return_value=failed)):
        resp = _client().put("/admin/model-config", json={
            "task": "generation", "primary": "openrouter:qwen/qwen3.7-flash", "fallback": None,
        })
    assert resp.status_code == 400
    assert "tool_choice" in resp.json()["detail"]
    setter.assert_not_called()


def test_put_model_config_checks_the_fallback_too():
    """A bad fallback breaks runs whose primary is healthy: `FallbackModel`
    resolves both sub-models before issuing a request."""
    async def _probe(model):
        return ProbeResult(True) if model == "openrouter:good" else ProbeResult(False, "nope")

    with patch("api.routers.admin.set_task_models") as setter, \
         patch("api.routers.admin.probe_model", AsyncMock(side_effect=_probe)):
        resp = _client().put("/admin/model-config", json={
            "task": "generation", "primary": "openrouter:good", "fallback": "openrouter:bad",
        })
    assert resp.status_code == 400
    assert "openrouter:bad" in resp.json()["detail"]
    setter.assert_not_called()


def test_put_model_config_skip_check_stores_without_probing():
    cfg = model_config.ModelConfig(
        generation=model_config.TaskModels("openrouter:new", None),
        translation=model_config.TaskModels("openrouter:t", None),
        import_=model_config.TaskModels("openrouter:i", None),
        judge=model_config.TaskModels("openrouter:j", None),
    )
    with patch("api.routers.admin.set_task_models") as setter, \
         patch("api.routers.admin.probe_model", AsyncMock(side_effect=AssertionError("must not probe"))), \
         patch("api.routers.admin.get_model_config", return_value=cfg), \
         patch("api.routers.admin.DBStorage.get_app_settings_meta", return_value={}):
        resp = _client().put("/admin/model-config", json={
            "task": "generation", "primary": "openrouter:new", "fallback": None, "skip_check": True,
        })
    assert resp.status_code == 200
    setter.assert_called_once()


def test_model_check_endpoint_reports_the_probe_result():
    with patch("api.routers.admin.probe_model",
               AsyncMock(return_value=ProbeResult(False, "ModelHTTPError: 404"))):
        body = _client().post("/admin/model-check", json={"model": "openrouter:x/y"}).json()
    assert body == {
        "model": "openrouter:x/y", "ok": False,
        "detail": "ModelHTTPError: 404", "message": "ModelHTTPError: 404",
    }


def test_model_check_requires_auth():
    app = FastAPI()
    app.include_router(admin_router.router)
    resp = TestClient(app).post("/admin/model-check", json={"model": "openrouter:x/y"})
    assert resp.status_code == 401


def test_put_model_config_422_on_unknown_task():
    resp = _client().put("/admin/model-config", json={
        "task": "nonsense", "primary": "openrouter:x", "fallback": None,
    })
    assert resp.status_code == 422
