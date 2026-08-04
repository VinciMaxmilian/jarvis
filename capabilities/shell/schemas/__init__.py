"""Schemas de entrada e saída da capability `shell`."""

from __future__ import annotations

from capabilities.shell.schemas.models import (
    MAX_ARGUMENTOS,
    MAX_SAIDA,
    TIMEOUT_MAX,
    TIMEOUT_PADRAO,
    ExecutarEntrada,
    ExecutarSaida,
    PermitidosEntrada,
    PermitidosSaida,
)

__all__ = [
    "MAX_ARGUMENTOS",
    "MAX_SAIDA",
    "TIMEOUT_MAX",
    "TIMEOUT_PADRAO",
    "ExecutarEntrada",
    "ExecutarSaida",
    "PermitidosEntrada",
    "PermitidosSaida",
]
