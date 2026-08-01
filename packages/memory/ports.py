"""Portas internas da memória.

Ficam aqui, e não em `packages/shared/ports.py`, porque só a memória as
implementa e só a memória as consome: porta compartilhada existe para separar
`packages/` de `apps/`, e nenhuma destas atravessa essa fronteira. A única que
atravessa — `VectorStore` — está no contrato compartilhado, porque o adapter
LanceDB dela é escolhido por configuração da app.

Roda sob `mypy` com `check_untyped_defs`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable
from uuid import UUID

from packages.memory.models import (
    ExperienceRecord,
    IndexedDocument,
    WorkingMemoryState,
)


@runtime_checkable
class WorkingMemoryStore(Protocol):
    """Persistência do estado vivo da task.

    O adapter default é arquivo JSON (um por task): o requisito é sobreviver a um
    `kill -9`, e para isso o dado precisa estar em disco no instante do
    checkpoint — não no fim do processo, não num buffer.
    """

    async def load(self, task_id: UUID) -> WorkingMemoryState | None: ...

    async def save(self, state: WorkingMemoryState) -> None: ...

    async def delete(self, task_id: UUID) -> bool: ...


@runtime_checkable
class KnowledgeIndex(Protocol):
    """Catálogo do que já foi indexado: `doc_id` → hash + ids dos chunks.

    É o que torna a reindexação **incremental**. Sem ele, "ingerir de novo" seria
    recalcular todo embedding de todo documento a cada varredura — e embedding é
    a operação cara desta camada.
    """

    async def get(self, doc_id: str) -> IndexedDocument | None: ...

    async def put(self, entry: IndexedDocument) -> None: ...

    async def delete(self, doc_id: str) -> IndexedDocument | None: ...

    async def all(self) -> list[IndexedDocument]: ...


@runtime_checkable
class ExperienceStore(Protocol):
    """Persistência dos padrões extraídos de execução. Cresce por acúmulo."""

    async def get(self, record_id: str) -> ExperienceRecord | None: ...

    async def put(self, record: ExperienceRecord) -> None: ...

    async def all(self) -> list[ExperienceRecord]: ...

    async def delete(self, record_ids: Sequence[str]) -> int: ...


__all__ = [
    "ExperienceStore",
    "KnowledgeIndex",
    "WorkingMemoryStore",
]
