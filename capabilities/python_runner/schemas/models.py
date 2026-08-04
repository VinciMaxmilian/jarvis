from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

TIMEOUT_PADRAO = 30.0
TIMEOUT_MAX = 300.0
MAX_SAIDA = 64 * 1024

class RunPythonEntrada(BaseModel):
    model_config = ConfigDict(frozen=True)

    codigo: str = Field(
        description="Código Python a ser executado.",
        min_length=1,
    )
    timeout: float = Field(
        default=TIMEOUT_PADRAO,
        description="Segundos até o processo ser morto.",
        gt=0,
        le=TIMEOUT_MAX,
    )

class RunPythonSaida(BaseModel):
    model_config = ConfigDict(frozen=True)

    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    truncado: bool = False
    expirou: bool = False
