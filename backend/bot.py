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



class State(TypedDict): messages: Annotated[list, add_messages]

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
        self.tool = tool or ChromaDBTool(persist_directory=persist_directory)

        if auto_ingest and jobs_csv and os.path.isfile(jobs_csv):
            try:
                data = CSVLoader(file_path=jobs_csv).load()
                # Create incremental ids based on current collection count
                try:
                    current = self.tool._collection.count()  # type: ignore[attr-defined]
                except Exception:
                    current = 0
                self.tool.add_documents(
                    [d.page_content for d in data],
                    [str(current + i) for i, _ in enumerate(data)],
                )
            except Exception as e:
                logging.warning(f"Bot auto_ingest failed for {jobs_csv}: {e}")

        self.llm_with_tools = llm.copy(tools=[self.tool])
        self.llm_with_tools.bind_tools()

        self.graph = self._create_graph()
        self.json_body = None
        self.writer = writer

    def _create_graph(self):
        def tools(state): return {"messages": [self.llm_with_tools.invoke(state["messages"]) ]}
        def chatbot(state): return {"messages": [self.llm.invoke(state["messages"]) ]}
        
        g=StateGraph(State)

        g.add_node("toolsBot",tools)
        g.add_edge(START,"toolsBot")
        g.add_node("tools",BasicToolNode(tools=[self.tool]))
        g.add_edge("toolsBot","tools")

        g.add_node("chatbot",chatbot)
        g.add_edge("tools","chatbot")
        g.add_edge("chatbot",END)

        
        return g.compile()

    def generate_resume(self, jd:str) -> Dict[str,Any]:
        #meta=JobParser.extract_language_and_title(jd)
        logging.info(f"Job Description: {jd}")
        res=self.graph.invoke({"messages":[SystemMessage(self.llm.JOB_PROMPT),HumanMessage(jd)]})
        logging.info(f"Resume: {res}")
        res = ResumeWriter.to_json(res["messages"][-1].content)
        logging.info(f"Resume JSON: {res}")
        if res["language"].lower() != "en":
            #res = self.graph.invoke({"messages":[SystemMessage(self.llm.TRANSLATE_PROMPT),HumanMessage(json.dumps(res))]})
            res = self.translate_resume(res)
            logging.info(f"Translated Resume: {res}")
        self.json_body = res
        self.writer.write(res,output="resume"+self.writer.file_ending,to_pdf=True)
        logging.info(f"Resume written to resume.{self.writer.file_ending}")
        return res

    
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
