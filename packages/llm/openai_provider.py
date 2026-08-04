"""Provider OpenAI — compatível com LM Studio, vLLM e Koboldcpp via OpenAI API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Final

import httpx
import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageToolCall

from packages.llm.base import (
    Completion,
    LLMError,
    Message,
    ProviderRequestError,
    StreamChunk,
    ToolCall,
    UnsupportedOperation,
)
from packages.shared.contracts import ToolSpec

#: Status que significam "este backend não serve `/v1/embeddings`". 404 é o LM
#: Studio/vLLM sem a rota; 405 é proxy que só libera chat; 501 é backend que
#: declara a rota e não a implementa. Nenhum deles se resolve tentando de novo.
_EMBED_ABSENT_STATUS: Final = frozenset({404, 405, 501})

#: 400 é ambíguo — pode ser payload ruim ou modelo sem cabeça de embedding. Estes
#: marcadores desempatam pelo texto do erro; sem eles, pedir embedding a um modelo
#: de geração viraria `ProviderRequestError`, que sugere "tente de novo" para algo
#: que nunca vai funcionar.
_EMBED_UNSUPPORTED_MARKERS: Final = (
    "does not support",
    "not supported",
    "is not an embedding",
    "no embedding",
    "embedding model",
)


def _looks_like_embedding_unsupported(detail: str) -> bool:
    lowered = detail.lower()
    return any(marker in lowered for marker in _EMBED_UNSUPPORTED_MARKERS)


class OpenAIProvider:
    """Implementa o protocolo LLMProvider usando o SDK da OpenAI.

    Conformidade é estrutural, como em `AnthropicProvider`: herdar do Protocol o
    tornaria abstrato e `deps.py` não conseguiria instanciá-lo.

    `embed_model` é separado de `model` de propósito: embedding e chat quase nunca
    são o mesmo modelo (no LM Studio são literalmente `type` diferentes), e usar o
    modelo de chat para vetorizar devolve 400 — ou, pior, um vetor de dimensão
    inesperada que só quebra na hora de comparar. Sem valor explícito, cai no
    modelo de chat e o erro sai nomeando os dois.

    `http_client` é injetável (`httpx.MockTransport` no teste) pela mesma razão do
    `OllamaProvider`: nenhum teste desta camada fala com a rede.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        *,
        embed_model: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name: str = "openai"
        self.model: str = model
        self._model = model
        self._embed_model = embed_model or model
        self._base_url = base_url
        self._client = AsyncOpenAI(
            api_key=api_key, base_url=base_url, http_client=http_client
        )

    def _convert_messages(
        self, messages: list[Message], *, system: str | None = None
    ) -> list[dict[str, Any]]:
        """Converte mensagens do nosso formato para o formato OpenAI."""
        out: list[dict[str, Any]] = []
        if system:
            out.append({"role": "system", "content": system})
        for msg in messages:
            # O parâmetro `system` explícito vence o embutido no histórico:
            # repetir instrução de sistema desalinha modelo aberto mais do que ajuda.
            if msg.role == "system" and not system:
                out.append({"role": "system", "content": msg.content})
            elif msg.role == "user":
                out.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                # Suporte básico a tools: não repassamos tool_calls no histórico.
                out.append({"role": "assistant", "content": msg.content})
            elif msg.role == "tool":
                # A OpenAI exige tool_call_id no role "tool", que modelos abertos
                # (LM Studio) suportam mal. Injetar como user message funciona nos
                # dois lados enquanto o v0.5 não precisa de casamento estrito.
                out.append(
                    {
                        "role": "user",
                        "content": f"Tool Result ({msg.tool_call_id}):\n{msg.content}",
                    }
                )
        return out

    def _convert_tools(self, tools: list[ToolSpec] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]

    def _parse_tool_calls(
        self, calls: list[ChatCompletionMessageToolCall] | None
    ) -> list[ToolCall]:
        if not calls:
            return []
        out = []
        for c in calls:
            try:
                args = json.loads(c.function.arguments)
            except json.JSONDecodeError:
                args = {}
            out.append(
                ToolCall(
                    id=c.id,
                    name=c.function.name,
                    arguments=args,
                )
            )
        return out

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system: str | None = None,
    ) -> Completion:
        """Gera completion completa (não streaming)."""
        try:
            oai_msgs = self._convert_messages(messages, system=system)
            oai_tools = self._convert_tools(tools)

            kwargs: dict[str, Any] = {
                "model": self._model,
                "messages": oai_msgs,
                "temperature": temperature,
                "max_tokens": max_tokens or 4096,
            }
            if oai_tools:
                kwargs["tools"] = oai_tools

            response = await self._client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            usage = response.usage

            text = choice.message.content or ""
            tool_calls = self._parse_tool_calls(choice.message.tool_calls)

            # Fallback for local models (like in LM Studio) that fail to use the API's tool_calls
            # but instead output the tool call as raw JSON in the text field.
            if not tool_calls and text:
                import re
                import uuid
                # Try to extract JSON from markdown block or just use the raw text
                match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
                json_str = match.group(1) if match else text.strip()
                
                if json_str.startswith("{") and '"name"' in json_str:
                    try:
                        parsed = json.loads(json_str)
                        if "name" in parsed and ("arguments" in parsed or "parameters" in parsed):
                            args = parsed.get("arguments", parsed.get("parameters", {}))
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except json.JSONDecodeError:
                                    pass
                            if isinstance(args, dict):
                                tool_calls.append(ToolCall(
                                    id=f"call_{uuid.uuid4().hex[:8]}", 
                                    name=parsed["name"], 
                                    arguments=args
                                ))
                                text = "" # Clear text as it was entirely a tool call
                    except json.JSONDecodeError:
                        pass

            return Completion(
                text=text,
                tool_calls=tool_calls,
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
                model=response.model or self._model,
                finish_reason=choice.finish_reason or "",
            )

        except openai.APIError as exc:
            raise ProviderRequestError(
                str(exc), status_code=getattr(exc, "status_code", None)
            ) from exc
        except Exception as exc:
            raise LLMError(f"Unexpected error: {exc}") from exc

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Gera completion em streaming."""
        try:
            oai_msgs = self._convert_messages(messages, system=system)
            oai_tools = self._convert_tools(tools)

            kwargs: dict[str, Any] = {
                "model": self._model,
                "messages": oai_msgs,
                "temperature": temperature,
                "max_tokens": max_tokens or 4096,
                "stream": True,
            }
            if oai_tools:
                kwargs["tools"] = oai_tools

            response = await self._client.chat.completions.create(**kwargs)

            # Em LM Studio / OAI Stream as tool calls vêm em pedaços e os modelos
            # locais fazem isso mal. Aqui só o texto sai; quando há tools, o loop
            # de agente usa `complete`, que recebe a tool call inteira.
            async for chunk in response:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield StreamChunk(text=delta.content)

        except openai.APIError as exc:
            raise ProviderRequestError(
                str(exc), status_code=getattr(exc, "status_code", None)
            ) from exc
        except Exception as exc:
            raise LLMError(f"Unexpected error: {exc}") from exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """`POST /v1/embeddings` com o modelo do perfil `embed`.

        **Por que isto deixou de levantar `UnsupportedOperation` sempre.** O
        comentário anterior recusava a operação com o argumento de que o endpoint
        varia por backend compatível e que um fallback silencioso esconderia quem
        está servindo. A PREOCUPAÇÃO continua certa — backends divergem —, mas a
        CONCLUSÃO não se sustenta mais: `/v1/embeddings` é parte da especificação
        OpenAI, o SDK que já é dependência a expõe, e o LM Studio da LAN foi
        medido servindo-a (1024 dimensões com
        `text-embedding-qwen3-embedding-0.6b`). Recusar uma capacidade que existe
        obriga todo chamador a montar um segundo cliente HTTP na mão, que é
        exatamente a duplicação que esta camada existe para evitar.

        A visibilidade que o comentário queria fica preservada sem a recusa: o
        backend que NÃO serve a rota devolve 404/405/501 e vira
        `UnsupportedOperation` nomeando `base_url` e modelo — quem chama decide o
        fallback com a informação de qual backend falhou, em vez de nunca poder
        tentar.
        """
        if not texts:
            # Sem ida à rede: lista vazia tem uma única resposta correta, e alguns
            # backends respondem 400 a `input: []`, o que viraria erro fantasma.
            return []

        try:
            response = await self._client.embeddings.create(
                model=self._embed_model, input=texts
            )
        except openai.APIStatusError as exc:
            detail = str(exc)
            if exc.status_code in _EMBED_ABSENT_STATUS:
                raise UnsupportedOperation(
                    f"O backend em {self._base_url} não serve /v1/embeddings "
                    f"(HTTP {exc.status_code}). Detalhe: {detail}"
                ) from exc
            if exc.status_code == 400 and _looks_like_embedding_unsupported(detail):
                raise UnsupportedOperation(
                    f"O modelo '{self._embed_model}' em {self._base_url} não faz "
                    "embedding. Aponte o perfil `embed` para um modelo de "
                    f"embedding. Detalhe: {detail}"
                ) from exc
            raise ProviderRequestError(detail, status_code=exc.status_code) from exc
        except openai.APIError as exc:
            raise ProviderRequestError(
                str(exc), status_code=getattr(exc, "status_code", None)
            ) from exc
        except Exception as exc:
            raise LLMError(f"Unexpected error: {exc}") from exc

        if not response.data:
            raise ProviderRequestError(
                f"O backend em {self._base_url} respondeu sem vetor para o modelo "
                f"'{self._embed_model}'."
            )

        # Ordena por `index`: a especificação permite devolver fora de ordem, e um
        # vetor casado com o texto errado é o bug que não dá erro — só piora a
        # busca semântica de um jeito que ninguém rastreia até aqui.
        ordenados = sorted(response.data, key=lambda item: item.index)
        return [[float(value) for value in item.embedding] for item in ordenados]

    # -- extras fora do Protocol ------------------------------------------- #

    async def list_models(self) -> list[str]:
        """`GET /v1/models` — o que este backend diz servir AGORA.

        Fora do Protocol, igual ao `list_models` do Gemini e do Ollama. É a fonte
        do `served` de `packages.llm.profiles.resolve_model`: sem ele, a resolução
        de perfil confiaria num id de modelo que a máquina pode nem ter carregado.
        Usa a rota OpenAI padrão, e não a `/api/v0/models` nativa do LM Studio, de
        propósito — a nativa traz `type` e contexto, mas só o LM Studio a serve, e
        esta classe também atende vLLM e Koboldcpp.
        """
        try:
            page = await self._client.models.list()
        except openai.APIError as exc:
            raise ProviderRequestError(
                str(exc), status_code=getattr(exc, "status_code", None)
            ) from exc
        except Exception as exc:
            raise LLMError(f"Unexpected error: {exc}") from exc

        return [model.id for model in page.data if model.id]


__all__ = ["OpenAIProvider"]
