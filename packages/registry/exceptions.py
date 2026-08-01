"""Erros do Capability Registry."""

from __future__ import annotations


class RegistryError(Exception):
    """Base dos erros do registry."""


class CapabilityGapDetected(RegistryError):
    """Lacuna de capacidade.

    **Não é mais levantada por `resolve()`** (D-2): desde a v1.1 o miss é o
    evento `capability.gap_detected` e o retorno `None`. `plan.md` §6 quer que a
    tarefa *pare* e o goal vá para `blocked` — exceção subindo até o Chief AI
    fazia o oposto, porque quem trata `except` improvisa, e improviso é
    exatamente o que a auto-evolução existe para não precisar.

    A classe continua aqui como tipo de erro para quem *exige* uma capability
    nomeada e não tem o que fazer sem ela — o adaptador de runtime da v1.2,
    quando mandam executar uma capability que sumiu do disco entre o
    planejamento e a execução.
    """

    def __init__(self, intent: str, context: str = "") -> None:
        self.intent = intent
        self.context = context
        super().__init__(f"Nenhuma capability para a intenção: {intent}")


class ManifestLoadError(RegistryError):
    """`manifest.yaml` ausente, ilegível ou fora do schema."""


class InvalidCapabilityStateError(RegistryError):
    """Capability não está no estado exigido pela operação."""


__all__ = [
    "CapabilityGapDetected",
    "InvalidCapabilityStateError",
    "ManifestLoadError",
    "RegistryError",
]
