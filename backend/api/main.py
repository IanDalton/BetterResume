import os
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from llm.chroma_db_tool import ChromaDBTool
from bot import Bot
from resume import LatexResumeWriter, WordResumeWriter
from llm.gemini_tool import GeminiTool
from typing import Dict

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
        USER_TOOLS[user_id] = ChromaDBTool(persist_directory="./chroma_db", collection_name=f"user_{user_id}")
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
    tmp_path = os.path.join("/tmp" if os.name != "nt" else ".", f"uploaded_jobs_{user_id}.csv")
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
    bot = Bot(writer=writer, llm=GeminiTool(model=req.model), tool=tool, auto_ingest=False)
    result = bot.generate_resume(req.job_description)
    return JSONResponse(content=result)

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
