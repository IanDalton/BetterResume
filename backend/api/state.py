from typing import Dict
from llm.pg_vector_tool import PGVectorTool

# Maintain a cache of user_id -> PGVectorTool (separate per-user tools)
USER_TOOLS: Dict[str, PGVectorTool] = {}
