"""Entrada e saída de cada tool de `filesystem`. Daqui sai o `input_schema`.

Modelo por tool, e não um `args: dict` genérico: o schema publicado é o que o
Chief AI lê para montar a chamada, e um campo livre publicaria "passe o que
quiser", que é o mesmo que não publicar nada.

**O caminho é validado aqui, antes de o disco ser tocado.** `..` e `~` morrem no
modelo de entrada, com o nome do campo na mensagem — que é o que `EntradaInvalida`
carrega para quem chamou. A conferência contra a concessão (o caminho está dentro
de `permissions.filesystem`?) é do handler, porque depende da instância; e o
guarda do kernel continua sendo a rede de baixo, negando o `open()` de fato. São
três camadas com papéis diferentes: o modelo pega erro de digitação, o handler
pega escopo, o kernel pega a chamada.

Caminho pode ser relativo à raiz de trabalho ou absoluto. O absoluto é aceito no
modelo e conferido no handler: recusá-lo aqui impediria usar a segunda raiz
concedida, e aceitá-lo sem conferir seria conceder o disco inteiro.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

#: Segmentos que fazem um caminho escapar da raiz concedida.
PROIBIDOS = ("..", "~")

#: Teto de leitura em uma chamada. 1 MiB é o que cabe num prompt sem estourar o
#: contexto; arquivo maior que isso não é caso de `fs_ler`, é caso de outra tool.
MAX_LEITURA = 1024 * 1024

#: Teto de entradas devolvidas por `fs_listar`. Listagem de diretório é a chamada
#: que mais facilmente devolve dezenas de milhares de linhas.
MAX_ENTRADAS = 500


def caminho_seguro(valor: str, *, campo: str, obrigatorio: bool = True) -> str:
    """Recusa o caminho que sai da raiz concedida, antes de qualquer I/O.

    Args:
        valor: o caminho como veio do argumento.
        campo: nome do campo, para a mensagem apontar a linha certa.
        obrigatorio: `False` deixa passar string vazia (a própria raiz).

    Raises:
        ValueError: o Pydantic o converte em `EntradaInvalida` com o campo.
    """
    limpo = valor.strip()
    if not limpo:
        if obrigatorio:
            raise ValueError(f"{campo} não pode ser vazio")
        return ""
    partes = limpo.replace("\\", "/").split("/")
    if any(parte in PROIBIDOS for parte in partes):
        raise ValueError(
            f"{campo} não pode conter {' nem '.join(PROIBIDOS)} — "
            "o caminho tem de ficar dentro da raiz concedida"
        )
    return limpo


class EntradaInfo(BaseModel):
    """Uma linha da listagem.

    `caminho` é relativo à raiz de trabalho para que a saída seja utilizável como
    argumento da próxima chamada sem o chamador ter de recortar prefixo.
    """

    model_config = ConfigDict(frozen=True)

    nome: str
    caminho: str
    tipo: str  # "arquivo" ou "pasta"
    bytes: int = 0


# --------------------------------------------------------------------------- #
# fs_ler
# --------------------------------------------------------------------------- #


class LerEntrada(BaseModel):
    model_config = ConfigDict(frozen=True)

    caminho: str = Field(
        description="Arquivo a ler, relativo à raiz concedida ou absoluto.",
        min_length=1,
        max_length=4096,
    )
    max_bytes: int = Field(
        default=MAX_LEITURA,
        description="Teto de bytes lidos. Arquivo maior é recusado, não truncado.",
        ge=1,
        le=MAX_LEITURA,
    )
    encoding: str = Field(
        default="utf-8", description="Codificação do texto.", max_length=32
    )

    @field_validator("caminho")
    @classmethod
    def _seguro(cls, valor: str) -> str:
        return caminho_seguro(valor, campo="caminho")


class LerSaida(BaseModel):
    model_config = ConfigDict(frozen=True)

    caminho: str
    conteudo: str
    bytes: int


# --------------------------------------------------------------------------- #
# fs_escrever
# --------------------------------------------------------------------------- #


class EscreverEntrada(BaseModel):
    model_config = ConfigDict(frozen=True)

    caminho: str = Field(
        description="Arquivo a gravar, relativo à raiz concedida ou absoluto.",
        min_length=1,
        max_length=4096,
    )
    conteudo: str = Field(description="Conteúdo em texto.")
    anexar: bool = Field(
        default=False,
        description="`true` acrescenta ao fim; `false` substitui o arquivo inteiro.",
    )
    criar_pastas: bool = Field(
        default=True, description="Cria as pastas que faltarem no caminho."
    )
    encoding: str = Field(
        default="utf-8", description="Codificação do texto.", max_length=32
    )

    @field_validator("caminho")
    @classmethod
    def _seguro(cls, valor: str) -> str:
        return caminho_seguro(valor, campo="caminho")


class EscreverSaida(BaseModel):
    model_config = ConfigDict(frozen=True)

    caminho: str
    bytes: int
    #: O arquivo não existia antes da chamada.
    criado: bool


# --------------------------------------------------------------------------- #
# fs_listar
# --------------------------------------------------------------------------- #


class ListarEntrada(BaseModel):
    model_config = ConfigDict(frozen=True)

    caminho: str = Field(
        default="",
        description="Pasta a listar. Vazio lista a própria raiz concedida.",
        max_length=4096,
    )
    recursivo: bool = Field(
        default=False, description="Desce nas subpastas em vez de listar um nível."
    )
    limite: int = Field(
        default=MAX_ENTRADAS,
        description="Teto de entradas devolvidas. O excedente marca `truncado`.",
        ge=1,
        le=MAX_ENTRADAS,
    )

    @field_validator("caminho")
    @classmethod
    def _seguro(cls, valor: str) -> str:
        return caminho_seguro(valor, campo="caminho", obrigatorio=False)


class ListarSaida(BaseModel):
    model_config = ConfigDict(frozen=True)

    entradas: list[EntradaInfo] = Field(default_factory=list)
    total: int = 0
    #: A pasta tinha mais do que `limite`. O chamador sabe que não viu tudo.
    truncado: bool = False


# --------------------------------------------------------------------------- #
# fs_mover / fs_copiar
# --------------------------------------------------------------------------- #


class MoverEntrada(BaseModel):
    model_config = ConfigDict(frozen=True)

    origem: str = Field(
        description="Arquivo ou pasta a mover.", min_length=1, max_length=4096
    )
    destino: str = Field(
        description="Caminho de destino, arquivo ou pasta.",
        min_length=1,
        max_length=4096,
    )
    sobrescrever: bool = Field(
        default=False, description="Permite substituir um destino que já existe."
    )

    @field_validator("origem", "destino")
    @classmethod
    def _seguro(cls, valor: str, info: ValidationInfo) -> str:
        return caminho_seguro(valor, campo=info.field_name or "caminho")


class MoverSaida(BaseModel):
    model_config = ConfigDict(frozen=True)

    origem: str
    destino: str


class CopiarEntrada(MoverEntrada):
    """Mesmos campos de `MoverEntrada`. Modelo próprio porque o schema publicado
    é por tool: reusar o nome faria as duas tools aparecerem com o mesmo `title`
    no catálogo, e o catálogo é o que o Chief AI lê para escolher."""


class CopiarSaida(BaseModel):
    model_config = ConfigDict(frozen=True)

    origem: str
    destino: str
    #: Quantos arquivos foram copiados. Pasta copiada conta os arquivos dentro.
    arquivos: int


# --------------------------------------------------------------------------- #
# fs_apagar
# --------------------------------------------------------------------------- #


class ApagarEntrada(BaseModel):
    model_config = ConfigDict(frozen=True)

    caminho: str = Field(
        description="Arquivo ou pasta a apagar.", min_length=1, max_length=4096
    )
    recursivo: bool = Field(
        default=False,
        description=(
            "Exigido para apagar pasta com conteúdo. Sem isto, pasta não vazia é "
            "recusada."
        ),
    )
    ausente_ok: bool = Field(
        default=False, description="`true` faz caminho inexistente não ser erro."
    )

    @field_validator("caminho")
    @classmethod
    def _seguro(cls, valor: str) -> str:
        return caminho_seguro(valor, campo="caminho")


class ApagarSaida(BaseModel):
    model_config = ConfigDict(frozen=True)

    caminho: str
    #: Arquivos removidos. Pasta apagada conta os arquivos que havia dentro.
    apagados: int
    #: O caminho não existia e `ausente_ok` estava ligado.
    ausente: bool = False


# --------------------------------------------------------------------------- #
# fs_criar_pasta
# --------------------------------------------------------------------------- #


class CriarPastaEntrada(BaseModel):
    model_config = ConfigDict(frozen=True)

    caminho: str = Field(
        description="Pasta a criar, com os níveis intermediários.",
        min_length=1,
        max_length=4096,
    )
    existe_ok: bool = Field(
        default=True, description="`false` faz pasta já existente ser erro."
    )

    @field_validator("caminho")
    @classmethod
    def _seguro(cls, valor: str) -> str:
        return caminho_seguro(valor, campo="caminho")


class CriarPastaSaida(BaseModel):
    model_config = ConfigDict(frozen=True)

    caminho: str
    #: `False` quando a pasta já existia e `existe_ok` estava ligado.
    criado: bool


__all__ = [
    "MAX_ENTRADAS",
    "MAX_LEITURA",
    "PROIBIDOS",
    "ApagarEntrada",
    "ApagarSaida",
    "CopiarEntrada",
    "CopiarSaida",
    "CriarPastaEntrada",
    "CriarPastaSaida",
    "EntradaInfo",
    "EscreverEntrada",
    "EscreverSaida",
    "LerEntrada",
    "LerSaida",
    "ListarEntrada",
    "ListarSaida",
    "MoverEntrada",
    "MoverSaida",
    "caminho_seguro",
]
