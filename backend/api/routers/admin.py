import logging

from fastapi import APIRouter, Depends, HTTPException, Query

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
