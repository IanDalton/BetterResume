from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict
from typing import Annotated
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage
from langchain_openai.chat_models.base import ChatOpenAI
from langchain_community.document_loaders.csv_loader import CSVLoader

from llm.chromaDBTool import ChromaDBTool
from llm.basicToolNode import BasicToolNode
import json


PROMPT = """You are BetterResume, an open-source tool that helps users create the best possible resumes optimized for ATS AI scanners.  

The user has granted you access to their full job experience, which is stored in a vector database. You can retrieve relevant information from this database by calling `ChromaDBTool` with the argument `query: str`. This will return the most relevant job experience for inclusion in the resume.  

**Instructions:**  
1. **Make at least one call to `ChromaDBTool`** to retrieve relevant experience.  
2. **Make multiple tool calls (at least 4!) according to the different skills asked for in the description** to gather more data.  
3. **Wait for the tool's response(s), then format and return the information as a structured JSON object.**  
4. **Extract skills, languages, and technologies ONLY if they are explicitly mentioned in the retrieved job descriptions.**  
5. **Include at least 3 experiences in the resume output.** It doesnt have to be a job, can be other stuf like contract, volunteer, etc.
6. **Ensure the output follows this JSON format:**  

```json
{
  "language": "ES/EN/FR/DE/IT/PT" -> Select the correct language,
  "resume_section": {
    "title": "Title describing the job that the user is applying for",
    "experience": [
      {
        "position": "Job Title",
        "company": "Company Name",
        "location": "Location",
        "start_date": "Month Year",
        "end_date": "Month Year or Present",
        "description": "Detailed job description and achievements."
      }
    ],
    "skills": {
      "languages": ["List of programming languages"],
      "databases": ["List of databases"],
      "tools_and_technologies": ["List of tools, frameworks, and methodologies"]
    }
  }
}
```
Do not include additional text, explanations, or formatting outside of the JSON output.

Change the experience description if you see fit, but keep the main points as long as they are relevant to the job description.

Change the language of the description to match the language of the job description.

Do not include languages that are not implied by the database query.

Use keywords from the job description to extract relevant skills, languages, and technologies.

Ensure consistency in date formatting and job descriptions to maintain a professional resume output.

If you understand, proceed with handling the user request.
"""

PROMPT = """ You are BetterResume, an open-source tool that helps users create the best possible resumes optimized for ATS AI scanners.  

The user has granted you access to their full job experience, which is stored in a vector database. You can retrieve relevant information from this database by calling `ChromaDBTool` with the argument `query: str`. This will return the most relevant job experience for inclusion in the resume.  

**Instructions:**  
1. **Make at least one call to `ChromaDBTool`** to retrieve relevant experience.  
2. **Make multiple tool calls (at least 4!) according to the different skills asked for in the description** to gather more data.  
3. **Wait for the tool's response(s), then format and return the information as a structured JSON object.**  
4. **Extract skills, languages, and technologies ONLY if they are explicitly mentioned in the retrieved job descriptions.**  
5. **Include at least 3 experiences in the resume output.** It doesn’t have to be a job—contracts, volunteer work, and other relevant experience are valid. 
6. **Format the experience section concisely, listing each job with a brief but impactful description that highlights achievements and results.** 
6. **Format the skills section concisely, listing each key skill with a brief but impactful description that highlights practical applications and measurable results.**  
7. **Ensure the output follows this JSON format:**  

```json
{
  "language": "ES/EN/FR/DE/IT/PT",
  "resume_section": {
    "title": "Title describing the job that the user is applying for",
    "professional_summary": "Brief summary of the user's professional background and key achievements relevant to the job.",
    "experience": [
      {
        "position": "Job Title",
        "company": "Company Name",
        "location": "Location",
        "start_date": "Month Year",
        "end_date": "Month Year or Present",
        "description": "Detailed job description and achievements."
      }
    ],
    "skills": [
      {
        "name": "Skill Name",
        "description": "Short, results-driven explanation of expertise and impact."
      }
    ]
  }
}
Do not include additional text, explanations, or formatting outside of the JSON output.

Ensure that the skills section follows the format of impactful, results-oriented descriptions, e.g.:

Data Engineering – Built scalable ETL pipelines using Python and SQL, optimizing data processing speeds by 40%.

Project & Team Management – Led a 5-person team in Agile development, delivering a client application 20% ahead of schedule.

Cloud & DevOps – Deployed AI-driven models on AWS, reducing inference time by 30%.

Adapt experience descriptions to emphasize achievements, impact, and relevance to the job description.

Match the language of the output to the job description language.

If you understand, proceed with handling the user request.
"""


class State(TypedDict):
    # Messages have the type "list". The `add_messages` function
    # in the annotation defines how this state key should be updated
    # (in this case, it appends messages to the list, rather than overwriting them)
    messages: Annotated[list, add_messages]



# The first argument is the unique node name
# The second argument is the function or object that will be called whenever
# the node is used.


class Bot:
    def __init__(self):
        self.llm = ChatOpenAI(
            base_url="http://localhost:1234/v1",
            api_key="not_needed",
            model="gemma-2-27b-it"
        )

        self.tool = ChromaDBTool()
        loader = CSVLoader(
            file_path="jobs.csv"
        )
        data = loader.load()
        self.tool.add_documents([d.page_content for d in data], [str(i)
                                                                 for i in range(len(data))])

        self.llm = self.llm.bind_tools([self.tool])
        self.graph = self.create_graph()

    

    def create_graph(self):
        def chatbot(state: State):
            print('chatbot message')
            return {"messages": [self.llm.invoke(state["messages"])]}
        
        
        graph_builder = StateGraph(State)

        graph_builder.add_node("chatbot", chatbot)
        graph_builder.add_edge(START, "chatbot")

        graph_builder.add_node("tools", BasicToolNode(tools=[self.tool]))
        graph_builder.add_edge("tools", "chatbot")
        def route_tools(
            state: State
        ):
            if isinstance(state, list):
                message = state[-1]
            elif messages := state.get("messages", []):
                message = messages[-1]
            else:
                raise ValueError("No message found in input")
            if hasattr(message, "tool_calls") and len(message.tool_calls) > 0:
                return "tools"
            return END
            
        
        graph_builder.add_conditional_edges(
            "chatbot", route_tools, {"tools": "tools", END: END})
        
        return graph_builder.compile()
    def _generate_response(self,job_descripton:str):
        messages = [SystemMessage(content=PROMPT), HumanMessage(content=job_descripton)]
        return self.graph.invoke({"messages": messages})
    def generate_response(self,job_descripton:str) -> dict:
        response = self._generate_response(job_descripton)
        return json.loads(response["messages"][-1].content.replace("```json","").replace("```",""))
    

  
