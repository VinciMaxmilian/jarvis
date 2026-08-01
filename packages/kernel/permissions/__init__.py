"""Permissões do kernel: a decisão (`policy`) e quem a aplica (`guard`).

`guard` não é reexportado aqui de propósito. Importá-lo tem efeito colateral
global no processo (troca `builtins.open`, `socket.connect` e `subprocess.Popen`)
e só faz sentido dentro do subprocesso da capability — quem precisa dele escreve
o import completo, e o import completo é o aviso.
"""

from packages.kernel.permissions.policy import (
    MODOS_DE_ESCRITA,
    PermissionPolicy,
    modo_escreve,
)

__all__ = ["MODOS_DE_ESCRITA", "PermissionPolicy", "modo_escreve"]
