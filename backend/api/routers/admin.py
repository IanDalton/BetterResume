import csv
import io
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from api.auth import require_admin
from llm.model_config import TASKS, get_model_config, set_task_models
from llm.openrouter_catalog import CatalogUnavailable, fetch_models
from utils.db_storage import DBStorage

logger = logging.getLogger("betterresume.api.admin")
router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats")
async def admin_stats(days: int = Query(default=30, ge=1, le=365), claims: dict = Depends(require_admin)):
    """Aggregated resume/generation statistics. Admin only."""
    logger.info("Admin stats requested by %s (days=%d)", claims.get("email"), days)
    try:
        stats = DBStorage().get_admin_stats(days=days)
    except Exception:
        logger.exception("Failed to compute admin stats")
        raise HTTPException(status_code=500, detail="Failed to compute statistics")
    return stats


@router.get("/logs/export")
async def export_logs(claims: dict = Depends(require_admin)):
    """Download all generation events as CSV. Admin only."""
    logger.info("Admin logs export requested by %s", claims.get("email"))
    try:
        rows = DBStorage().get_generation_events()
    except Exception:
        logger.exception("Failed to export generation logs")
        raise HTTPException(status_code=500, detail="Failed to export logs")
    buf = io.StringIO()
    fields = ["id", "created_at", "user_id", "model", "requested_model", "fallback_used",
              "format", "language", "duration_ms", "status", "error"]
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=generation_logs.csv"},
    )


class ModelConfigUpdate(BaseModel):
    task: Literal["generation", "translation", "import"]
    primary: str
    fallback: Optional[str] = None


def _model_config_payload() -> dict:
    config = get_model_config(force_refresh=True)
    meta = DBStorage().get_app_settings_meta("model.")
    tasks = {}
    for task in TASKS:
        task_models = config.for_task(task)
        row = meta.get(f"model.{task}", {})
        tasks[task] = {
            "primary": task_models.primary,
            "fallback": task_models.fallback,
            "updated_at": row.get("updated_at"),
            "updated_by": row.get("updated_by"),
        }
    return {"tasks": tasks}


@router.get("/models")
async def list_models(tools_only: bool = True, q: str = "", claims: dict = Depends(require_admin)):
    """OpenRouter's model catalog, filtered for the admin picker."""
    try:
        models = await fetch_models()
    except CatalogUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"OpenRouter model list unavailable: {exc}")
    if tools_only:
        models = [m for m in models if m.supports_tools]
    if q:
        needle = q.lower()
        models = [m for m in models if needle in m.id.lower() or needle in m.name.lower()]
    return {"models": [m.as_dict() for m in models]}


@router.get("/model-config")
async def read_model_config(claims: dict = Depends(require_admin)):
    """Current per-task model settings."""
    return _model_config_payload()


@router.put("/model-config")
async def update_model_config(update: ModelConfigUpdate, claims: dict = Depends(require_admin)):
    """Set the primary/fallback models for one task."""
    try:
        set_task_models(update.task, update.primary, update.fallback, updated_by=claims.get("email"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    logger.info("Model config for %s changed by %s", update.task, claims.get("email"))
    return _model_config_payload()
