"""Entrada e saída de cada tool. É daqui que sai o `input_schema` do manifest.

Modelo por tool, e não um modelo genérico com `dict[str, Any]`: o schema publicado
é o que o Chief AI lê para montar a chamada, e um campo `args: dict` publicaria
"passe o que quiser", que é o mesmo que não publicar nada.

O caminho relativo é validado **aqui**, no modelo de entrada, e não no handler: a
recusa acontece antes de qualquer I/O e a mensagem sai com o nome do campo, que é
o que o `EntradaInvalida` do SDK carrega para quem chamou. O guarda de permissões
do kernel continua sendo a rede de baixo — ele nega o `open()` de fato —, mas rede
de baixo não é lugar de pegar erro de digitação: ela devolve task falhada, não
"você escreveu `..` no nome do arquivo".
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Segmentos que fazem um caminho relativo deixar de ser relativo.
PROIBIDOS = ("..", "~")


def caminho_seguro(valor: str, *, campo: str) -> str:
    """Recusa o que sai da raiz concedida antes de o disco ser tocado."""
    if valor.startswith(("/", "\\")) or ":" in valor:
        raise ValueError(f"{campo} tem de ser relativo à raiz do NAS, veio {valor!r}")
    partes = valor.replace("\\", "/").split("/")
    if any(parte in PROIBIDOS for parte in partes):
        raise ValueError(f"{campo} não pode conter {' nem '.join(PROIBIDOS)}")
    return valor


class ArquivoInfo(BaseModel):
    """Uma entrada da listagem. `bytes` é o tamanho em disco."""

    model_config = ConfigDict(frozen=True)

    nome: str
    bytes: int


class ListarEntrada(BaseModel):
    model_config = ConfigDict(frozen=True)

    subcaminho: str = Field(
        default="",
        description="Pasta dentro da raiz concedida. Vazio lista a própria raiz.",
        max_length=255,
    )

    @field_validator("subcaminho")
    @classmethod
    def _seguro(cls, valor: str) -> str:
        return caminho_seguro(valor, campo="subcaminho")


class ListarSaida(BaseModel):
    model_config = ConfigDict(frozen=True)

    arquivos: list[ArquivoInfo] = Field(default_factory=list)
    total: int = 0


class GravarEntrada(BaseModel):
    model_config = ConfigDict(frozen=True)

    nome: str = Field(
        description="Nome do arquivo, relativo à raiz concedida.",
        min_length=1,
        max_length=255,
    )
    conteudo: str = Field(description="Conteúdo em texto UTF-8.")

    @field_validator("nome")
    @classmethod
    def _seguro(cls, valor: str) -> str:
        return caminho_seguro(valor, campo="nome")


class GravarSaida(BaseModel):
    model_config = ConfigDict(frozen=True)

    caminho: str
    bytes: int


class StatusEntrada(BaseModel):
    """Sem argumento. O modelo existe para a tool ter schema como todas as outras."""

    model_config = ConfigDict(frozen=True)


class StatusSaida(BaseModel):
    model_config = ConfigDict(frozen=True)

    host: str
    porta: int
    online: bool


__all__ = [
    "PROIBIDOS",
    "ArquivoInfo",
    "GravarEntrada",
    "GravarSaida",
    "ListarEntrada",
    "ListarSaida",
    "StatusEntrada",
    "StatusSaida",
    "caminho_seguro",
]
