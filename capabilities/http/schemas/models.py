"""Entrada e saída das tools de `http`. Daqui sai o `input_schema`.

A URL é validada **aqui**: esquema `http`/`https`, host presente, sem credencial
embutida (`http://user:senha@host`). O host extraído por `host_de()` é o mesmo que
o handler confere contra `permissions.network` — extrair em dois lugares com dois
parsers é como se conferiria um host e se contataria outro.

Cabeçalho com `\\r` ou `\\n` no valor é recusado. Não é preciosismo: é injeção de
cabeçalho, a forma clássica de transformar uma requisição em duas.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Espera padrão. 15 s é o que separa "a API está lenta" de "a API caiu".
TIMEOUT_PADRAO = 15.0

#: Teto de espera. Requisição mais longa que isto é job, não tool síncrona.
TIMEOUT_MAX = 120.0

#: Teto de corpo lido. 1 MiB é o que cabe num `Task.output` sem estourar o
#: contexto do Chief AI; acima disso o corpo é **cortado** e marcado, não recusado
#: — diferente de `filesystem.fs_ler`, porque aqui o começo da resposta costuma
#: ser a resposta (cabeçalho de JSON, primeira página de HTML).
MAX_RESPOSTA = 1024 * 1024

#: Teto de corpo enviado num POST.
MAX_CORPO = 1024 * 1024

#: Os únicos esquemas que esta capability fala.
ESQUEMAS = ("http", "https")


def host_de(url: str) -> str:
    """O host da URL, em minúsculas e sem porta. Vazio se não houver.

    Sem porta de propósito: `permissions.network` é lista de hosts, e conceder
    `api.exemplo.com` conceder `api.exemplo.com:8443` é a leitura que o dono faz
    do arquivo. O kernel aplica a mesma regra sobre `connect()`.
    """
    return (urlsplit(url).hostname or "").lower()


def url_segura(valor: str, *, campo: str = "url") -> str:
    """Recusa a URL que esta capability não sabe ou não deve buscar."""
    limpo = valor.strip()
    if not limpo:
        raise ValueError(f"{campo} não pode ser vazio")

    partes = urlsplit(limpo)
    if partes.scheme.lower() not in ESQUEMAS:
        raise ValueError(
            f"{campo} tem de começar com {' ou '.join(ESQUEMAS)}, veio "
            f"{partes.scheme or '<sem esquema>'!r}"
        )
    if not partes.hostname:
        raise ValueError(f"{campo} não tem host: {valor!r}")
    if partes.username or partes.password:
        raise ValueError(
            f"{campo} não pode trazer credencial embutida — use o campo headers"
        )
    return limpo


def _headers_seguros(valor: dict[str, str]) -> dict[str, str]:
    """Recusa injeção de cabeçalho. `\\r\\n` num valor vira uma segunda requisição."""
    for nome, conteudo in valor.items():
        if any(c in nome or c in conteudo for c in ("\r", "\n")):
            raise ValueError(
                f"headers[{nome!r}] tem quebra de linha — isso é injeção de "
                "cabeçalho, não um valor"
            )
    return valor


class _Comum(BaseModel):
    """O que `http_get` e `http_post` têm em comum. Não é tool, é reuso de campo."""

    model_config = ConfigDict(frozen=True)

    url: str = Field(
        description="URL completa, http ou https.", min_length=1, max_length=4096
    )
    headers: dict[str, str] = Field(
        default_factory=dict, description="Cabeçalhos da requisição."
    )
    timeout: float = Field(
        default=TIMEOUT_PADRAO,
        description="Segundos até a requisição ser abandonada.",
        gt=0,
        le=TIMEOUT_MAX,
    )
    max_bytes: int = Field(
        default=MAX_RESPOSTA,
        description="Teto do corpo lido. Acima disso a resposta volta cortada.",
        ge=1,
        le=MAX_RESPOSTA,
    )

    @field_validator("url")
    @classmethod
    def _url(cls, valor: str) -> str:
        return url_segura(valor)

    @field_validator("headers")
    @classmethod
    def _headers(cls, valor: dict[str, str]) -> dict[str, str]:
        return _headers_seguros(valor)


class GetEntrada(_Comum):
    """Argumentos de `http_get`."""


class PostEntrada(_Comum):
    """Argumentos de `http_post`."""

    corpo: str = Field(
        default="",
        description="Corpo da requisição, em texto.",
        max_length=MAX_CORPO,
    )
    content_type: str = Field(
        default="application/json",
        description="Valor do cabeçalho Content-Type.",
        max_length=128,
    )

    @field_validator("content_type")
    @classmethod
    def _content_type(cls, valor: str) -> str:
        if any(c in valor for c in ("\r", "\n")):
            raise ValueError("content_type não pode ter quebra de linha")
        return valor.strip()


class RespostaSaida(BaseModel):
    """A resposta como o Chief AI a lê.

    `status_code` fora da faixa 2xx **não** é falha da tool: a requisição foi
    feita e o servidor respondeu 404. Falha da tool é não conseguir requisitar —
    host não concedido, DNS que não resolve, conexão recusada, timeout.
    """

    model_config = ConfigDict(frozen=True)

    url: str
    status_code: int
    headers: dict[str, str] = Field(default_factory=dict)
    corpo: str = ""
    bytes: int = 0
    #: O corpo bateu em `max_bytes` e foi cortado.
    truncado: bool = False


__all__ = [
    "ESQUEMAS",
    "MAX_CORPO",
    "MAX_RESPOSTA",
    "TIMEOUT_MAX",
    "TIMEOUT_PADRAO",
    "GetEntrada",
    "PostEntrada",
    "RespostaSaida",
    "host_de",
    "url_segura",
]
