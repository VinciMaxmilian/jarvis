import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from packages.agents.tools.executor import SystemToolExecutor
from packages.llm.base import LLMProvider
from packages.shared.settings import Settings
from apps.api.deps import _build_gemini
from packages.memory.factory import build_memory_system
from packages.mcp.client_manager import MCPClientManager
import json

async def main():
    settings = Settings()
    provider = _build_gemini(settings, "")
    memory = build_memory_system(provider)
    
    mcp_dir = Path(__file__).parent.parent / "mcp"
    mcp_manager = MCPClientManager(mcp_dir)
    await mcp_manager.discover_and_connect()
    
    executor = SystemToolExecutor(
        tavily_api_key="dummy",
        llm=provider,
        chat_history_store=memory.working,
        memory_vector_store=memory.knowledge._store,
        embed_llm=provider,
        mcp_manager=mcp_manager
    )
    
    specs = await executor.get_all_specs()
    print("Specs loaded:", len(specs))
    
    from packages.llm.gemini_provider import _strip_unsupported_schema
    
    for spec in specs:
        try:
            stripped = _strip_unsupported_schema(spec.input_schema)
            print(f"\nTool {spec.name} OK")
        except Exception as e:
            print(f"\nTool {spec.name} FAILED: {e}")
            
    await mcp_manager.close_all()

if __name__ == "__main__":
    asyncio.run(main())
