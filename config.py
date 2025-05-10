from typing import Dict

CONFIG: Dict = {
    "llm": {
        "base_url": "http://localhost:1234/v1", # replace with your LLM's API URL. if using openai, leave None
        "api_key": "your_api_key_here",
        "model": "gemma-3-27b-it"
    },
    "chroma": {
        "persist_directory": "./chroma_db"
    }
}