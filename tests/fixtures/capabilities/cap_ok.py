"""Capability de exemplo que funciona. Roda de verdade, em subprocesso.

Mora sob `tests/` e não em `capabilities/` de propósito: o `discover()` do
registry confere o digest do diretório de cada capability instalada contra
`approved_commit` (D-3), e uma capability de teste que muda a cada edição faria a
suíte do registry reprovar por integridade. Aqui ela é só um módulo importável.

O contrato do entrypoint é `(tool, arguments) -> dict`, definido por
`packages/kernel/runtime/_child.py`. `dry_run` é o terceiro parâmetro opcional: o
`_child` só o passa a quem o declara, e é ele que transforma o log do Gate 2 de
"importou" em "faria isto".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def handler(
    tool: str, arguments: dict[str, Any], dry_run: bool = False
) -> dict[str, Any]:
    if tool == "somar":
        parcelas = [int(n) for n in arguments.get("parcelas", [])]
        if dry_run:
            return {"dry_run": True, "somaria": len(parcelas), "executado": False}
        return {"total": sum(parcelas)}

    if tool == "escrever":
        # Escrita dentro do diretório da capability: o guarda permite, e é o
        # caminho que prova que `write_roots` não nega o que foi declarado.
        destino = Path(arguments["nome"])
        if dry_run:
            return {"dry_run": True, "escreveria": str(destino), "executado": False}
        destino.write_text(str(arguments.get("conteudo", "")), encoding="utf-8")
        return {"escrito": str(destino)}

    raise ValueError(f"tool desconhecida: {tool!r}")
