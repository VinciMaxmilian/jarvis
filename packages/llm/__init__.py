"""Camada de abstração de LLM — re-exporta base e providers.

Providers ficam aqui só para quem monta a injeção (`apps/api/deps.py`). Agente
nenhum importa provider concreto: todos dependem de `LLMProvider`.
"""

from packages.llm.anthropic_provider import AnthropicProvider
from packages.llm.base import (
    Completion,
    ContentBlocked,
    LLMError,
    LLMProvider,
    Message,
    ProviderRequestError,
    Role,
    StreamChunk,
    ToolCall,
    ToolResult,
    UnsupportedOperation,
)
from packages.llm.gemini_provider import DEFAULT_MODEL as GEMINI_DEFAULT_MODEL
from packages.llm.gemini_provider import GeminiProvider
from packages.llm.ollama_provider import DEFAULT_BASE_URL as OLLAMA_DEFAULT_BASE_URL
from packages.llm.ollama_provider import DEFAULT_MODEL as OLLAMA_DEFAULT_MODEL
from packages.llm.ollama_provider import OllamaProvider
from packages.llm.openai_provider import OpenAIProvider
from packages.llm.profiles import (
    FALLBACK_MODEL,
    PROFILE_MODELS,
    TASK_PROFILES,
    ModelResolution,
    TaskProfile,
    resolve_model,
)

__all__ = [
    "FALLBACK_MODEL",
    "GEMINI_DEFAULT_MODEL",
    "OLLAMA_DEFAULT_BASE_URL",
    "OLLAMA_DEFAULT_MODEL",
    "PROFILE_MODELS",
    "TASK_PROFILES",
    "AnthropicProvider",
    "Completion",
    "ContentBlocked",
    "GeminiProvider",
    "LLMError",
    "LLMProvider",
    "Message",
    "ModelResolution",
    "OllamaProvider",
    "OpenAIProvider",
    "ProviderRequestError",
    "Role",
    "StreamChunk",
    "TaskProfile",
    "ToolCall",
    "ToolResult",
    "UnsupportedOperation",
    "resolve_model",
]
