"""Kernel do Jarvis — a infraestrutura de execução, abaixo dos agentes.

`event_bus/` veio na v1.1 (primeiro uso real do bus, D-12). `runtime/`,
`permissions/` e o `Kernel` entraram na v1.2, cada um quando teve código que roda:
`plan-execution.md` §2 recusou criar pasta vazia para "definir domínio", porque
isso gera import morto e dúvida sobre onde a coisa mora.

Fronteira: o Chief AI **nunca** importa este pacote (`tests/test_architecture.py`
verifica por AST). Quem executa é a camada de execução; quem decide, não.
"""

from packages.kernel.kernel import Kernel

__all__ = ["Kernel"]
