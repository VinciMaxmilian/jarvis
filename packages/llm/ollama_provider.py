"""Provider Ollama — runtime local de inferência atrás de `LLMProvider`.

Existe por restrição real de máquina: na pessoal (GTX 1050 Ti 4 GB, 16 GB RAM,
CPU pré-AVX2) o Ollama é o único runtime que roda hoje, servindo
`adelnazmy2002/Qwen3-VL-8B-Instruct` — multimodal, o que cobre visão e texto
barato com um modelo só residente na VRAM.

**Por que a API nativa e não a camada OpenAI-compatible do Ollama.**
`/api/chat` expõe tool calling e as contagens reais de token
(`prompt_eval_count`, `eval_count`); a camada compatível omite a primeira e
preenche as segundas pior ou não preenche. Sem contagem real, o accounting viraria
estimativa apresentada como medição. O mesmo vale para `/api/embed`, que devolve
`embeddings` direto, e `/api/tags`, que lista o que está de fato instalado — sem
isso a UI precisaria de lista de modelos hardcoded.

**Streaming é NDJSON, não SSE**: uma linha JSON completa por chunk, sem prefixo
`data:` e sem `[DONE]`. Quem consome não pode reusar parser de SSE aqui.

Nenhum agente importa este módulo: todos dependem de `LLMProvider`. Trocar de
provider é configuração em runtime (`chief_provider`), não build.

Este módulo roda sob `mypy --strict`.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Final, NoReturn

import httpx

from packages.llm.base import (
    Completion,
    LLMProvider,
    Message,
    ProviderRequestError,
    StreamChunk,
    ToolCall,
    UnsupportedOperation,
)
from packages.shared.contracts import ToolSpec

#: Loopback, não `0.0.0.0`: o Ollama serve um único operador nesta máquina.
DEFAULT_BASE_URL: Final = "http://127.0.0.1:11434"

#: VL para resolver visão e texto barato com um modelo só em 4 GB de VRAM.
DEFAULT_MODEL: Final = "adelnazmy2002/Qwen3-VL-8B-Instruct"

#: `connect` curto para que "serviço fora do ar" falhe rápido e com mensagem útil;
#: `read` longo porque um 8B quantizado em GPU modesta gera devagar.
DEFAULT_TIMEOUT: Final = httpx.Timeout(connect=5.0, read=600.0, write=30.0, pool=5.0)

#: Marcadores do erro que o Ollama devolve quando o modelo não tem cabeça de
#: embedding. Viram `UnsupportedOperation` para quem chama decidir o fallback.
_EMBED_UNSUPPORTED_MARKERS: Final = (
    "does not support embed",
    "not support embedding",
    "does not support generate",
    "no embedding",
)


# --------------------------------------------------------------------------- #
# Coerção de payload — a resposta do Ollama é JSON não tipado
# --------------------------------------------------------------------------- #


def _as_dict(value: object, *, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProviderRequestError(
            f"Ollama devolveu {what} em formato inesperado: {type(value).__name__}"
        )
    return value


def _as_str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _as_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _parse_arguments(raw: object) -> dict[str, Any]:
    """Normaliza `function.arguments`.

    Na API nativa vem como objeto JSON já desserializado, mas parte dos modelos
    imita o formato OpenAI e manda a string. Aceitar os dois evita descartar uma
    tool call válida por causa do dialeto do modelo.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed: Any = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _parse_tool_calls(raw: object, *, start_index: int = 0) -> list[ToolCall]:
    """Converte `message.tool_calls[]` do Ollama para o `ToolCall` do projeto.

    A API nativa não emite `id` na tool call, mas `ToolCall.id` é obrigatório e o
    loop do Chief AI casa o resultado por ele. Sintetizamos um id determinístico
    (índice + nome) em vez de UUID: mesma entrada gera mesmo id, o que torna o
    provider testável sem monkeypatch de aleatoriedade.
    """
    if not isinstance(raw, list):
        return []

    out: list[ToolCall] = []
    for offset, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        function = item.get("function")
        if not isinstance(function, dict):
            continue
        name = _as_str(function.get("name"))
        if not name:
            continue
        index = start_index + offset
        given_id = _as_str(item.get("id"))
        out.append(
            ToolCall(
                id=given_id or f"call_{index}_{name}",
                name=name,
                arguments=_parse_arguments(function.get("arguments")),
            )
        )
    return out


def _to_ollama_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    """ToolSpec → `tools[]` do Ollama. `input_schema` já é JSON Schema (MCP)."""
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


def _attach_images(entries: list[dict[str, Any]], images: list[str]) -> None:
    """Pendura as imagens base64 na última mensagem de `user`.

    É onde um modelo VL espera encontrá-las: a imagem pertence ao turno que está
    perguntando sobre ela, não ao histórico. Sem turno de user, cria um.
    """
    for entry in reversed(entries):
        if entry.get("role") == "user":
            entry["images"] = images
            return
    entries.append({"role": "user", "content": "", "images": images})


def _to_ollama_messages(
    messages: list[Message],
    *,
    system: str | None = None,
    images: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Message → `messages[]` do Ollama, que aceita os quatro roles nativamente."""
    out: list[dict[str, Any]] = []

    if system:
        out.append({"role": "system", "content": system})

    for m in messages:
        # O parâmetro `system` explícito vence o system embutido no histórico:
        # repetir instrução de sistema desalinha modelo 8B mais do que ajuda.
        if m.role == "system" and system:
            continue

        entry: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.tool_calls:
            # Devolver a própria tool call ao modelo mantém o turno coerente;
            # a API nativa não usa id aqui, só nome e argumentos.
            entry["tool_calls"] = [
                {"function": {"name": tc.name, "arguments": tc.arguments}}
                for tc in m.tool_calls
            ]
        out.append(entry)

    if images:
        _attach_images(out, images)

    return out


def _error_detail(body: str) -> str:
    """Extrai o campo `error` do corpo; cai para o corpo cru se não for JSON."""
    try:
        parsed: Any = json.loads(body)
    except json.JSONDecodeError:
        return body.strip()
    if isinstance(parsed, dict):
        detail = _as_str(parsed.get("error"))
        if detail:
            return detail
    return body.strip()


def _looks_like_embedding_unsupported(detail: str) -> bool:
    lowered = detail.lower()
    return any(marker in lowered for marker in _EMBED_UNSUPPORTED_MARKERS)


# --------------------------------------------------------------------------- #
# Provider
# --------------------------------------------------------------------------- #


class OllamaProvider:
    """LLMProvider concreta para a API nativa do Ollama.

    Suporta `complete`, `stream` e `embed` (este último depende do modelo
    carregado ter cabeça de embedding — senão levanta `UnsupportedOperation`).

    **Limitação conhecida — imagens e o Protocol.** `Message.content` é `str` e
    esse contrato NÃO muda: mudá-lo obrigaria todo provider e todo agente a
    entender conteúdo multimodal que só o Ollama serve hoje. Em vez disso,
    `complete`/`stream` aceitam um `images: list[str] | None` opcional (base64,
    sem prefixo `data:`), repassado no campo `images` da mensagem do Ollama.
    Parâmetro opcional extra não quebra o Protocol — `OllamaProvider` continua
    substituível por `LLMProvider` —, mas quem só tem a referência tipada como
    `LLMProvider` não consegue passá-lo: o Protocol não o declara. Para esse caso
    existe `complete_with_images`, que força o call site a estreitar o tipo de
    propósito, tornando a dependência de visão visível na revisão em vez de
    escondida num kwarg.

    O cliente httpx é injetável (`client=`) e a `base_url` é parâmetro: nada de
    cliente global. Sem injeção, um cliente é criado e fechado por requisição —
    em loopback o custo é irrelevante e evita cliente preso a event loop morto.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        *,
        timeout: httpx.Timeout | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name: str = "ollama"
        self.model: str = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        self._injected_client = client

    # -- infraestrutura ---------------------------------------------------- #

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    @asynccontextmanager
    async def _acquire_client(self) -> AsyncIterator[httpx.AsyncClient]:
        """Cliente injetado é emprestado, nunca fechado por nós — quem injetou
        controla o ciclo de vida (é o que permite `httpx.MockTransport` em teste).
        """
        if self._injected_client is not None:
            yield self._injected_client
            return
        # URL absoluta em toda chamada: assim um cliente injetado com outra
        # base_url continua funcionando como puro transporte.
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            yield client

    def _offline_hint(self, url: str) -> str:
        return (
            f"Ollama não respondeu em {url}: o serviço não está no ar. "
            f"Suba com `ollama serve` e confirme que o modelo '{self.model}' "
            f"está instalado (`ollama list`, `ollama pull {self.model}`)."
        )

    def _timeout_hint(self, url: str) -> str:
        return (
            f"Ollama excedeu o tempo limite em {url} (read={self._timeout.read}s). "
            f"O modelo '{self.model}' pode estar carregando na VRAM ou rodando em "
            f"CPU — verifique com `ollama ps`."
        )

    def _status_hint(self, url: str, status_code: int, body: str) -> str:
        detail = _error_detail(body) or "sem detalhe no corpo da resposta"
        if status_code == 404:
            return (
                f"Ollama respondeu 404 em {url}: o modelo '{self.model}' não está "
                f"instalado. Rode `ollama pull {self.model}`. Detalhe: {detail}"
            )
        return f"Ollama respondeu HTTP {status_code} em {url}: {detail}"

    async def _request(
        self, method: str, path: str, *, payload: dict[str, Any] | None = None
    ) -> httpx.Response:
        """Requisição não-streaming. Só traduz falha de transporte; status HTTP
        fica para quem chama, porque `embed` reage a 4xx diferente de `complete`.
        """
        url = self._url(path)
        try:
            async with self._acquire_client() as client:
                return await client.request(method, url, json=payload)
        except httpx.ConnectError as exc:
            raise ProviderRequestError(self._offline_hint(url)) from exc
        except httpx.TimeoutException as exc:
            raise ProviderRequestError(self._timeout_hint(url)) from exc
        except httpx.HTTPError as exc:
            raise ProviderRequestError(
                f"Falha de transporte ao falar com o Ollama em {url}: {exc}"
            ) from exc

    def _raise_for_status(self, resp: httpx.Response, path: str) -> NoReturn:
        raise ProviderRequestError(
            self._status_hint(self._url(path), resp.status_code, resp.text),
            status_code=resp.status_code,
        )

    def _json_body(self, resp: httpx.Response, path: str) -> dict[str, Any]:
        try:
            body: Any = resp.json()
        except ValueError as exc:
            raise ProviderRequestError(
                f"Ollama devolveu resposta não-JSON em {self._url(path)}: "
                f"{resp.text[:200]!r}",
                status_code=resp.status_code,
            ) from exc
        return _as_dict(body, what=f"a resposta de {path}")

    def _chat_payload(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None,
        temperature: float,
        max_tokens: int | None,
        system: str | None,
        images: list[str] | None,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        options: dict[str, Any] = {"temperature": temperature}
        if max_tokens is not None:
            options["num_predict"] = max_tokens

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": _to_ollama_messages(messages, system=system, images=images),
            "stream": stream,
            "options": options,
        }
        if tools:
            payload["tools"] = _to_ollama_tools(tools)
        return payload

    def _to_completion(self, raw: dict[str, Any]) -> Completion:
        message = _as_dict(raw.get("message") or {}, what="`message`")
        return Completion(
            text=_as_str(message.get("content")),
            tool_calls=_parse_tool_calls(message.get("tool_calls")),
            input_tokens=_as_int(raw.get("prompt_eval_count")),
            output_tokens=_as_int(raw.get("eval_count")),
            # Fallback para o modelo configurado: campo real quando vier, nunca "".
            model=_as_str(raw.get("model")) or self.model,
            finish_reason=_as_str(raw.get("done_reason")),
        )

    # -- Protocol ---------------------------------------------------------- #

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system: str | None = None,
        images: list[str] | None = None,
    ) -> Completion:
        """`POST /api/chat` com `stream: false`."""
        payload = self._chat_payload(
            messages, tools, temperature, max_tokens, system, images, stream=False
        )
        resp = await self._request("POST", "/api/chat", payload=payload)
        if resp.status_code >= 400:
            self._raise_for_status(resp, "/api/chat")
        return self._to_completion(self._json_body(resp, "/api/chat"))

    async def complete_with_images(
        self,
        messages: list[Message],
        images: list[str],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system: str | None = None,
    ) -> Completion:
        """Entrada explícita para visão (modelo VL), fora do Protocol.

        `images` são base64 puros, sem `data:image/...;base64,`. Existe para que a
        dependência de multimodal apareça no call site: quem chama isto precisou
        estreitar `LLMProvider` para `OllamaProvider` e assumiu a escolha.
        """
        return await self.complete(
            messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            system=system,
            images=images,
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system: str | None = None,
        images: list[str] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """`POST /api/chat` com `stream: true`, consumindo **NDJSON**.

        Falha de transporte sai como `StreamChunk(type="error")` em vez de
        exceção: o gerador pode já ter emitido texto, e levantar no meio deixaria
        o gateway sem como fechar o turno no WebSocket.
        """
        payload = self._chat_payload(
            messages, tools, temperature, max_tokens, system, images, stream=True
        )
        url = self._url("/api/chat")

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        final: dict[str, Any] = {}

        try:
            async with (
                self._acquire_client() as client,
                client.stream("POST", url, json=payload) as resp,
            ):
                if resp.status_code >= 400:
                    # Corpo de resposta streaming só existe depois do aread().
                    await resp.aread()
                    yield StreamChunk(
                        type="error",
                        error=self._status_hint(url, resp.status_code, resp.text),
                    )
                    return

                async for line in resp.aiter_lines():
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        chunk: Any = json.loads(stripped)
                    except json.JSONDecodeError:
                        # Linha truncada não invalida o turno inteiro.
                        continue
                    if not isinstance(chunk, dict):
                        continue

                    failure = _as_str(chunk.get("error"))
                    if failure:
                        yield StreamChunk(
                            type="error",
                            error=f"Ollama abortou a geração: {failure}",
                        )
                        return

                    message = chunk.get("message")
                    if isinstance(message, dict):
                        piece = _as_str(message.get("content"))
                        if piece:
                            text_parts.append(piece)
                            yield StreamChunk(type="text", text=piece)
                        tool_calls.extend(
                            _parse_tool_calls(
                                message.get("tool_calls"),
                                start_index=len(tool_calls),
                            )
                        )

                    if chunk.get("done") is True:
                        final = chunk
        except httpx.ConnectError:
            yield StreamChunk(type="error", error=self._offline_hint(url))
            return
        except httpx.TimeoutException:
            yield StreamChunk(type="error", error=self._timeout_hint(url))
            return
        except httpx.HTTPError as exc:
            yield StreamChunk(
                type="error",
                error=f"Falha de transporte ao falar com o Ollama em {url}: {exc}",
            )
            return

        # Tool calls saem só aqui, depois do texto: o Ollama as manda inteiras
        # (não em delta), mas nada garante em qual chunk. Bufferizar mantém a
        # ordem contratada text → tool_call → done qualquer que seja o modelo.
        for tc in tool_calls:
            yield StreamChunk(type="tool_call", tool_call=tc)

        yield StreamChunk(
            type="done",
            completion=Completion(
                text="".join(text_parts),
                tool_calls=tool_calls,
                input_tokens=_as_int(final.get("prompt_eval_count")),
                output_tokens=_as_int(final.get("eval_count")),
                model=_as_str(final.get("model")) or self.model,
                finish_reason=_as_str(final.get("done_reason")),
            ),
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """`POST /api/embed` (campo `input`, resposta `embeddings`).

        Modelo sem cabeça de embedding levanta `UnsupportedOperation`, não erro de
        transporte: é limite de capacidade, e quem chama decide o fallback (outro
        modelo residente ou embedding remoto).
        """
        payload: dict[str, Any] = {"model": self.model, "input": texts}
        resp = await self._request("POST", "/api/embed", payload=payload)

        if resp.status_code >= 400:
            detail = _error_detail(resp.text)
            if _looks_like_embedding_unsupported(detail):
                raise UnsupportedOperation(
                    f"O modelo '{self.model}' no Ollama não gera embeddings: {detail}"
                )
            self._raise_for_status(resp, "/api/embed")

        body = self._json_body(resp, "/api/embed")
        raw = body.get("embeddings")
        if not isinstance(raw, list) or not raw:
            raise UnsupportedOperation(
                f"Ollama não devolveu embeddings para o modelo '{self.model}'. "
                "Use um modelo com cabeça de embedding (ex.: `nomic-embed-text`)."
            )

        vectors: list[list[float]] = []
        for item in raw:
            if not isinstance(item, list):
                raise ProviderRequestError(
                    "Ollama devolveu `embeddings` com item que não é vetor: "
                    f"{type(item).__name__}"
                )
            vectors.append([float(value) for value in item])
        return vectors

    # -- extras fora do Protocol ------------------------------------------- #

    async def list_models(self) -> list[str]:
        """`GET /api/tags` — modelos de fato instalados.

        Fora do Protocol de propósito: é introspecção de runtime local, que só o
        Ollama oferece. Serve para a UI de configurações não ter lista hardcoded.
        """
        resp = await self._request("GET", "/api/tags")
        if resp.status_code >= 400:
            self._raise_for_status(resp, "/api/tags")

        body = self._json_body(resp, "/api/tags")
        entries = body.get("models")
        if not isinstance(entries, list):
            return []

        names: list[str] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = _as_str(entry.get("model")) or _as_str(entry.get("name"))
            if name:
                names.append(name)
        return names


if TYPE_CHECKING:

    def _conforms_to_protocol(provider: OllamaProvider) -> LLMProvider:
        """Guarda estática: se `OllamaProvider` deixar de satisfazer o Protocol,
        o `mypy --strict` quebra aqui em vez de no call site do `deps.py`.
        """
        return provider


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "OllamaProvider",
]
