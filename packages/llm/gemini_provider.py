"""Provider Gemini (Google AI) — provider principal, atrás de `LLMProvider`.

Assumiu o lugar do Ollama como default por restrição de hardware: o
`Qwen3-VL-8B-Instruct` não entra nos 4 GB da GTX 1050 Ti. O `OllamaProvider`
continua no repo, selecionável em runtime, para quando houver GPU que o comporte.

**Por que REST na mão e não o SDK `google-genai`.** `httpx` já é dependência; o
SDK seria uma dependência nova para um adapter de ~400 linhas cujo formato de wire
é estável e público. Menos superfície e nada a resolver no `pyproject.toml`.

**Chave vai em header `x-goog-api-key`, nunca em query string.** Chave em URL
aparece em log de proxy, em histórico de shell e em relatório de erro.

O formato do Gemini não é o do OpenAI e as diferenças são todas silenciosas —
erram devolvendo resposta vazia, não erro:

- `messages` → `contents[]`; role de assistente é `"model"`, não `"assistant"`
- prompt de sistema vai em `systemInstruction`, campo irmão de `contents`
- `temperature`/`max_tokens` moram em `generationConfig.{temperature,maxOutputTokens}`
- tools em `tools[].functionDeclarations[]`, resposta em `parts[].functionCall`
- resultado de tool volta como `parts[].functionResponse`, em turno de role `user`
- streaming é **SSE** (`data: {...}`), não o NDJSON do Ollama

Este módulo roda sob `mypy --strict`.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Final, NoReturn

import httpx

from packages.llm.base import (
    Completion,
    ContentBlocked,
    LLMProvider,
    Message,
    ProviderRequestError,
    StreamChunk,
    ToolCall,
    UnsupportedOperation,
)
from packages.shared.contracts import ToolSpec

DEFAULT_BASE_URL: Final = "https://generativelanguage.googleapis.com/v1beta"

#: NÃO verificado contra a API — não havia chave disponível na máquina no momento
#: em que este adapter foi escrito. É um flash por custo. Confirme com
#: `list_models()` (ou `GET /v1beta/models`) e ajuste `GEMINI_MODEL` se preciso;
#: `_status_hint` já manda fazer isso quando a API responde 404.
DEFAULT_MODEL: Final = "gemini-2.5-flash"

#: `connect` curto para falhar rápido sem rede; `read` folgado porque tool calling
#: com prompt longo demora.
DEFAULT_TIMEOUT: Final = httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=5.0)

#: `finishReason` que significa "não houve resposta utilizável". Devolver texto
#: vazio nesses casos faria o Chief AI planejar sobre o nada.
_BLOCKED_FINISH_REASONS: Final = frozenset(
    {"SAFETY", "PROHIBITED_CONTENT", "RECITATION", "SPII", "BLOCKLIST"}
)

#: Erro do Gemini quando se pede embedding a um modelo de geração.
_EMBED_UNSUPPORTED_MARKERS: Final = (
    "is not found for api version",
    "not supported for",
    "does not support",
    "unexpected model name format",
)


# --------------------------------------------------------------------------- #
# Coerção de payload
# --------------------------------------------------------------------------- #


def _as_dict(value: object, *, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProviderRequestError(
            f"Gemini devolveu {what} em formato inesperado: {type(value).__name__}"
        )
    return value


def _as_str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _as_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _bare_model(model: str) -> str:
    """`models/gemini-x` e `gemini-x` são o mesmo modelo. Normaliza para o segundo,
    porque a URL do endpoint já traz o prefixo `models/`.
    """
    return model[len("models/") :] if model.startswith("models/") else model


# --------------------------------------------------------------------------- #
# Conversão de contrato → wire do Gemini
# --------------------------------------------------------------------------- #


def _strip_unsupported_schema(schema: Any) -> Any:
    """O Gemini (v1beta) suporta um subconjunto restrito do JSON Schema.
    Mantém apenas as chaves permitidas recursivamente para evitar HTTP 400 ou
    falhas silenciosas onde a API ignora os tools.
    """
    _allowed_keys = frozenset({
        "type", "format", "description", "nullable", "enum",
        "maxItems", "minItems", "properties", "required", "items"
    })
    if isinstance(schema, dict):
        out = {}
        for k, v in schema.items():
            if k == "properties":
                # The keys inside properties are argument names, not schema keywords.
                out[k] = {arg_name: _strip_unsupported_schema(arg_schema) for arg_name, arg_schema in v.items()}
            elif k in _allowed_keys:
                out[k] = _strip_unsupported_schema(v)
        return out
    if isinstance(schema, list):
        return [_strip_unsupported_schema(item) for item in schema]
    return schema


def _to_gemini_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    """ToolSpec → `tools[].functionDeclarations[]`, reusando o JSON Schema do MCP.

    Vai tudo numa única entrada de `tools`: o Gemini trata a lista externa como
    grupos de ferramentas, e declarar um grupo por função faz o modelo escolher pior.
    """
    return [
        {
            "functionDeclarations": [
                {
                    "name": t.name,
                    "description": t.description,
                    "parameters": _strip_unsupported_schema(t.input_schema),
                }
                for t in tools
            ]
        }
    ]


def _tool_response_part(message: Message) -> dict[str, Any]:
    """Resultado de tool → `functionResponse`.

    O Gemini casa o resultado pelo NOME da função, não por id. `Message` de role
    `tool` guarda `tool_call_id` (que aqui é o próprio nome, veja
    `_parse_function_calls`), então é dele que o nome sai. E `response` tem de ser
    objeto: string crua é rejeitada, por isso o conteúdo é embrulhado.
    """
    name = message.tool_call_id or "unknown_tool"
    try:
        parsed: Any = json.loads(message.content)
    except json.JSONDecodeError:
        parsed = message.content
    payload = parsed if isinstance(parsed, dict) else {"result": parsed}
    return {"functionResponse": {"name": name, "response": payload}}


def _to_gemini_contents(
    messages: list[Message],
    *,
    images: list[str] | None = None,
    image_mime_type: str = "image/png",
) -> list[dict[str, Any]]:
    """Message → `contents[]`. Mensagens de role `system` são ignoradas aqui: quem
    chama as extrai para `systemInstruction`, que é campo separado.
    """
    contents: list[dict[str, Any]] = []

    for m in messages:
        if m.role == "system":
            continue

        if m.role == "tool":
            # Resultado de tool volta como turno de `user` no Gemini.
            contents.append({"role": "user", "parts": [_tool_response_part(m)]})
            continue

        parts: list[dict[str, Any]] = []
        if m.content:
            parts.append({"text": m.content})
        for tc in m.tool_calls:
            fc_part = {"name": tc.name, "args": tc.arguments}
            part_dict: dict[str, Any] = {"functionCall": fc_part}
            if tc.thought_signature:
                part_dict["thoughtSignature"] = tc.thought_signature
            parts.append(part_dict)
        if not parts:
            # `parts` vazio é rejeitado com 400; turno sem conteúdo não agrega nada.
            continue

        contents.append(
            {"role": "model" if m.role == "assistant" else "user", "parts": parts}
        )

    if images:
        _attach_images(contents, images, image_mime_type)

    return contents


_DATA_URL_RE: Final = re.compile(r"^data:(?P<mime>[\w.+-]+/[\w.+-]+)?;base64,", re.I)


def _split_data_url(raw: str, fallback_mime: str) -> tuple[str, str]:
    """`data:image/jpeg;base64,XXXX` → `("image/jpeg", "XXXX")`.

    Base64 puro passa intacto, com `fallback_mime`.

    Por que tolerar as duas formas em vez de exigir só a de contrato: o que chega
    do `<input type="file">` do PWA é `FileReader.readAsDataURL`, ou seja, SEMPRE
    o data URL completo. Passando ele direto, o Google devolvia

        HTTP 400 — Invalid value at 'contents[N].parts[1].inline_data.data'
        (TYPE_BYTES), Base64 decoding failed for "data:image/jpeg;base64,/9j/…"

    porque `inlineData.data` aceita só o payload. E a correção óbvia — cortar o
    prefixo em quem chama — perderia a única informação confiável de mime que
    existe no caminho: `_to_gemini_contents` tem `image_mime_type="image/png"`
    fixo, então um JPEG viajaria anunciado como PNG. O prefixo é a resposta para
    os dois problemas, e por isso ele é consumido aqui, onde o mime é usado.
    """
    match = _DATA_URL_RE.match(raw)
    if not match:
        return fallback_mime, raw
    return match.group("mime") or fallback_mime, raw[match.end():]


def _attach_images(
    contents: list[dict[str, Any]], images: list[str], mime_type: str
) -> None:
    """Anexa `inlineData` ao último turno de `user` — mesma regra do
    `OllamaProvider`, onde a imagem pertence ao turno que pergunta sobre ela.

    Aceita base64 puro (o contrato) e data URL (o que o PWA manda de fato) — ver
    `_split_data_url`.
    """
    image_parts = []
    for raw in images:
        mime, data = _split_data_url(raw, mime_type)
        image_parts.append({"inlineData": {"mimeType": mime, "data": data}})
    for entry in reversed(contents):
        if entry.get("role") == "user":
            existing = entry.get("parts")
            if isinstance(existing, list):
                existing.extend(image_parts)
                return
    contents.append({"role": "user", "parts": list(image_parts)})


def _parse_function_calls(parts: list[Any], *, start_index: int = 0) -> list[ToolCall]:
    """`parts[].functionCall` → `ToolCall`.

    O Gemini não emite id de tool call: o casamento do resultado é por nome. Como
    `ToolCall.id` é obrigatório e o loop do Chief AI devolve esse id em
    `Message.tool_call_id`, usamos o próprio nome como id — é o que
    `_tool_response_part` precisa receber de volta para montar o `functionResponse`.
    """
    out: list[ToolCall] = []
    for offset, part in enumerate(parts):
        if not isinstance(part, dict):
            continue
        call = part.get("functionCall")
        if not isinstance(call, dict):
            continue
        name = _as_str(call.get("name"))
        if not name:
            continue
        args = call.get("args")
        thought_signature = part.get("thoughtSignature")
        out.append(
            ToolCall(
                id=name,
                name=name,
                arguments=args if isinstance(args, dict) else {},
                thought_signature=thought_signature,
            )
        )
        del offset, start_index  # índice não entra no id; o Gemini casa por nome
    return out


def _text_from_parts(parts: list[Any]) -> str:
    return "".join(
        _as_str(part.get("text")) for part in parts if isinstance(part, dict)
    )


def _error_detail(body: str) -> str:
    """Extrai `error.message` do corpo de erro do Google; cai para o corpo cru."""
    try:
        parsed: Any = json.loads(body)
    except json.JSONDecodeError:
        return body.strip()
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict):
            detail = _as_str(error.get("message"))
            if detail:
                return detail
    return body.strip()


def _looks_like_embedding_unsupported(detail: str) -> bool:
    lowered = detail.lower()
    return any(marker in lowered for marker in _EMBED_UNSUPPORTED_MARKERS)


# --------------------------------------------------------------------------- #
# Provider
# --------------------------------------------------------------------------- #


class GeminiProvider:
    """LLMProvider concreta para a API REST do Google AI (Gemini).

    Suporta `complete`, `stream` e `embed`. `embed` só funciona com modelo que
    tenha `embedContent` (ex.: `text-embedding-004`); com um modelo de geração
    levanta `UnsupportedOperation` para quem chama decidir o fallback.

    **Imagens — mesma decisão do `OllamaProvider`, de propósito.** `Message.content`
    é `str` e esse contrato não muda: mexer nele obrigaria todo provider e todo
    agente a entender conteúdo multimodal. `complete`/`stream` aceitam um
    `images: list[str] | None` opcional (base64 puro, sem prefixo `data:`), que
    aqui virá em `parts[].inlineData` e no Ollama em `message.images`. Parâmetro
    opcional extra não quebra o Protocol, mas quem só tem a referência tipada como
    `LLMProvider` não consegue passá-lo — para esse caso existe
    `complete_with_images`, idêntico em nome e forma ao do Ollama, para que trocar
    de provider não mude o call site de visão.

    Cliente httpx injetável e `base_url` parametrizada: nada de cliente global.
    """

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        *,
        base_url: str = DEFAULT_BASE_URL,
        embed_model: str | None = None,
        timeout: httpx.Timeout | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name: str = "gemini"
        self.model: str = _bare_model(model)
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        # Sem variável de ambiente própria para o modelo de embedding: por default
        # tenta o mesmo modelo e, se ele não tiver `embedContent`, diz qual usar.
        self._embed_model = _bare_model(embed_model or model)
        self._timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        self._injected_client = client

    # -- infraestrutura ---------------------------------------------------- #

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    def _headers(self) -> dict[str, str]:
        # Header, não query string: chave em URL vaza em log de proxy e histórico.
        return {
            "x-goog-api-key": self._api_key,
            "Content-Type": "application/json",
        }

    @asynccontextmanager
    async def _acquire_client(self) -> AsyncIterator[httpx.AsyncClient]:
        """Cliente injetado é emprestado, nunca fechado por nós."""
        if self._injected_client is not None:
            yield self._injected_client
            return
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            yield client

    def _unreachable_hint(self, url: str) -> str:
        return (
            f"Não foi possível conectar ao Gemini em {url}: host inalcançável. "
            "Verifique a conexão de rede, DNS e proxy da máquina."
        )

    def _timeout_hint(self, url: str) -> str:
        return (
            f"Gemini excedeu o tempo limite em {url} "
            f"(read={self._timeout.read}s) com o modelo '{self.model}'."
        )

    def _status_hint(self, url: str, status_code: int, body: str) -> str:
        detail = _error_detail(body) or "sem detalhe no corpo da resposta"
        if status_code in (401, 403):
            # Mensagem própria: o corpo cru do Google aqui não diz o que fazer.
            return (
                f"Gemini recusou a autenticação (HTTP {status_code}): a chave em "
                "GEMINI_API_KEY/GOOGLE_API_KEY é inválida, expirou ou não tem "
                f"acesso ao modelo '{self.model}'. Gere ou libere a chave em "
                "https://aistudio.google.com/apikey e confira os modelos "
                "disponíveis com `list_models()`."
            )
        if status_code == 404:
            return (
                f"Gemini não conhece o modelo '{self.model}' (HTTP 404). Liste os "
                "nomes válidos com `list_models()` (GET /v1beta/models) e ajuste "
                f"GEMINI_MODEL. Detalhe: {detail}"
            )
        if status_code == 429:
            return (
                f"Gemini estourou a cota do modelo '{self.model}' (HTTP 429). "
                f"Espere a janela de quota reabrir ou troque de modelo. {detail}"
            )
        return f"Gemini respondeu HTTP {status_code} em {url}: {detail}"

    async def _request(
        self, method: str, path: str, *, payload: dict[str, Any] | None = None
    ) -> httpx.Response:
        """Requisição não-streaming. Só traduz falha de transporte; status HTTP fica
        para quem chama, porque `embed` reage a 4xx diferente de `complete`.
        """
        url = self._url(path)
        try:
            async with self._acquire_client() as client:
                return await client.request(
                    method, url, json=payload, headers=self._headers()
                )
        except httpx.ConnectError as exc:
            raise ProviderRequestError(self._unreachable_hint(url)) from exc
        except httpx.TimeoutException as exc:
            raise ProviderRequestError(self._timeout_hint(url)) from exc
        except httpx.HTTPError as exc:
            raise ProviderRequestError(
                f"Falha de transporte ao falar com o Gemini em {url}: {exc}"
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
                f"Gemini devolveu resposta não-JSON em {self._url(path)}: "
                f"{resp.text[:200]!r}",
                status_code=resp.status_code,
            ) from exc
        return _as_dict(body, what=f"a resposta de {path}")

    def _generate_payload(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None,
        temperature: float,
        max_tokens: int | None,
        system: str | None,
        images: list[str] | None,
    ) -> dict[str, Any]:
        # O parâmetro `system` vence o system embutido no histórico.
        effective_system = system or next(
            (m.content for m in messages if m.role == "system"), None
        )

        config: dict[str, Any] = {"temperature": temperature}
        if max_tokens is not None:
            config["maxOutputTokens"] = max_tokens

        payload: dict[str, Any] = {
            "contents": _to_gemini_contents(messages, images=images),
            "generationConfig": config,
        }
        if effective_system:
            payload["systemInstruction"] = {"parts": [{"text": effective_system}]}
        if tools:
            payload["tools"] = _to_gemini_tools(tools)
        return payload

    def _guard_blocked(
        self, finish_reason: str, block_reason: str, text: str
    ) -> None:
        """Bloqueio de segurança não é sucesso com texto vazio.

        Sem isto o Chief AI recebe `""` e planeja sobre o nada. Texto parcial vai
        na mensagem para não perder evidência do que chegou antes do corte.
        """
        if block_reason:
            raise ContentBlocked(
                f"Gemini bloqueou o prompt antes de gerar (blockReason="
                f"{block_reason}). Reformule a pergunta."
            )
        if finish_reason in _BLOCKED_FINISH_REASONS:
            partial = f" Texto parcial recebido: {text[:200]!r}." if text else ""
            raise ContentBlocked(
                f"Gemini interrompeu a resposta por política de conteúdo "
                f"(finishReason={finish_reason}).{partial}"
            )

    def _to_completion(self, raw: dict[str, Any]) -> Completion:
        feedback = raw.get("promptFeedback")
        block_reason = (
            _as_str(feedback.get("blockReason")) if isinstance(feedback, dict) else ""
        )

        candidates = _as_list(raw.get("candidates"))
        candidate = (
            candidates[0] if candidates and isinstance(candidates[0], dict) else {}
        )
        content = candidate.get("content")
        parts = _as_list(content.get("parts")) if isinstance(content, dict) else []

        text = _text_from_parts(parts)
        finish_reason = _as_str(candidate.get("finishReason"))
        self._guard_blocked(finish_reason, block_reason, text)

        usage = raw.get("usageMetadata")
        usage_dict = usage if isinstance(usage, dict) else {}

        return Completion(
            text=text,
            tool_calls=_parse_function_calls(parts),
            input_tokens=_as_int(usage_dict.get("promptTokenCount")),
            output_tokens=_as_int(usage_dict.get("candidatesTokenCount")),
            model=_as_str(raw.get("modelVersion")) or self.model,
            finish_reason=finish_reason,
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
        """`POST /models/{model}:generateContent`."""
        path = f"/models/{self.model}:generateContent"
        payload = self._generate_payload(
            messages, tools, temperature, max_tokens, system, images
        )
        resp = await self._request("POST", path, payload=payload)
        if resp.status_code >= 400:
            self._raise_for_status(resp, path)
        return self._to_completion(self._json_body(resp, path))

    async def complete_with_images(
        self,
        messages: list[Message],
        images: list[str],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system: str | None = None,
    ) -> Completion:
        """Entrada explícita para visão, fora do Protocol.

        Mesma assinatura de `OllamaProvider.complete_with_images`: trocar de
        provider não deve mudar o call site de visão. `images` são base64 puros.
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
        """`POST /models/{model}:streamGenerateContent?alt=sse`.

        Formato **SSE** (`data: {...}` por evento), não o NDJSON do Ollama: o
        parser não é compartilhado com ele de propósito.

        Falha de transporte e bloqueio de conteúdo saem como
        `StreamChunk(type="error")` em vez de exceção: o gerador pode já ter
        emitido texto, e levantar no meio deixaria o gateway sem fechar o turno.
        """
        path = f"/models/{self.model}:streamGenerateContent"
        url = f"{self._url(path)}?alt=sse"
        payload = self._generate_payload(
            messages, tools, temperature, max_tokens, system, images
        )

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        input_tokens = 0
        output_tokens = 0
        model_version = ""
        finish_reason = ""
        block_reason = ""

        try:
            async with (
                self._acquire_client() as client,
                client.stream(
                    "POST", url, json=payload, headers=self._headers()
                ) as resp,
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
                    # SSE: só linhas `data:` interessam; comentário e `event:` não.
                    if not stripped.startswith("data:"):
                        continue
                    body = stripped[len("data:") :].strip()
                    if not body:
                        continue
                    try:
                        chunk: Any = json.loads(body)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(chunk, dict):
                        continue

                    feedback = chunk.get("promptFeedback")
                    if isinstance(feedback, dict):
                        block_reason = (
                            _as_str(feedback.get("blockReason")) or block_reason
                        )

                    candidates = _as_list(chunk.get("candidates"))
                    if candidates and isinstance(candidates[0], dict):
                        candidate = candidates[0]
                        finish_reason = (
                            _as_str(candidate.get("finishReason")) or finish_reason
                        )
                        content = candidate.get("content")
                        if isinstance(content, dict):
                            parts = _as_list(content.get("parts"))
                            piece = _text_from_parts(parts)
                            if piece:
                                text_parts.append(piece)
                                yield StreamChunk(type="text", text=piece)
                            tool_calls.extend(
                                _parse_function_calls(
                                    parts, start_index=len(tool_calls)
                                )
                            )

                    usage = chunk.get("usageMetadata")
                    if isinstance(usage, dict):
                        input_tokens = (
                            _as_int(usage.get("promptTokenCount")) or input_tokens
                        )
                        output_tokens = (
                            _as_int(usage.get("candidatesTokenCount")) or output_tokens
                        )
                    model_version = _as_str(chunk.get("modelVersion")) or model_version
        except httpx.ConnectError:
            yield StreamChunk(type="error", error=self._unreachable_hint(url))
            return
        except httpx.TimeoutException:
            yield StreamChunk(type="error", error=self._timeout_hint(url))
            return
        except httpx.HTTPError as exc:
            yield StreamChunk(
                type="error",
                error=f"Falha de transporte ao falar com o Gemini em {url}: {exc}",
            )
            return

        aggregated = "".join(text_parts)
        try:
            self._guard_blocked(finish_reason, block_reason, aggregated)
        except ContentBlocked as exc:
            yield StreamChunk(type="error", error=str(exc))
            return

        # Tool calls depois do texto, mesma ordem contratada no OllamaProvider.
        for tc in tool_calls:
            yield StreamChunk(type="tool_call", tool_call=tc)

        yield StreamChunk(
            type="done",
            completion=Completion(
                text=aggregated,
                tool_calls=tool_calls,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model=model_version or self.model,
                finish_reason=finish_reason,
            ),
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """`POST /models/{model}:embedContent`, uma chamada por texto.

        Sem `batchEmbedContents` por enquanto: o volume aqui é de um operador só, e
        um round trip por texto mantém o mapeamento erro→texto óbvio. Modelo de
        geração não tem `embedContent` e cai em `UnsupportedOperation`.
        """
        path = f"/models/{self._embed_model}:embedContent"
        vectors: list[list[float]] = []

        for text in texts:
            payload: dict[str, Any] = {
                "model": f"models/{self._embed_model}",
                "content": {"parts": [{"text": text}]},
            }
            resp = await self._request("POST", path, payload=payload)

            if resp.status_code >= 400:
                detail = _error_detail(resp.text)
                if resp.status_code in (400, 404) and _looks_like_embedding_unsupported(
                    detail
                ):
                    raise UnsupportedOperation(
                        f"O modelo '{self._embed_model}' não expõe embedContent. "
                        "Use um modelo de embedding (ex.: `text-embedding-004`) "
                        f"via `embed_model=`. Detalhe: {detail}"
                    )
                self._raise_for_status(resp, path)

            body = self._json_body(resp, path)
            embedding = body.get("embedding")
            values = (
                _as_list(embedding.get("values")) if isinstance(embedding, dict) else []
            )
            if not values:
                raise UnsupportedOperation(
                    f"Gemini não devolveu vetor para o modelo '{self._embed_model}'."
                )
            vectors.append([float(value) for value in values])

        return vectors

    # -- extras fora do Protocol ------------------------------------------- #

    async def list_models(self) -> list[str]:
        """`GET /models` — nomes que suportam `generateContent`.

        Fora do Protocol: serve para a UI de configurações não ter lista hardcoded
        e para o dono confirmar o identificador real do modelo sem adivinhar.
        """
        resp = await self._request("GET", "/models")
        if resp.status_code >= 400:
            self._raise_for_status(resp, "/models")

        body = self._json_body(resp, "/models")
        names: list[str] = []
        for entry in _as_list(body.get("models")):
            if not isinstance(entry, dict):
                continue
            methods = {
                _as_str(m) for m in _as_list(entry.get("supportedGenerationMethods"))
            }
            if "generateContent" not in methods:
                continue
            name = _as_str(entry.get("name"))
            if name:
                names.append(_bare_model(name))
        return names


if TYPE_CHECKING:

    def _conforms_to_protocol(provider: GeminiProvider) -> LLMProvider:
        """Guarda estática: se `GeminiProvider` deixar de satisfazer o Protocol, o
        `mypy --strict` quebra aqui em vez de no call site do `deps.py`.
        """
        return provider


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "GeminiProvider",
]
