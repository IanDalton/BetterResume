import logging
import time
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from utils.logging_utils import setup_logging, new_request_id, clear_request_id
from api.routers import health, jobs, profile, resume, users

setup_logging()
app = FastAPI(title="BetterResume API", version="0.1.0")
# Module logger (relies on configured handlers)
logger = logging.getLogger("betterresume.api")

# Firebase auth disabled for now
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://iandalton.dev", "http://localhost:5173", "http://127.0.0.1"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.middleware("http")
async def add_request_context(request: Request, call_next):
    """Attach a correlation id to every request and basic access log lines."""
    rid = new_request_id()
    start = time.time()
    path = request.url.path
    method = request.method
    logger.info("Inbound request %s %s", method, path)
    try:
        response = await call_next(request)
        duration_ms = int((time.time() - start) * 1000)
        logger.info("Completed %s %s -> %s in %dms", method, path, getattr(response, 'status_code', '?'), duration_ms)
        return response
    finally:
        # Clear only the request id; user id is tied to the endpoint handling
        clear_request_id()

app.include_router(health.router)
app.include_router(jobs.router)
app.include_router(profile.router)
app.include_router(resume.router)
app.include_router(users.router)

# Convenience root
@app.get("/")
async def root():
    return {"message": "BetterResume API. Use /upload-jobs/{user_id} then /generate-resume/{user_id}."}
