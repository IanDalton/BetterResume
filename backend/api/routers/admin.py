import csv
import io
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from api.auth import require_admin
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
    fields = ["id", "created_at", "user_id", "model", "format",
              "language", "duration_ms", "status", "error"]
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=generation_logs.csv"},
    )
