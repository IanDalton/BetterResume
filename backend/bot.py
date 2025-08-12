import json
import logging
import os
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict
from typing import Annotated, Any, Dict, Optional
from resume import WordResumeWriter
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_community.document_loaders.csv_loader import CSVLoader

from llm.openai_tool import OpenAITool
from llm.base import BaseLLM

from llm.gemini_tool import GeminiTool
from llm.chroma_db_tool import ChromaDBTool
from llm.basic_tool_node import BasicToolNode

from resume.parser import JobParser
from resume.writer import ResumeWriter
from resume.base_writer import BaseWriter
from utils.logging_utils import request_id_var, user_id_var, set_user_context



class State(TypedDict): 
    messages: Annotated[list, add_messages]
    user_id: str

class Bot:
    """
    A class to handle resume generation and translation using a combination of 
    language models, tools, and a state graph.
    Attributes:
        llm (OpenAITool): The primary language model tool for processing messages.
        tool (ChromaDBTool): A tool for managing and querying a ChromaDB database.
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
        tool: Optional[ChromaDBTool] = None,
        user_id: Optional[str] = None,
        auto_ingest: bool = True,
        jobs_csv: str = "jobs.csv",
        persist_directory: str = "./chroma_db",
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
        if user_id:
            persist_directory+=f"/{user_id}"
        self.tool = tool or ChromaDBTool(persist_directory=persist_directory)
        self.user_id = user_id
        self.logger = logging.getLogger("betterresume.bot")
        self.logger.info(
            "Bot init model=%s has_tool=%s auto_ingest=%s jobs_csv=%s user=%s",
            getattr(llm, "model", None), bool(tool), auto_ingest, jobs_csv, user_id,
        )

        if auto_ingest and jobs_csv and os.path.isfile(jobs_csv):
            try:
                # Clear any existing collection docs to avoid cross-run mixing
                try:
                    self.logger.info("Resetting Chroma collection for fresh ingest")
                    self.tool._client.delete_collection(self.tool.collection_name)  # type: ignore[attr-defined]
                    self.tool._collection = self.tool._client.get_or_create_collection(self.tool.collection_name)
                except Exception:
                    try:
                        self.tool._collection = self.tool._client.get_collection(name=self.tool.collection_name)
                    except Exception:
                        self.tool._collection = self.tool._client.create_collection(name=self.tool.collection_name)

                data = CSVLoader(file_path=jobs_csv).load()
                self.logger.info("Auto-ingesting %d rows from %s", len(data), jobs_csv)
                self.tool.add_documents(
                    [d.page_content for d in data],
                    [str(i) for i, _ in enumerate(data)],
                )
            except Exception as e:
                self.logger.warning("Auto-ingest failed for %s: %s", jobs_csv, e)

        self.llm_with_tools = llm.copy(tools=[self.tool])
        self.llm_with_tools.bind_tools()

        self.graph = self._create_graph()
        self.json_body = None
        self.writer = writer

    def _create_graph(self):
        def tools(state):
            return {"messages": [self.llm_with_tools.invoke(state["messages"]) ]}

        def chatbot(state):
            return {"messages": [self.llm.invoke(state["messages"]) ]}

        g = StateGraph(State)
        g.add_node("toolsBot", tools)
        g.add_edge(START, "toolsBot")
        g.add_node("tools", BasicToolNode(tools=[self.tool], require_tool=True))
        g.add_edge("toolsBot", "tools")
        g.add_node("chatbot", chatbot)
        g.add_edge("tools", "chatbot")
        g.add_edge("chatbot", END)
        return g.compile()

    def generate_resume(self, jd: str, output_basename: str = "resume") -> Dict[str, Any]:
        #meta=JobParser.extract_language_and_title(jd)
        if self.user_id:
            set_user_context(self.user_id)
        self.logger.info("Generate resume start; jd_chars=%d", len(jd or ""))
        res=self.graph.invoke({"messages":[SystemMessage(self.llm.JOB_PROMPT),HumanMessage(jd)]})
        self.logger.info("Graph returned; messages=%d", len(res.get("messages", [])))
        res = ResumeWriter.to_json(res["messages"][-1].content)
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
        parsed = ResumeWriter.to_json(res["messages"][-1].content)
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
