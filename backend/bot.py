import json
import logging
import os

from langgraph.graph import StateGraph, START, END

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
        self.tool = None
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

        if auto_ingest and jobs_csv and os.path.isfile(jobs_csv):
            try:
                # Remove any existing vectors for this user to avoid cross-run mixing
                try:
                    self.logger.info("Resetting pgvector rows for fresh ingest user=%s", self.user_id)
                    self.tool.delete_user_documents(self.user_id)
                except Exception:
                    pass

                data = CSVLoader(file_path=jobs_csv).load()
                ids = [f"{self.user_id}_{i}" for i in range(len(data))]
                self.logger.info("Auto-ingesting %d rows from %s for user=%s", len(data), jobs_csv, self.user_id)
                self.tool.add_documents(
                    [d.page_content for d in data],
                    ids,
                    user_id=self.user_id,
                )
            except Exception as e:
                self.logger.warning("Auto-ingest failed for %s: %s", jobs_csv, e)

        

        self.graph = self._create_graph()
        self.json_body = None
        self.writer = writer

    def _create_graph(self):
        async def chatbot(state: State):
            return await self.llm.ainvoke(state)
        def has_tool_call_orchestrator(state: State) -> bool:
            messages = state["messages"]
            msg = messages[-1] if messages else None
            if "tool_call" in msg.additional_kwargs:
                return True
            return False
        async def tool_call(state: State):
            return await self.tool_node.ainvoke(state)
        
        g = StateGraph(State)
        g.add_node("agent", chatbot )
        g.add_node("toolsBot", tool_call )

        g.add_edge(START, "agent")
        g.add_conditional_edges("agent", has_tool_call_orchestrator,{
            True: "toolsBot",
            False: END,
        })
        g.add_edge("toolsBot", "agent")

        
        return g.compile()

    async def generate_resume(self, jd: str, output_basename: str = "resume") -> Dict[str, Any]:
        #meta=JobParser.extract_language_and_title(jd)
        if self.user_id:
            set_user_context(self.user_id)
        self.logger.info("Generate resume start; jd_chars=%d", len(jd or ""))
        res=await self.graph.ainvoke({"messages":[SystemMessage(self.llm.JOB_PROMPT),HumanMessage(jd)]})
        self.logger.info("Graph returned; messages=%d", len(res.get("messages", [])))
        last_content = res["messages"][-1].content

        # If a structured output format (Pydantic) is provided, try to coerce into that object.
        parsed_obj = None
        if getattr(self.llm, "output_format", None):
            try:
                cleaned = ResumeWriter.clean_tools_output(last_content)
                model_cls = (
                    self.llm.output_format
                    if isinstance(self.llm.output_format, type)
                    else self.llm.output_format.__class__
                )
                # Prefer Pydantic v2 API if available
                if hasattr(model_cls, "model_validate_json"):
                    parsed_obj = model_cls.model_validate_json(cleaned)
                else:
                    # Fallback for Pydantic v1
                    parsed_obj = model_cls.parse_raw(cleaned)
            except Exception as e:
                self.logger.warning("Structured parse failed, falling back to JSON: %s", e)

        # Convert to plain dict for downstream usage
        if parsed_obj is not None:
            try:
                res = parsed_obj.model_dump()  # pydantic v2
            except Exception:
                res = parsed_obj.dict()        # pydantic v1
        else:
            res = ResumeWriter.to_json(last_content)
        self.logger.info("Parsed resume json; language=%s", res.get("language"))
        if res["language"].lower() != "en":
            #res = self.graph.invoke({"messages":[SystemMessage(self.llm.TRANSLATE_PROMPT),HumanMessage(json.dumps(res))]})
            res = self.translate_resume(res)
            self.logger.info("Translation applied; language=%s", res.get("language"))
        self.json_body = res
        try:
            output_name = f"{output_basename}{self.writer.file_ending}"
            self.writer.write(res, output=output_name, to_pdf=True)
            self.logger.info("Files written output=%s (and PDF)", output_name)
        except Exception as e:
            self.logger.exception("Failed to write resume files: %s", e)
        return res

    def generate_resume_progress(self, jd: str, output_basename: str = "resume"):
        """Generator yielding progress events (stage, optional payload)."""
        if self.user_id:
            set_user_context(self.user_id)
        self.logger.info("Streaming: invoking graph")
        yield {"stage": "invoking_graph", "message": "Invoking LLM graph"}
        res = self.graph.invoke({"messages":[SystemMessage(self.llm.JOB_PROMPT),HumanMessage(jd)]})
        self.logger.info("Streaming: graph complete")
        yield {"stage": "graph_complete", "message": "Graph completed"}
        last_content = res["messages"][-1].content
        parsed_obj = None
        if getattr(self.llm, "output_format", None):
            try:
                cleaned = ResumeWriter.clean_tools_output(last_content)
                model_cls = (
                    self.llm.output_format
                    if isinstance(self.llm.output_format, type)
                    else self.llm.output_format.__class__
                )
                if hasattr(model_cls, "model_validate_json"):
                    parsed_obj = model_cls.model_validate_json(cleaned)
                else:
                    parsed_obj = model_cls.parse_raw(cleaned)
            except Exception as e:
                self.logger.warning("Structured parse failed (stream), falling back to JSON: %s", e)

        if parsed_obj is not None:
            try:
                parsed = parsed_obj.model_dump()
            except Exception:
                parsed = parsed_obj.dict()
        else:
            parsed = ResumeWriter.to_json(last_content)
        self.logger.info("Streaming: parsed language=%s", parsed.get("language"))
        yield {"stage": "parsed", "message": "Initial resume parsed", "data": {"language": parsed.get("language")}}
        if parsed.get("language", "").lower() != "en":
            self.logger.info("Streaming: translating non-EN -> EN")
            yield {"stage": "translating", "message": "Translating resume"}
            parsed = self.translate_resume(parsed)
            self.logger.info("Streaming: translated language=%s", parsed.get("language"))
            yield {"stage": "translated", "message": "Translation complete", "data": {"language": parsed.get("language")}}
        self.json_body = parsed
        self.logger.info("Streaming: writing files")
        yield {"stage": "writing_file", "message": "Writing resume file"}
        out_name = f"{output_basename}{self.writer.file_ending}"
        try:
            self.writer.write(parsed, output=out_name, to_pdf=True)
            yield {"stage": "done", "message": "Resume generation complete", "result": parsed, "files": {"source": out_name, "pdf": f"{output_basename}.pdf"}}
        except Exception as e:
            self.logger.exception("Streaming: write failed: %s", e)
            yield {"stage": "error", "message": f"Failed writing resume: {e}"}

    
    def translate_resume(self,r:dict)->dict:
        if isinstance(r, dict):
            r = str(r)

        res=self.llm.invoke([SystemMessage(self.llm.TRANSLATE_PROMPT),HumanMessage(r)])
        return ResumeWriter.to_json(res.content)

if __name__=="__main__":
    import argparse

    p=argparse.ArgumentParser();p.add_argument("--job",required=True);p.add_argument("--translate",action="store_true");a=p.parse_args()
    jd=open(a.job).read();b=Bot(writer=WordResumeWriter());out=b.generate_resume(jd);print(json.dumps(out,indent=2,ensure_ascii=False))
    if a.translate: print(json.dumps(b.translate_resume(out),indent=2,ensure_ascii=False))
