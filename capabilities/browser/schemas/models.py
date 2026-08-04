from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

class ExtrairEntrada(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str = Field(
        description="URL para extrair o texto.",
        min_length=1,
    )
    timeout: float = Field(
        default=30.0,
        description="Timeout da requisição HTTP.",
        gt=0,
    )

class ExtrairSaida(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    texto: str
    erro: str = ""
