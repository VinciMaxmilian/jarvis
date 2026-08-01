"""Porta de persistência do catálogo de capabilities.

Mora aqui, e não em `packages/shared/ports.py`, porque o contrato que ela move
(`CapabilityRecord`) é do registry e ainda não é vocabulário do sistema inteiro.
Quando um segundo pacote precisar dele, a porta sobe para `shared/ports.py` —
mover uma `Protocol` custa um import; nascer no lugar errado custa a fronteira.

O adaptador é `PgCapabilityStore`, em `apps/api/db/repository.py`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from packages.registry.records import CapabilityHealth, CapabilityRecord


@runtime_checkable
class CapabilityStore(Protocol):
    """Persistência do catálogo. `runtime_checkable` para o dublê da suíte ser
    verificado contra a mesma porta que o adaptador Postgres implementa."""

    async def upsert(self, record: CapabilityRecord) -> CapabilityRecord:
        """Grava a capability, casando por `name` — a chave estável em disco."""
        ...

    async def list_all(self) -> list[CapabilityRecord]: ...

    async def get_by_name(self, name: str) -> CapabilityRecord | None: ...

    async def mark_used(self, name: str, when: datetime) -> None: ...

    async def set_health(self, name: str, health: CapabilityHealth) -> None: ...


__all__ = ["CapabilityStore"]
