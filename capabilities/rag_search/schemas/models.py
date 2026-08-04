from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

class BuscarEntrada(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str = Field(
        description="Termo ou pergunta a buscar na base de conhecimento.",
        min_length=1,
    )
    limite: int = Field(
        default=5,
        description="Número máximo de resultados.",
        gt=0,
    )

class ResultadoBusca(BaseModel):
    model_config = ConfigDict(frozen=True)
    
    documento: str
    trecho: str
    score: float = 1.0

class BuscarSaida(BaseModel):
    model_config = ConfigDict(frozen=True)

    resultados: list[ResultadoBusca] = Field(default_factory=list)
    query: str
