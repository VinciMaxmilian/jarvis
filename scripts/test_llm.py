import asyncio
import os
import sys
from pathlib import Path
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from packages.agents.tools.executor import SystemToolExecutor
from packages.llm.base import Message
from packages.shared.settings import Settings
from apps.api.deps import _build_gemini, _build_lmstudio
from packages.memory.factory import build_memory_system
from packages.mcp.client_manager import MCPClientManager

async def test_llm(provider_name, provider):
    print(f"\n--- Testing with {provider_name} ---")
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
    
    messages = [
        Message(role="system", content="Você é um assistente que DEVE usar a ferramenta executar_comando_cmd para listar arquivos quando pedido."),
        Message(role="user", content="Oi. Pode listar os arquivos na pasta de Documentos por favor?")
    ]
    
    try:
        completion = await provider.complete(messages=messages, tools=specs)
        print("Wants tools:", completion.wants_tools)
        if completion.wants_tools:
            for tc in completion.tool_calls:
                print(f"Tool call: {tc.name} args: {tc.arguments}")
        else:
            print("Response:", completion.text)
    except Exception as e:
        print(f"Error during completion: {e}")
        
    await mcp_manager.close_all()

async def main():
    settings = Settings()
    try:
        lm_studio = _build_lmstudio(settings, "")
        await test_llm("LM Studio", lm_studio)
    except Exception as e:
        print(f"LM Studio setup failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
