import os
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from llm.chroma_db_tool import ChromaDBTool
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

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/upload-jobs/{user_id}")
async def upload_jobs(user_id: str, file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv")
    contents = await file.read()
    tmp_path = os.path.join(UPLOADS_BASE, f"uploaded_jobs_{user_id}.csv")
    with open(tmp_path, "wb") as f:
        f.write(contents)
    tool = get_user_tool(user_id)
    try:
        import pandas as pd  # optional for validation
        try:
            df = pd.read_csv(tmp_path)
            rows = len(df)
        except Exception:
            rows = None
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
        return {"status": "ok", "rows_ingested": rows or len(data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate-resume/{user_id}")
async def generate_resume(user_id: str, req: ResumeRequest):
    writer = LatexResumeWriter() if req.format.lower() == "latex" else WordResumeWriter()
    tool = get_user_tool(user_id)
    # Ensure per-user output directory (persistent)
    out_dir = os.path.join(OUTPUTS_BASE, user_id)
    os.makedirs(out_dir, exist_ok=True)
    cwd = os.getcwd()
    os.chdir(out_dir)
    try:
        bot = Bot(writer=writer, llm=GeminiTool(model=req.model), tool=tool, auto_ingest=False)
        result = bot.generate_resume(req.job_description, output_basename="resume")
    finally:
        os.chdir(cwd)
    files = {"source": f"/download/{user_id}/resume{'.tex' if req.format.lower()=='latex' else '.docx'}"}
    # Only attach PDF link if it exists (graceful fallback for word w/out PDF conversion)
    pdf_path = os.path.join(out_dir, "resume.pdf")
    if os.path.isfile(pdf_path):
        files["pdf"] = f"/download/{user_id}/resume.pdf"
    result_meta = {"result": result, "files": files}
    return JSONResponse(content=result_meta)

def sse_event(data: dict) -> bytes:
    import json as _json
    return f"data: {_json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")

@app.post("/generate-resume-stream/{user_id}")
async def generate_resume_stream(user_id: str, req: ResumeRequest):
    """Stream progress events for resume generation via Server-Sent Events (SSE)."""
    writer = LatexResumeWriter() if req.format.lower() == "latex" else WordResumeWriter()
    tool = get_user_tool(user_id)
    out_dir = os.path.join(OUTPUTS_BASE, user_id)
    os.makedirs(out_dir, exist_ok=True)
    bot = Bot(writer=writer, llm=GeminiTool(model=req.model), tool=tool, auto_ingest=False)

    def event_generator():
        try:
            # Run inside output dir so writer outputs land there
            cwd = os.getcwd(); os.chdir(out_dir)
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
