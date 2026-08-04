"""Entrada e saída das tools de `shell`. Daqui sai o `input_schema`.

**O programa e os argumentos são campos separados, e `argumentos` é uma lista.**
Essa é a decisão de segurança mais importante do módulo, e ela mora no schema, não
no handler: um campo único `comando: str` só poderia ser executado passando por um
shell, e passar por um shell é o que transforma `; rm -rf /` num argumento válido.
Com programa e lista de argumentos, `subprocess` recebe o vetor pronto e não há
interpretação de `;`, `|`, `&&`, `>` nem expansão de `*` por ninguém.

`programa` é obrigatoriamente um **nome simples**: sem barra, sem `..`, sem letra
de unidade. Quem escolhe o executável é a allowlist mais o `PATH`, não o chamador
— aceitar `/tmp/meu_binario` faria a allowlist virar decoração, porque bastaria
gravar um arquivo com nome permitido em qualquer lugar.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Espera padrão de um comando. 30 s é o que separa "compilou" de "travou".
TIMEOUT_PADRAO = 30.0

#: Teto de espera. Comando que precisa de mais que isto não é caso de tool
#: síncrona — o kernel tem supervisor e job agendado para trabalho longo.
TIMEOUT_MAX = 300.0

#: Teto de cada fluxo capturado. Saída maior é cortada e marcada em `truncado`:
#: um `find /` inteiro no `Task.output` estoura o contexto do Chief AI e não
#: acrescenta nada ao que as primeiras dezenas de KiB já disseram.
MAX_SAIDA = 64 * 1024

#: Teto de argumentos. Não é limite técnico, é limite de superfície.
MAX_ARGUMENTOS = 64

#: O que faz um nome deixar de ser um nome simples de programa.
SEPARADORES = ("/", "\\", ":")


class ExecutarEntrada(BaseModel):
    model_config = ConfigDict(frozen=True)

    programa: str = Field(
        description=(
            "Nome do executável, sem caminho. Tem de estar na allowlist e no PATH."
        ),
        min_length=1,
        max_length=128,
    )
    argumentos: list[str] = Field(
        default_factory=list,
        description=(
            "Argumentos, um por item. Não passam por shell: `;` e `|` são texto "
            "literal, não operadores."
        ),
        max_length=MAX_ARGUMENTOS,
    )
    cwd: str = Field(
        default="",
        description=(
            "Diretório de trabalho, relativo à raiz concedida ou absoluto dentro "
            "dela. Vazio usa a própria raiz."
        ),
        max_length=4096,
    )
    timeout: float = Field(
        default=TIMEOUT_PADRAO,
        description="Segundos até o processo ser morto.",
        gt=0,
        le=TIMEOUT_MAX,
    )

    @field_validator("programa")
    @classmethod
    def _nome_simples(cls, valor: str) -> str:
        limpo = valor.strip()
        if not limpo:
            raise ValueError("programa não pode ser vazio")
        if any(sep in limpo for sep in SEPARADORES):
            raise ValueError(
                "programa tem de ser um nome simples, sem caminho — quem escolhe o "
                f"executável é a allowlist mais o PATH; veio {valor!r}"
            )
        if limpo.startswith("-") or ".." in limpo:
            raise ValueError(f"programa inválido: {valor!r}")
        return limpo

    @field_validator("cwd")
    @classmethod
    def _cwd_seguro(cls, valor: str) -> str:
        limpo = valor.strip()
        if not limpo:
            return ""
        partes = limpo.replace("\\", "/").split("/")
        if any(parte in ("..", "~") for parte in partes):
            raise ValueError(
                "cwd não pode conter .. nem ~ — o diretório de trabalho tem de "
                "ficar dentro da raiz concedida"
            )
        return limpo


class ExecutarSaida(BaseModel):
    """O resultado bruto do processo. Sucesso e fracasso saem pelo mesmo campo.

    `exit_code` diferente de zero **não** é erro da tool: o comando rodou e disse
    que falhou, e essa é a resposta que quem perguntou queria. Erro da tool é o
    comando que não pôde ser executado — fora da allowlist, ausente do `PATH`,
    `cwd` fora do escopo. A diferença importa porque o Chief AI trata `Task`
    falhada e `Task` bem-sucedida com saída ruim de formas diferentes.
    """

    model_config = ConfigDict(frozen=True)

    programa: str
    argumentos: list[str] = Field(default_factory=list)
    #: `None` quando o processo foi morto pelo timeout: não houve código de saída.
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    #: Algum dos fluxos bateu em `MAX_SAIDA` e foi cortado.
    truncado: bool = False
    #: O processo estourou `timeout` e foi morto.
    expirou: bool = False
    cwd: str = ""


class PermitidosEntrada(BaseModel):
    """Sem argumento. O modelo existe para a tool ter schema como todas as outras."""

    model_config = ConfigDict(frozen=True)


class PermitidosSaida(BaseModel):
    model_config = ConfigDict(frozen=True)

    permitidos: list[str] = Field(default_factory=list)
    total: int = 0


__all__ = [
    "MAX_ARGUMENTOS",
    "MAX_SAIDA",
    "SEPARADORES",
    "TIMEOUT_MAX",
    "TIMEOUT_PADRAO",
    "ExecutarEntrada",
    "ExecutarSaida",
    "PermitidosEntrada",
    "PermitidosSaida",
]
