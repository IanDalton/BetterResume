from typing import Dict

from llm.vector_store import PGVectorStore

# Maintain a cache of user_id -> PGVectorStore (separate per-user stores)
USER_STORES: Dict[str, PGVectorStore] = {}
