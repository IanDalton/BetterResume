import json
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict
from typing import Annotated, Any, Dict
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_community.document_loaders.csv_loader import CSVLoader

from llm.openai_tool import OpenAITool
from llm.chroma_db_tool import ChromaDBTool
from llm.basic_tool_node import BasicToolNode
from utils.file_io import load_prompt
from resume.parser import JobParser
from resume.writer import ResumeWriter
import config
from resume.base_writer import BaseWriter

JOB_PROMPT = load_prompt("job_prompt")
TRANSLATE_PROMPT = load_prompt("translation_prompt")

class State(TypedDict): messages: Annotated[list, add_messages]

class Bot:
    def __init__(self,writer:BaseWriter):
        self.llm = OpenAITool(**config.CONFIG['llm'])
        
        self.tool = ChromaDBTool(persist_directory=config.CONFIG['chroma']['persist_directory'])
        data = CSVLoader(file_path="jobs.csv").load()
        self.tool.add_documents([d.page_content for d in data],[str(i) for i,_ in enumerate(data)])


        self.llm_with_tools = OpenAITool(**config.CONFIG['llm'],tools=[self.tool])
        self.llm_with_tools.bind_tools()

        self.graph = self._create_graph()
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
        res=self.graph.invoke({"messages":[SystemMessage(JOB_PROMPT),HumanMessage(jd)]})
        res = ResumeWriter.to_json(res["messages"][-1].content)
        return self.writer.write(res,output="resume.docx",to_pdf=True)

    
    def translate_resume(self,r:dict)->dict:
        res=self.graph.invoke({"messages":[SystemMessage(TRANSLATE_PROMPT),HumanMessage(json.dumps(r))]})
        return ResumeWriter.to_json(res["messages"][-1].content)

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser();p.add_argument("--job",required=True);p.add_argument("--translate",action="store_true");a=p.parse_args()
    jd=open(a.job).read();b=Bot();out=b.generate_resume(jd);print(json.dumps(out,indent=2,ensure_ascii=False))
    if a.translate: print(json.dumps(b.translate_resume(out),indent=2,ensure_ascii=False))
