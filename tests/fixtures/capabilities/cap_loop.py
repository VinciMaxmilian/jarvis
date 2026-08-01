"""Capability que nunca termina. Existe para provar que o supervisor a mata.

Laço ocupado (e não `sleep`) de propósito: `sleep` seria morto por qualquer
supervisor, inclusive um que só esperasse o processo. Queimar CPU é o caso que
distingue "o supervisor mata" de "o processo desistiu sozinho".
"""

from __future__ import annotations

from typing import Any


def handler(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool == "travar":
        while True:
            pass
    raise ValueError(f"tool desconhecida: {tool!r}")
