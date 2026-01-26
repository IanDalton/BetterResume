import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from utils.logging_utils import setup_logging, new_request_id, clear_request_id
from utils.db_storage import DBStorage, init_db_pool, close_db_pool, init_async_db_pool, close_async_db_pool
from api.routers import health, jobs, profile, resume, users, donations, admin

setup_logging()
# Module logger (relies on configured handlers)
logger = logging.getLogger("betterresume.api")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database pools...")
    init_db_pool()
    
    logger.info("Initializing database schema...")
    try:
        DBStorage().init_schema()
    except Exception as e:
        logger.error("Startup schema initialization failed: %s", e)

    # Initialize async pool after schema is ready (so vector extension exists)
    await init_async_db_pool()
    yield
    
    logger.info("Closing database pools...")
    await close_async_db_pool()
    close_db_pool()

app = FastAPI(title="BetterResume API", version="0.1.0", lifespan=lifespan)

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

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "frame-ancestors 'self' https://iandalton.dev http://localhost:5173 http://127.0.0.1"
    return response

app.include_router(health.router)
app.include_router(jobs.router, prefix="/resume")
app.include_router(profile.router, prefix="/resume")
app.include_router(resume.router, prefix="/resume")
app.include_router(users.router, prefix="/resume")
app.include_router(donations.router, prefix="/resume")
app.include_router(admin.router, prefix="/admin")


# Convenience root
@app.get("/")
async def root():
    return {"message": "BetterResume API. Use /upload-jobs/{user_id} then /generate-resume/{user_id}."}
