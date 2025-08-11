import os
import hashlib
# Disable telemetry noise from dependencies (e.g., ChromaDB / posthog)
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
os.environ.setdefault("CHROMA_TELEMETRY_ENABLED", "false")
os.environ.setdefault("POSTHOG_DISABLED", "1")
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from llm.chroma_db_tool import ChromaDBTool
import shutil
from bot import Bot
from resume import LatexResumeWriter, WordResumeWriter
from llm.gemini_tool import GeminiTool
from typing import Dict

DATA_DIR = os.getenv("DATA_DIR", "/app/data")  # default to mounted volume path
os.makedirs(DATA_DIR, exist_ok=True)
PERSIST_CHROMA = os.path.join(DATA_DIR, "chroma_db")
OUTPUTS_BASE = os.path.join(DATA_DIR, "outputs")
UPLOADS_BASE = os.path.join(DATA_DIR, "uploads")
for _d in (PERSIST_CHROMA, OUTPUTS_BASE, UPLOADS_BASE):
    os.makedirs(_d, exist_ok=True)

app = FastAPI(title="BetterResume API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Maintain a cache of user_id -> ChromaDBTool (separate collections)
USER_TOOLS: Dict[str, ChromaDBTool] = {}

def get_user_tool(user_id: str) -> ChromaDBTool:
    if user_id not in USER_TOOLS:
        USER_TOOLS[user_id] = ChromaDBTool(persist_directory=PERSIST_CHROMA, collection_name=f"user_{user_id}")
    return USER_TOOLS[user_id]

class ResumeRequest(BaseModel):
    job_description: str
    format: str = "latex"  # or "word"
    model: str = "gemini-2.5-flash"

def clean_output_dir(path: str):
    """Remove all existing files in the user's output directory so only the newly generated resume remains.
    Keeps the directory itself (so any open file handles won't break directory existence).
    """
    try:
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
            return
        for name in os.listdir(path):
            full = os.path.join(path, name)
            try:
                if os.path.isfile(full) or os.path.islink(full):
                    os.remove(full)
                elif os.path.isdir(full):
                    shutil.rmtree(full, ignore_errors=True)
            except Exception:
                # Best-effort; continue cleaning others
                pass
    except Exception:
        # Silently ignore; generation will overwrite needed files anyway
        pass

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/upload-jobs/{user_id}")
async def upload_jobs(user_id: str, file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv")
    contents = await file.read()
    new_hash = hashlib.sha256(contents).hexdigest()
    tmp_path = os.path.join(UPLOADS_BASE, f"uploaded_jobs_{user_id}.csv")
    hash_path = tmp_path + ".sha256"
    # If hash matches existing, skip re-ingestion
    if os.path.isfile(tmp_path) and os.path.isfile(hash_path):
        try:
            with open(hash_path, 'r', encoding='utf-8') as hf:
                old_hash = hf.read().strip()
            if old_hash == new_hash:
                # Attempt to get row count for informative response
                rows = None
                try:
                    import pandas as pd
                    df_prev = pd.read_csv(tmp_path)
                    rows = len(df_prev)
                except Exception:
                    pass
                return {"status": "unchanged", "rows_ingested": 0, "rows": rows, "hash": new_hash, "message": "CSV identical; ingestion skipped"}
        except Exception:
            pass
    # Write new file
    with open(tmp_path, "wb") as f:
        f.write(contents)
    with open(hash_path, 'w', encoding='utf-8') as hf:
        hf.write(new_hash)
    tool = get_user_tool(user_id)
    try:
        import pandas as pd
        try:
            df = pd.read_csv(tmp_path)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to parse CSV: {e}")
        # Minimum set: company, description, type (dates optional but normalize if present)
        required_min = {"company","description","type"}
        missing = sorted(list(required_min - set(df.columns)))
        if missing:
            raise HTTPException(status_code=400, detail=f"Missing required columns: {', '.join(missing)}")
        # If date columns exist, attempt parsing; ignore if absent
        import warnings
        for col in ["start_date","end_date"]:
            if col in df.columns:
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore')
                        df[col] = pd.to_datetime(df[col], errors='coerce', dayfirst=True)
                except Exception:
                    pass
        # Persist normalized dates back to file for downstream readers
        try:
            df.to_csv(tmp_path, index=False)
        except Exception:
            pass
        rows = len(df)
        from langchain_community.document_loaders.csv_loader import CSVLoader
        data = CSVLoader(file_path=tmp_path).load()
        try:
            current = tool._collection.count()
        except Exception:
            current = 0
        tool.add_documents(
            [d.page_content for d in data],
            [str(current + i) for i, _ in enumerate(data)],
        )
        return {"status": "ok", "rows_ingested": rows, "hash": new_hash}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def _resolve_user_jobs_csv(user_id: str) -> str:
    """Return absolute path to the uploaded jobs CSV for a user or raise HTTP 400 if missing."""
    csv_path = os.path.join(UPLOADS_BASE, f"uploaded_jobs_{user_id}.csv")
    if not os.path.isfile(csv_path):
        raise HTTPException(status_code=400, detail="Jobs CSV not uploaded. Upload via /upload-jobs/{user_id} first.")
    return csv_path

@app.post("/generate-resume/{user_id}")
async def generate_resume(user_id: str, req: ResumeRequest):
    csv_path = _resolve_user_jobs_csv(user_id)
    # Row count for response metadata
    row_count = None
    try:
        import pandas as pd
        row_count = len(pd.read_csv(csv_path))
    except Exception:
        pass
    writer = LatexResumeWriter(csv_location=csv_path) if req.format.lower() == "latex" else WordResumeWriter(csv_location=csv_path)
    tool = get_user_tool(user_id)
    out_dir = os.path.join(OUTPUTS_BASE, user_id)
    os.makedirs(out_dir, exist_ok=True)
    clean_output_dir(out_dir)
    cwd = os.getcwd(); os.chdir(out_dir)
    try:
        bot = Bot(writer=writer, llm=GeminiTool(model=req.model), tool=tool, auto_ingest=False)
        result = bot.generate_resume(req.job_description, output_basename="resume")
    finally:
        os.chdir(cwd)
    files = {"source": f"/download/{user_id}/resume{'.tex' if req.format.lower()=='latex' else '.docx'}"}
    pdf_path = os.path.join(out_dir, "resume.pdf")
    if os.path.isfile(pdf_path):
        files["pdf"] = f"/download/{user_id}/resume.pdf"
    return JSONResponse(content={"result": result, "files": files, "rows": row_count})

def sse_event(data: dict) -> bytes:
    import json as _json
    return f"data: {_json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")

@app.post("/generate-resume-stream/{user_id}")
async def generate_resume_stream(user_id: str, req: ResumeRequest):
    """Stream progress events for resume generation via Server-Sent Events (SSE)."""
    csv_path = _resolve_user_jobs_csv(user_id)
    writer = LatexResumeWriter(csv_location=csv_path) if req.format.lower() == "latex" else WordResumeWriter(csv_location=csv_path)
    tool = get_user_tool(user_id)
    out_dir = os.path.join(OUTPUTS_BASE, user_id)
    os.makedirs(out_dir, exist_ok=True)
    clean_output_dir(out_dir)
    # Pre-calc row count for early event
    row_count = None
    try:
        import pandas as pd
        row_count = len(pd.read_csv(csv_path))
    except Exception:
        pass
    bot = Bot(writer=writer, llm=GeminiTool(model=req.model), tool=tool, auto_ingest=False)

    def event_generator():
        try:
            # Run inside output dir so writer outputs land there
            cwd = os.getcwd(); os.chdir(out_dir)
            # Send initial CSV info event
            yield sse_event({"stage": "csv_info", "rows": row_count})
            for event in bot.generate_resume_progress(req.job_description, output_basename="resume"):
                # Normalize final file paths for client (match non-stream endpoint style)
                if event.get("stage") == "done":
                    source_name = f"resume{writer.file_ending}"
                    # Build file list dynamically to avoid broken pdf links
                    files = {"source": f"/download/{user_id}/{source_name}"}
                    if os.path.isfile(os.path.join(out_dir, "resume.pdf")):
                        files["pdf"] = f"/download/{user_id}/resume.pdf"
                    event["files"] = files
                yield sse_event(event)
            os.chdir(cwd)
        except Exception as e:
            yield sse_event({"stage": "error", "message": str(e)})

    # Explicit headers added because some environments / proxies may strip CORS headers on streaming responses
    sse_headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Allow-Methods": "*",
    }
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=sse_headers)

@app.get("/download/{user_id}/{filename}")
async def download_file(user_id: str, filename: str):
    # Security: basic path traversal guard
    if ".." in filename or filename.startswith('/'):
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = os.path.join(OUTPUTS_BASE, user_id, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)

@app.get("/users")
async def list_users():
    return {"users": list(USER_TOOLS.keys())}

@app.delete("/users/{user_id}")
async def clear_user(user_id: str):
    # Drop the user's collection and remove cache entry
    if user_id not in USER_TOOLS:
        raise HTTPException(status_code=404, detail="User not found")
    tool = USER_TOOLS.pop(user_id)
    try:
        tool._client.delete_collection(tool.collection_name)  # type: ignore[attr-defined]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete collection: {e}")
    return {"status": "deleted", "user_id": user_id}

# Convenience root
@app.get("/")
async def root():
    return {"message": "BetterResume API. Use /upload-jobs/{user_id} then /generate-resume/{user_id}."}
