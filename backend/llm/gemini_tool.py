import json
import os
import logging
import time
import threading
import random
from typing import Callable, Any

from langchain_core.messages import BaseMessage
from langchain.chat_models import init_chat_model
from .base import BaseLLM
from utils.file_io import load_prompt

class GeminiTool(BaseLLM):
    """
    A class that wraps around the ChatGemini client to provide additional functionality
    such as binding tools and invoking the model with messages.
    Attributes:
        client (ChatGemini): The ChatGemini client instance used for communication with the LLM.
        tools (list): A list of tools to be bound to the ChatGemini client.
    Methods:
        __init__(base_url: str, api_key: str, model: str, tools: list = None):
            Initializes the GeminiTool instance with the specified base URL, API key, model, and optional tools.
        bind_tools():
            Binds the specified tools to the ChatGemini client. Reassigns the client instance
            to ensure the tools are properly bound.
        invoke(messages: list[BaseMessage]) -> BaseMessage:
            Sends a list of messages to the ChatGemini client and returns the response.
    """
    def __init__(self, model: str, api_key: str = None, tools: list = None):
        super().__init__(tools=tools,model=model)
        api_key =  os.environ.get("GOOGLE_API_KEY", api_key)
        if not api_key:
            raise ValueError("API key must be provided or set in environment variable GOOGLE_API_KEY")
        os.environ["GOOGLE_API_KEY"] = api_key
        
        self.client = init_chat_model("google_genai:gemini-2.5-flash")
        self._logger = logging.getLogger("betterresume.llm")
     

    def bind_tools(self):
        """Bind provided tools to the Gemini chat client.

        Gemini's LangChain wrapper does not accept the OpenAI-style string value
        "required" for tool_choice. Passing that caused the earlier runtime error:
        `allowed_function_names` ... Found invalid: required. We simply bind the tools
        and let the model decide when (if) to call them.
        """
        if self.tools:
            self.client = self.client.bind_tools(self.tools, tool_choice="any")
            self._logger.info("Gemini bound tools count=%d", len(self.tools))

    def invoke(self, messages: list[BaseMessage]) -> BaseMessage:
        # Rate limited + retrying call
        self._logger.info("Gemini invoke messages=%d", len(messages))
        return _rate_limited_invoke(lambda: self.client.invoke(messages))


# ---- Concurrency and rate limiting with retries ----
_RPM = int(os.getenv("GEMINI_RPM", "60"))
_MAX_CONCURRENCY = int(os.getenv("GEMINI_MAX_CONCURRENCY", "4"))
_TPS = max(1, _RPM) / 60.0  # tokens (requests) per second


class _RateLimiter:
    def __init__(self, tps: float, max_concurrency: int):
        self.min_interval = 1.0 / float(tps)
        self._last = 0.0
        self._lock = threading.Lock()
        self._sema = threading.Semaphore(max_concurrency)

    def acquire(self):
        self._sema.acquire()
        with self._lock:
            now = time.time()
            wait = max(0.0, self._last + self.min_interval - now)
            if wait:
                time.sleep(wait)
            self._last = time.time()

    def release(self):
        self._sema.release()


_LIMITER = _RateLimiter(_TPS, _MAX_CONCURRENCY)


def _with_retries(call: Callable[[], Any], *, max_tries: int = 5, base_delay: float = 0.5):
    tries = 0
    while True:
        tries += 1
        try:
            return call()
        except Exception as e:
            # Retry on rate/quota/timeouts/transient 5xx
            msg = str(e).lower()
            retriable = any(x in msg for x in ("rate", "quota", "429", "busy", "timeout", "temporar", "deadline", "503", "unavailable"))
            if not retriable or tries >= max_tries:
                raise
            time.sleep(base_delay * (2 ** (tries - 1)) + random.uniform(0, 0.25))


def _rate_limited_invoke(call: Callable[[], Any]):
    _LIMITER.acquire()
    try:
        return _with_retries(call)
    finally:
        _LIMITER.release()
