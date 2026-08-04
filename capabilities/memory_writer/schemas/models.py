from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

class EscreverEntrada(BaseModel):
    model_config = ConfigDict(frozen=True)

    anotacao: str = Field(
        description="Fato ou preferência a ser guardada na memória longa.",
        min_length=1,
    )

class EscreverSaida(BaseModel):
    model_config = ConfigDict(frozen=True)

    sucesso: bool = True
    caminho: str
