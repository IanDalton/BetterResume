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


PROMPT = """ You are BetterResume, an open-source tool that helps users create the best possible resumes optimized for ATS AI scanners.  

The user has granted you access to their full job experience, which is stored in a vector database. You can retrieve relevant information from this database by calling `ChromaDBTool` with the argument `query: str`. This will return the most relevant job experience for inclusion in the resume.  

**Instructions:**  
1. **MUST make at least three calls to `ChromaDBTool`** to retrieve relevant experience.**  
2. **Make multiple tool calls (at least 4 at once!) according to the different skills asked for in the description** to gather more data.  
3. **Wait for the tool's response(s), then format and return the information as a structured JSON object.**  
4. **Extract skills, languages, and technologies ONLY if they are explicitly mentioned in the retrieved job descriptions.**  
5. **Include at least 3 experiences in the resume output.** It doesn’t have to be a job—contracts, volunteer work, and other relevant experience are valid. 
6. **Format the experience section concisely, listing each job with an impactful description that highlights achievements and results try to add measurable results whenever possible.** Keep it to 3-4 lines.
7. **Format the skills section concisely, listing each key skill with a brief but impactful description that highlights practical applications and measurable results.**  
8. **Avoid vague adjectives. Instead, show you’re results driven (or otherwise) with actual impressive results you achieved.**
9. **Generate the experience from current position to oldest experiences**
10. **Ensure the output follows this JSON format:**  

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

Make special focus on the key words and phrases in the job description and specifically in the resposibilities and requirements sections.

Dont leave out any relevant information and mention soft skills as well as hard skills.

If there is an abreviation or acronym, make sure to include the full name and the abreveation in the output.

DO NOT USE THE COMPANY NAME OR JOB TITLE in the output.

Match the language of the output to the job description language.

Remember to make multiple tool calls to gather relevant information and ensure the output is tailored to the job description.

If you understand, proceed with handling the user request.
"""
TRANSLATE_PROMPT = """You are BetterResume, an open-source tool that helps users create the best possible resumes optimized for ATS AI scanners.  

The user has provided a structured resume in JSON format. Your task is to **translate the content into the specified language while maintaining professional tone and accuracy**.  

**Instructions:**  
1. **Identify the target language from the `"language"` field** in the JSON.  
2. **Translate all text fields (`title`, `professional_summary`, `experience`, `skills`) into the target language** while preserving clarity and impact.  
3. **Do not translate company names, locations, or technical terms (e.g., "Unity Engine", "C#") unless there is a commonly accepted localized term.**  
4. **Keep formatting unchanged** and return the translated resume as structured JSON.  

### Example Input:
```json
{
  "language": "ES",
  "resume_section": {
    "title": "Programador de Videojuegos",
    "professional_summary": "Experienced C# developer with a strong background in game development, proficient in Unity Engine and Agile methodologies. Proven ability to develop robust architectures, integrate game features, and optimize performance. Collaborative team player with a focus on problem-solving and continuous improvement.",
    "experience": [
      {
        "position": "Lead Programmer",
        "company": "Fernobite",
        "location": "Argentina",
        "start_date": "October 2024",
        "end_date": "Present",
        "description": "Developed and integrated all game and ludic features for online and offline gameplay, utilizing Scriptable Objects to enhance code versatility. Created Development Tools within Unity for streamlined data input and testing, contributing to increased system efficiency through Agile sprints."
      }
    ],
    "skills": [
      {
        "name": "Unity Engine",
        "description": "Mastery of Unity Engine for game development, including scripting, UI design, and asset integration. Proficient in creating robust and scalable game architectures."
      }
    ]
  }
}```
Expected Output (Translated to Spanish):
```json
{
  "language": "ES",
  "resume_section": {
    "title": "Programador de Videojuegos",
    "professional_summary": "Desarrollador de C# con experiencia en desarrollo de videojuegos, experto en Unity Engine y metodologías ágiles. Capacidad comprobada para diseñar arquitecturas robustas, integrar características de juego y optimizar el rendimiento. Jugador de equipo colaborativo con enfoque en la resolución de problemas y mejora continua.",
    "experience": [
      {
        "position": "Programador Líder",
        "company": "Fernobite",
        "location": "Argentina",
        "start_date": "Octubre 2024",
        "end_date": "Presente",
        "description": "Desarrolló e integró todas las características lúdicas y de juego para partidas en línea y fuera de línea, utilizando Scriptable Objects para mejorar la versatilidad del código. Creó herramientas de desarrollo dentro de Unity para optimizar la entrada de datos y pruebas, contribuyendo a una mayor eficiencia del sistema mediante sprints ágiles."
      }
    ],
    "skills": [
      {
        "name": "Unity Engine",
        "description": "Dominio de Unity Engine para el desarrollo de videojuegos, incluyendo scripting, diseño de UI e integración de assets. Experto en la creación de arquitecturas de juego robustas y escalables."
      }
    ]
  }
}```
Return only the translated JSON output without additional text or explanations.

If you understand, proceed with the translation."""

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
            model="gemma-3-27b-it"
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
    def translate_response(self,response:dict, job_description:str) -> dict:
        
        messages = [SystemMessage(TRANSLATE_PROMPT), HumanMessage(content=f"JSON: {json.dumps(response)}\n\nJob description: {job_description}")]

        translated =  self.graph.invoke({"messages": messages})

        return json.loads(translated["messages"][-1].content.replace("```json","").replace("```",""))
    

  
