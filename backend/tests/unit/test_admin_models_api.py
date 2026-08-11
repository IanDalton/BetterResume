"""Tests for the admin model-catalog and model-config endpoints."""

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import require_admin
from api.routers import admin as admin_router
from llm import model_config
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
        generation=model_config.TaskModels("openrouter:g", "google-gla:f"),
        translation=model_config.TaskModels("openrouter:t", None),
        import_=model_config.TaskModels("openrouter:i", None),
    )
    with patch("api.routers.admin.get_model_config", return_value=cfg), \
         patch("api.routers.admin.DBStorage.get_app_settings_meta", return_value={}):
        body = _client().get("/admin/model-config").json()
    assert body["tasks"]["generation"]["primary"] == "openrouter:g"
    assert body["tasks"]["generation"]["fallback"] == "google-gla:f"
    assert set(body["tasks"]) == {"generation", "translation", "import"}


def test_put_model_config_persists_and_returns_new_state():
    cfg = model_config.ModelConfig(
        generation=model_config.TaskModels("openrouter:new", None),
        translation=model_config.TaskModels("openrouter:t", None),
        import_=model_config.TaskModels("openrouter:i", None),
    )
    with patch("api.routers.admin.set_task_models") as setter, \
         patch("api.routers.admin.get_model_config", return_value=cfg), \
         patch("api.routers.admin.DBStorage.get_app_settings_meta", return_value={}):
        resp = _client().put("/admin/model-config", json={
            "task": "generation", "primary": "openrouter:new", "fallback": None,
        })
    assert resp.status_code == 200
    setter.assert_called_once_with("generation", "openrouter:new", None, updated_by="daltioan@gmail.com")
    assert resp.json()["tasks"]["generation"]["primary"] == "openrouter:new"


def test_put_model_config_400_on_invalid_model_string():
    with patch("api.routers.admin.set_task_models", side_effect=ValueError("must be provider-prefixed")):
        resp = _client().put("/admin/model-config", json={
            "task": "generation", "primary": "no-provider", "fallback": None,
        })
    assert resp.status_code == 400
    assert "provider-prefixed" in resp.json()["detail"]


def test_put_model_config_422_on_unknown_task():
    resp = _client().put("/admin/model-config", json={
        "task": "nonsense", "primary": "openrouter:x", "fallback": None,
    })
    assert resp.status_code == 422
