"""Schemas de entrada e saída da capability `http`."""

from __future__ import annotations

from capabilities.http.schemas.models import (
    MAX_CORPO,
    MAX_RESPOSTA,
    TIMEOUT_MAX,
    TIMEOUT_PADRAO,
    GetEntrada,
    PostEntrada,
    RespostaSaida,
    host_de,
    url_segura,
)

__all__ = [
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
