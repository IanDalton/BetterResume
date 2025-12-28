import json
import logging
import os

from langgraph.graph import StateGraph, START, END

import asyncio
from typing import Annotated, Any, Dict, Optional
from resume import WordResumeWriter
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_community.document_loaders.csv_loader import CSVLoader
from llm.base import BaseLLM
from llm.basic_tool_node import BasicToolNode
from llm.state import State

from resume.parser import JobParser
from resume.writer import ResumeWriter
from resume.base_writer import BaseWriter
from utils.logging_utils import request_id_var, user_id_var, set_user_context
from models.resume import ResumeOutputFormat
from llm.pg_vector_tool import PGVectorTool





class Bot:
    """
    A class to handle resume generation and translation using a combination of 
    language models, tools, and a state graph.
    Attributes:
        llm (OpenAITool): The primary language model tool for processing messages.
        tool (PGVectorTool): A tool for managing and querying pgvector-backed embeddings in Postgres.
        llm_with_tools (OpenAITool): A language model tool bound with additional tools.
        graph (StateGraph): A compiled state graph for managing the flow of operations.
        json_body (dict): The JSON representation of the generated resume.
        writer (BaseWriter): An instance of a writer class for outputting resumes.
    Methods:
        generate_resume(jd: str) -> Dict[str, Any]:
            Generates a resume based on the provided job description (jd).
            Returns the resume in a specified format (e.g., .docx, .pdf).
        translate_resume(r: dict) -> dict:
            Translates the given resume dictionary (r) into another language.
            Returns the translated resume as a dictionary.
    """
    def __init__(
        self,
        writer: BaseWriter,
        llm: BaseLLM,
        tool: Optional[PGVectorTool] = None,
        user_id: Optional[str] = None,
        auto_ingest: bool = True,
        jobs_csv: str = "jobs.csv",
    ):
        """Initialize Bot.

        Args:
            writer: Concrete resume writer.
            llm: LLM implementation.
            tool: Optional existing ChromaDBTool instance (reuse across calls, e.g., API).
            auto_ingest: If True, loads jobs_csv into the collection (if file exists).
            jobs_csv: Path to CSV to ingest.
            persist_directory: Directory for Chroma persistence when creating new tool.
        """
        self.llm = llm
        self.tool: Optional[PGVectorTool] = tool
        if not self.tool and self.llm.get_tools():
            self.tool = self.llm.get_tools()[0]

        # Always respect injected tool (API supplies per-user tool with isolated persist+collection)
        # Only create a new one if not provided.
        self.tool_node = BasicToolNode(tools=self.llm.get_tools())
        self.user_id = user_id
        self.logger = logging.getLogger("betterresume.bot")
        self.logger.info(
            "Bot init model=%s has_tool=%s auto_ingest=%s jobs_csv=%s user=%s collection=%s",
            getattr(llm, "model", None), bool(self.tool), auto_ingest, jobs_csv, user_id, getattr(self.tool, "collection_name", "?"),
        )

        self._auto_ingest_task = None
        if auto_ingest and jobs_csv and os.path.isfile(jobs_csv):
            self._start_auto_ingest(jobs_csv)

        
        self.json_body = None
        self.writer = writer

    def _start_auto_ingest(self, jobs_csv: str):
        """Kick off auto-ingest synchronously or as a background task, depending on loop state."""
        if not self.tool:
            self.logger.warning("Auto-ingest skipped: tool missing")
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop; run to completion.
            asyncio.run(self._auto_ingest_jobs(jobs_csv))
            self._auto_ingest_task = None
            return
        # Running loop; schedule background task.
        self._auto_ingest_task = loop.create_task(self._auto_ingest_jobs(jobs_csv))

    async def _auto_ingest_jobs(self, jobs_csv: str):
        try:
            self.logger.info("Resetting pgvector rows for fresh ingest user=%s", self.user_id)
            try:
                await self.tool.adelete_user_documents(self.user_id)
            except Exception:
                pass

            data = CSVLoader(file_path=jobs_csv).load()
            ids = [f"{self.user_id}_{i}" for i in range(len(data))]
            self.logger.info("Auto-ingesting %d rows from %s for user=%s", len(data), jobs_csv, self.user_id)
            await self.tool.aadd_documents(
                [d.page_content for d in data],
                ids,
                user_id=self.user_id,
            )
        except Exception as e:
            self.logger.warning("Auto-ingest failed for %s: %s", jobs_csv, e)

    
    async def generate_resume(self, jd: str, output_basename: str = "resume") -> ResumeOutputFormat:
        #meta=JobParser.extract_language_and_title(jd)
        if self._auto_ingest_task:
            await self._auto_ingest_task
        if self.user_id:
            set_user_context(self.user_id)
        else:
            raise ValueError("user_id is required to generate a resume")
        self.logger.info("Generate resume start; jd_chars=%d", len(jd or ""))
        res = await self.llm.ainvoke({
            "messages": [SystemMessage(self.llm.JOB_PROMPT), HumanMessage(jd)],
            "user_id": self.user_id,
        })
        self.logger.info("Graph returned; messages=%d", len(res.get("messages", [])))
        resume:ResumeOutputFormat = res["structured_response"]

        if resume.language.lower() != "en":
            #res = self.graph.invoke({"messages":[SystemMessage(self.llm.TRANSLATE_PROMPT),HumanMessage(json.dumps(res))]})
            resume = await self.translate_resume(resume, jd)
            self.logger.info("Translation applied; language=%s", resume.language)
            
        self.json_body = resume.model_dump() 
        # TODO: Store files in db
        return resume

    async def generate_resume_progress(self, jd: str):
        """Async generator yielding progress events; leaves file creation to API layer."""
        # Ensure any background ingest completes
        if self._auto_ingest_task:
            try:
                await self._auto_ingest_task
            except Exception:
                pass
        if self.user_id:
            set_user_context(self.user_id)
        else:
            raise ValueError("user_id is required to generate a resume")

        self.logger.info("Streaming: invoking LLM")
        yield {"stage": "invoking_llm", "message": "Invoking LLM"}
        res = await self.llm.ainvoke({
            "messages": [SystemMessage(self.llm.JOB_PROMPT), HumanMessage(jd)],
            "user_id": self.user_id,
        })
        self.logger.info("Streaming: LLM complete; messages=%d", len(res.get("messages", [])))
        resume: ResumeOutputFormat = res["structured_response"]
        yield {"stage": "parsed", "message": "Initial resume parsed", "data": {"language": getattr(resume, "language", None)}}

        if (getattr(resume, "language", "") or "").lower() != "en":
            self.logger.info("Streaming: translating non-EN -> EN")
            yield {"stage": "translating", "message": "Translating resume"}
            resume = await self.translate_resume(resume, jd)
            yield {"stage": "translated", "message": "Translation complete", "data": {"language": getattr(resume, "language", None)}}

        self.json_body = resume.model_dump()
        self.logger.info("Streaming: done")
        yield {"stage": "done", "message": "Resume generation complete", "result": resume}

    async def translate_resume(self,r:ResumeOutputFormat, original_jd:str)->ResumeOutputFormat:
        if isinstance(r, dict):
            r = str(r)

        res = await self.llm.ainvoke({
            "messages": [SystemMessage(self.llm.TRANSLATE_PROMPT), HumanMessage(original_jd), HumanMessage(r.model_dump_json())],
            "user_id": self.user_id,
        })
        return res["structured_response"]

if __name__=="__main__":
    import argparse

    p=argparse.ArgumentParser();p.add_argument("--job",required=True);p.add_argument("--translate",action="store_true");a=p.parse_args()
    jd=open(a.job).read();b=Bot(writer=WordResumeWriter())
    out=asyncio.run(b.generate_resume(jd))
    print(json.dumps(out,indent=2,ensure_ascii=False))
    if a.translate: print(json.dumps(b.translate_resume(out),indent=2,ensure_ascii=False))
