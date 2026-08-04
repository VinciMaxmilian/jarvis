import asyncio
import os
import sys

# Ensure the root of the repo is in the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from packages.agents.tools.executor import SystemToolExecutor
from packages.llm.base import LLMProvider
from packages.shared.ports import VectorStore

class DummyLLM(LLMProvider):
    async def complete(self, *args, **kwargs):
        pass
    async def embed(self, *args, **kwargs):
        return [[0.1]*768]

class DummyStore(VectorStore):
    async def search(self, *args, **kwargs):
        return []
    async def upsert(self, *args, **kwargs):
        pass
    async def delete(self, *args, **kwargs):
        pass

async def main():
    executor = SystemToolExecutor(
        tavily_api_key="dummy",
        llm=DummyLLM(),
        chat_history_store=DummyStore(),
        memory_vector_store=DummyStore(),
    )
    result = await executor.execute("knowledge_save", {"fato": "O usuário gosta de vermelho.", "categoria": "preferencias_usuario"})
    print("RESULT:", result)

if __name__ == "__main__":
    asyncio.run(main())
