from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

TIMEOUT_PADRAO = 30.0
TIMEOUT_MAX = 300.0
MAX_SAIDA = 64 * 1024

class GitEntrada(BaseModel):
    model_config = ConfigDict(frozen=True)

    argumentos: list[str] = Field(
        description="Argumentos para passar ao comando git.",
        min_length=1,
    )
    cwd: str = Field(
        default="",
        description="Diretório de trabalho relativo ou absoluto. Vazio usa a raiz concedida.",
    )
    timeout: float = Field(
        default=TIMEOUT_PADRAO,
        description="Timeout da execução.",
        gt=0,
        le=TIMEOUT_MAX,
    )

class GitSaida(BaseModel):
    model_config = ConfigDict(frozen=True)

    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    truncado: bool = False
    expirou: bool = False
