import logging
from fastapi import APIRouter, Security
from utils.db_storage import DBStorage
from api.auth import get_current_admin

logger = logging.getLogger("betterresume.api.admin")
router = APIRouter()
db = DBStorage()

@router.get("/stats")
def get_stats(admin_user: dict = Security(get_current_admin)):
    """Retrieve system-wide statistics."""
    stats = {
        "users": 0,
        "resume_requests": 0,
        "job_experiences": 0,
        "files_stored": 0,
        "resumes_generated": 0, # Estimated from cache or files
        "recent_activity": []
    }
    
    try:
        with db._get_conn() as conn:
            with conn.cursor() as cur:
                # User count
                cur.execute("SELECT count(*) FROM users")
                row = cur.fetchone()
                if row:
                    stats["users"] = row[0]
                
                # Resume requests (Jobs)
                cur.execute("SELECT count(*) FROM resume_requests")
                row = cur.fetchone()
                if row:
                    stats["resume_requests"] = row[0]
                
                # Job experiences
                cur.execute("SELECT count(*) FROM job_experiences")
                row = cur.fetchone()
                if row:
                    stats["job_experiences"] = row[0]
                
                # Total files
                cur.execute("SELECT count(*) FROM user_files")
                row = cur.fetchone()
                if row:
                    stats["files_stored"] = row[0]

                # Resumes generated (based on cache)
                cur.execute("SELECT count(*) FROM resume_generation_cache")
                row = cur.fetchone()
                if row:
                    stats["resumes_generated"] = row[0]

                # Recent activity (Last 10 users created)
                cur.execute("""
                    SELECT user_id, created_at, 'User Created' as type 
                    FROM users 
                    ORDER BY created_at DESC 
                    LIMIT 5
                """)
                users = [{"user_id": r[0], "date": str(r[1]), "type": r[2]} for r in cur.fetchall()]
                
                # Recent job uploads
                cur.execute("""
                    SELECT user_id, created_at, 'Job Experience Added' as type 
                    FROM job_experiences 
                    ORDER BY created_at DESC 
                    LIMIT 5
                """)
                jobs = [{"user_id": r[0], "date": str(r[1]), "type": r[2]} for r in cur.fetchall()]

                # Combine and sort
                combined = sorted(users + jobs, key=lambda x: x['date'], reverse=True)[:10]
                stats["recent_activity"] = combined

    except Exception as e:
        logger.error("Failed to fetch admin stats: %s", e)
        # Return what we have or error out? 
        # For admin dashboard it's better to show partial data or 0s than 500
    
    return stats

