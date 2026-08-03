"""Executor central de tools do agente.

Implementa ToolExecutor (packages/shared/ports.py) e agrega `web_search` e `search_memory`.
"""

from __future__ import annotations

from typing import Any
import httpx
import asyncio
from packages.shared.contracts import ToolSpec
from packages.shared.ports import ToolNotFound, VectorStore
from packages.llm.base import LLMProvider

TAVILY_SEARCH_SPEC = ToolSpec(
    name="web_search",
    description=(
        "Busca informações na web usando Tavily. Retorna resultados relevantes "
        "com título, URL e conteúdo resumido. Use quando precisar de informações "
        "atualizadas ou que não estejam na base de conhecimento."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Termo de busca",
            },
            "max_results": {
                "type": "integer",
                "description": "Número máximo de resultados (1-10)",
                "default": 5,
            },
        },
        "required": ["query"],
    },
    idempotent=True,
    requires_approval=False,
)

SEARCH_MEMORY_SPEC = ToolSpec(
    name="search_memory",
    description=(
        "Busca informações no histórico de conversas passadas usando busca vetorial semântica. "
        "Use esta tool quando o usuário fizer referência a algo que foi discutido anteriormente ou "
        "pedir para resgatar dados do passado."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Termo de busca semântica para buscar no histórico",
            },
            "limit": {
                "type": "integer",
                "description": "Número máximo de mensagens a recuperar",
                "default": 5,
            },
        },
        "required": ["query"],
    },
    idempotent=True,
    requires_approval=False,
)

CRIAR_SERVIDOR_MCP_SPEC = ToolSpec(
    name="criar_servidor_mcp",
    description=(
        "Cria um novo servidor MCP (Model Context Protocol) na pasta mcp/ para ensinar uma nova habilidade ao Jarvis. "
        "Use esta ferramenta quando o usuário pedir para você aprender a fazer algo novo ou integrar com uma nova API. "
        "Você DEVE escrever o código completo (em Python) para o arquivo main.py que usará a biblioteca FastMCP."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "nome": {
                "type": "string",
                "description": "Nome da pasta do novo servidor MCP (ex: mcp_clima, nas_smb)"
            },
            "codigo_main_py": {
                "type": "string",
                "description": "O código Python completo para o arquivo main.py usando FastMCP"
            }
        },
        "required": ["nome", "codigo_main_py"]
    },
    idempotent=False,
    requires_approval=True
)

def _as_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, (float, str)):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default
    return default


class SystemToolExecutor:
    """ToolExecutor com as tools do sistema."""

    def __init__(
        self, 
        tavily_api_key: str, 
        llm: LLMProvider, 
        chat_history_store: VectorStore,
        mcp_manager: Any | None = None
    ) -> None:
        self._tavily_api_key = tavily_api_key
        self._llm = llm
        self._history_store = chat_history_store
        self._mcp_manager = mcp_manager
        
        self._tools: dict[str, ToolSpec] = {
            TAVILY_SEARCH_SPEC.name: TAVILY_SEARCH_SPEC,
            SEARCH_MEMORY_SPEC.name: SEARCH_MEMORY_SPEC,
            CRIAR_SERVIDOR_MCP_SPEC.name: CRIAR_SERVIDOR_MCP_SPEC,
        }

    async def get_all_specs(self) -> list[ToolSpec]:
        """Devolve as specs do sistema e dos MCPs."""
        specs = list(self._tools.values())
        if self._mcp_manager:
            mcp_specs = await self._mcp_manager.get_tools_specs()
            for s in mcp_specs:
                specs.append(ToolSpec(
                    name=s["name"],
                    description=s["description"],
                    input_schema=s["input_schema"],
                    idempotent=False,
                    requires_approval=False
                ))
        return specs

    def specs(self) -> list[ToolSpec]:
        """Síncrono (legado). Apenas system tools."""
        return list(self._tools.values())

    def has(self, name: str) -> bool:
        return name in self._tools

    async def execute(
        self, name: str, arguments: dict[str, object], dry_run: bool = False
    ) -> dict[str, object]:
        if self.has(name):
            if name == "web_search":
                return await self._web_search(
                    query=str(arguments.get("query", "")),
                    max_results=_as_int(arguments.get("max_results"), default=5),
                    dry_run=dry_run,
                )
                
            if name == "search_memory":
                return await self._search_memory(
                    query=str(arguments.get("query", "")),
                    limit=_as_int(arguments.get("limit"), default=5),
                    dry_run=dry_run,
                )
                
            if name == "criar_servidor_mcp":
                return await self._criar_servidor_mcp(
                    nome=str(arguments.get("nome", "")),
                    codigo_main_py=str(arguments.get("codigo_main_py", "")),
                    dry_run=dry_run
                )
                
        if self._mcp_manager and name in self._mcp_manager.tool_routes:
            if dry_run:
                return {"dry_run": True, "action": "mcp_call", "tool": name, "args": arguments}
            return await self._mcp_manager.call_tool(name, arguments)

        raise ToolNotFound(name)

    async def _web_search(
        self, query: str, max_results: int = 5, dry_run: bool = False
    ) -> dict[str, object]:
        if dry_run:
            return {
                "dry_run": True,
                "action": "web_search",
                "query": query,
                "max_results": max_results,
            }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self._tavily_api_key,
                    "query": query,
                    "max_results": min(max_results, 10),
                    "include_answer": True,
                    "include_raw_content": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results: list[dict[str, Any]] = []
        for r in data.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
                "score": r.get("score", 0),
            })

        return {
            "answer": data.get("answer", ""),
            "results": results,
            "query": query,
        }

    async def _search_memory(
        self, query: str, limit: int = 5, dry_run: bool = False
    ) -> dict[str, object]:
        if dry_run:
            return {
                "dry_run": True,
                "action": "search_memory",
                "query": query,
                "limit": limit,
            }
            
        try:
            vetores = await self._llm.embed([query])
            matches = await self._history_store.search(
                vetores[0], namespace="chat_history", limit=limit
            )
            
            results = []
            for match in matches:
                results.append({
                    "score": match.score,
                    "text": match.record.text,
                    "date": match.record.metadata.get("updated_at", ""),
                })
                
            return {
                "query": query,
                "matches": results,
            }
        except Exception as exc:
            return {"error": str(exc)}

    async def _criar_servidor_mcp(self, nome: str, codigo_main_py: str, dry_run: bool = False) -> dict[str, object]:
        if dry_run:
            return {
                "dry_run": True,
                "action": "criar_servidor_mcp",
                "nome": nome,
                "tamanho_codigo": len(codigo_main_py)
            }
            
        try:
            import os
            from pathlib import Path
            mcp_dir = Path(__file__).parent.parent.parent.parent / "mcp" / nome
            mcp_dir.mkdir(parents=True, exist_ok=True)
            
            main_path = mcp_dir / "main.py"
            with open(main_path, "w", encoding="utf-8") as f:
                f.write(codigo_main_py)
                
            # Adiciona um pyproject.toml básico se não existir
            pyproject_path = mcp_dir / "pyproject.toml"
            if not pyproject_path.exists():
                with open(pyproject_path, "w", encoding="utf-8") as f:
                    f.write(f'[project]\nname = "{nome}"\nversion = "0.1.0"\ndependencies = ["mcp"]\n')
                    
            if self._mcp_manager:
                # Dá 3 segundos pro watchfiles no Windows reiniciar o servidor
                await asyncio.sleep(3)
                # Tenta redescobrir imediatamente para conectar
                await self._mcp_manager.refresh()
                
            return {
                "status": "success",
                "message": f"Servidor MCP '{nome}' criado e salvo em {main_path}. Se as dependências estiverem instaladas, as ferramentas já estão disponíveis neste exato momento!"
            }
        except Exception as exc:
            return {"error": str(exc)}

__all__ = ["SystemToolExecutor", "TAVILY_SEARCH_SPEC", "SEARCH_MEMORY_SPEC", "CRIAR_SERVIDOR_MCP_SPEC"]
