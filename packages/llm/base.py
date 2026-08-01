"""Camada de abstração de LLM. Escrita ANTES do primeiro provider.

Nenhum módulo do sistema importa SDK de provider diretamente; todos dependem de
`LLMProvider`. Trocar de modelo não toca em agente nenhum.

Este módulo roda sob `mypy --strict`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from packages.shared.contracts import ToolSpec

Role = Literal["system", "user", "assistant", "tool"]


class Message(BaseModel):
    """Formato de wire para o provider. Persistência de conversa usa `ChatMessage`."""

    role: Role
    content: str
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    thought_signature: str | None = None


class ToolResult(BaseModel):
    """Retorno de uma tool, pronto para virar uma `Message` de role `tool`."""

    tool_call_id: str
    name: str
    content: str
    is_error: bool = False


class Completion(BaseModel):
    text: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    finish_reason: str = ""

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class StreamChunk(BaseModel):
    """Unidade de streaming. `type` diz ao gateway o que empurrar no WebSocket."""

    type: Literal["text", "tool_call", "done", "error"] = "text"
    text: str = ""
    tool_call: ToolCall | None = None
    completion: Completion | None = None
    error: str | None = None


Message.model_rebuild()


# --------------------------------------------------------------------------- #
# Erros
# --------------------------------------------------------------------------- #


class LLMError(Exception):
    """Base de toda falha da camada de LLM."""


class UnsupportedOperation(LLMError):
    """O provider não implementa a operação. Quem chama decide o fallback."""


class ContentBlocked(LLMError):
    """O provider recusou gerar por política de conteúdo.

    Distinta de `ProviderRequestError`: a requisição funcionou, o status foi 2xx e
    não há o que repetir. Existe porque provider que sinaliza bloqueio devolvendo
    texto vazio (Gemini com `finishReason=SAFETY`) faria o agente planejar sobre o
    nada — o silêncio tem de virar erro nomeado.
    """


class ProviderRequestError(LLMError):
    """Falha de transporte ou resposta inválida do provider."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


# --------------------------------------------------------------------------- #
# Protocolo
# --------------------------------------------------------------------------- #


@runtime_checkable
class LLMProvider(Protocol):
    """Interface única. Tool calling é normalizado para `ToolCall`, que usa o
    mesmo `input_schema` JSON Schema do MCP."""

    name: str
    model: str

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system: str | None = None,
    ) -> Completion: ...

    def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system: str | None = None,
    ) -> AsyncIterator[StreamChunk]: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


__all__ = [
    "Completion",
    "ContentBlocked",
    "LLMError",
    "LLMProvider",
    "Message",
    "ProviderRequestError",
    "Role",
    "StreamChunk",
    "ToolCall",
    "ToolResult",
    "UnsupportedOperation",
]
