import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from packages.agents.tools.executor import SystemToolExecutor
from packages.llm.base import LLMProvider
from packages.shared.settings import Settings
from apps.api.deps import _build_gemini
from packages.memory.factory import build_memory_system

async def main():
    settings = Settings()
    provider = _build_gemini(settings, "")
    memory = build_memory_system(provider)
    
    # We don't have agno_knowledge in this test script, but we can test memory_store fallback.
    executor = SystemToolExecutor(
        tavily_api_key="dummy",
        llm=provider,
        chat_history_store=memory.working,
        memory_vector_store=memory.knowledge._store,
        embed_llm=provider
    )
    
    result = await executor.execute("search_memory", {"query": "Qual cor eu gosto mesmo?", "limit": 5})
    for m in result.get("matches", []):
        print(f"[{m['source']}] score={m['score']:.4f}: {m['text']}")

if __name__ == "__main__":
    asyncio.run(main())
