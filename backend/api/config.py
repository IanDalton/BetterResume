import os

DATA_DIR = os.getenv("DATA_DIR", "/app/data")
os.makedirs(DATA_DIR, exist_ok=True)
PERSIST_CHROMA = os.path.join(DATA_DIR, "chroma_db")
OUTPUTS_BASE = os.path.join(DATA_DIR, "outputs")
UPLOADS_BASE = os.path.join(DATA_DIR, "uploads")
for _d in (PERSIST_CHROMA, OUTPUTS_BASE, UPLOADS_BASE):
    os.makedirs(_d, exist_ok=True)
PROFILE_PICS_BASE = os.path.join(UPLOADS_BASE, "profile_pictures")
os.makedirs(PROFILE_PICS_BASE, exist_ok=True)

CACHE_FILENAME = "resume_cache.json"

ALLOWED_PROFILE_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/pjpeg": ".jpg",
    "image/x-png": ".png",
}
PROFILE_EXTENSIONS = {".png", ".jpg"}

DOWNLOAD_SIGNING_SECRET = os.getenv("DOWNLOAD_SIGNING_SECRET") or os.getenv("SECRET_KEY") or "dev-secret-change-me"
