"""Capability que tenta sair para a rede. Existe para provar que ela não sai.

Usa `socket` cru em vez de `httpx`: o guarda faz patch em `socket.socket.connect`,
`connect_ex`, `create_connection` e `getaddrinfo` justamente porque é por lá que
toda biblioteca HTTP passa. Testar com a camada mais baixa prova o ponto de
verdade; testar com `httpx` provaria só que o `httpx` usa socket.
"""

from __future__ import annotations

import socket
from typing import Any


def handler(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool == "buscar":
        host = str(arguments.get("host", "1.1.1.1"))
        porta = int(arguments.get("porta", 80))
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            s.connect((host, porta))
        return {"conectou": True}

    if tool == "resolver":
        socket.getaddrinfo(str(arguments.get("host", "example.com")), 80)
        return {"resolveu": True}

    raise ValueError(f"tool desconhecida: {tool!r}")
