"""Executor central de tools do agente.

Implementa ToolExecutor (packages/shared/ports.py) e agrega `web_search` e `search_memory`.
"""

from __future__ import annotations

from typing import Any
import httpx
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
        chat_history_store: VectorStore
    ) -> None:
        self._tavily_api_key = tavily_api_key
        self._llm = llm
        self._history_store = chat_history_store
        
        self._tools: dict[str, ToolSpec] = {
            TAVILY_SEARCH_SPEC.name: TAVILY_SEARCH_SPEC,
            SEARCH_MEMORY_SPEC.name: SEARCH_MEMORY_SPEC,
        }

    def specs(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def has(self, name: str) -> bool:
        return name in self._tools

    async def execute(
        self, name: str, arguments: dict[str, object], dry_run: bool = False
    ) -> dict[str, object]:
        if not self.has(name):
            raise ToolNotFound(name)

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

__all__ = ["SystemToolExecutor", "TAVILY_SEARCH_SPEC", "SEARCH_MEMORY_SPEC"]
