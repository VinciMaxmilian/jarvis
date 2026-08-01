"""Portas (Protocols) entre camadas.

`packages/` define a porta; `apps/` fornece o adaptador. É isto que impede
`packages.agents` de importar SQLAlchemy e o orchestrator de importar `apps/`.

Roda sob `mypy --strict`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from packages.shared.contracts import (
    ChatMessage,
    Event,
    Goal,
    GoalStatus,
    Task,
    TaskStatus,
    ToolSpec,
)


@runtime_checkable
class GoalStore(Protocol):
    """Persistência de objetivos e tarefas. Implementado em `apps/api/db`."""

    async def create_goal(self, goal: Goal) -> Goal: ...

    async def get_goal(self, goal_id: UUID) -> Goal | None: ...

    async def list_goals(
        self, status: GoalStatus | None = None, limit: int = 50
    ) -> list[Goal]: ...

    async def update_goal_status(
        self, goal_id: UUID, status: GoalStatus
    ) -> Goal | None: ...

    async def create_tasks(self, tasks: Sequence[Task]) -> list[Task]: ...

    async def get_task(self, task_id: UUID) -> Task | None: ...

    async def list_tasks(self, goal_id: UUID) -> list[Task]: ...

    async def update_task(self, task: Task) -> Task: ...

    async def next_pending_task(self, goal_id: UUID) -> Task | None:
        """Primeira tarefa `pending` cujas dependências já estão `done`."""
        ...


@runtime_checkable
class ConversationStore(Protocol):
    """Persistência de conversa. Implementado em `apps/api/db`."""

    async def append(self, message: ChatMessage) -> ChatMessage: ...

    async def history(
        self, conversation_id: UUID, limit: int = 50
    ) -> list[ChatMessage]: ...

    async def ensure_conversation(self, conversation_id: UUID) -> UUID: ...


@runtime_checkable
class ToolExecutor(Protocol):
    """Catálogo executável de tools. Na v0 são tools nativas; na v1 vira o
    Capability Registry, e um miss deixa de ser exceção e vira evento."""

    def specs(self) -> list[ToolSpec]: ...

    def has(self, name: str) -> bool: ...

    async def execute(
        self, name: str, arguments: dict[str, object], dry_run: bool = False
    ) -> dict[str, object]: ...


@runtime_checkable
class EventBus(Protocol):
    """asyncio.Queue na v0; Redis Streams na v2. O contrato não muda."""

    async def publish(self, event: Event) -> None: ...


# --------------------------------------------------------------------------- #
# Vetores — memória `knowledge` e `long` (v1.3)
# --------------------------------------------------------------------------- #
#
# Por que a porta existe, e não uma chamada direta ao LanceDB: nesta máquina o
# `import lancedb` NÃO levanta ImportError — ele MATA o processo com SIGILL
# (exit 132). O binário Rust do LanceDB exige AVX2/FMA/BMI2 e o i5-3470 (Ivy
# Bridge, 2012) tem só `avx f16c sse4_2`. É a mesma parede que tirou o KoboldCpp
# do projeto (`plan-execution.md` §v1.0b), e não há pin de versão que resolva:
# o `pip install` funciona, o import é que morre.
#
# Consequência de arquitetura, não gambiarra: o LanceDB continua sendo a escolha
# da v1 (`tools.md` §1.4 — embarcado, backup é copiar o diretório) e o adapter
# fica escrito e completo, exatamente como o do Ollama; quem decide qual dos dois
# roda é configuração. O default é o adapter em memória, que roda em qualquer
# CPU. Ver `packages/memory/vector_store.py`.


class VectorRecord(BaseModel):
    """Unidade indexável: o texto, o vetor dele e a proveniência.

    `embedding` vem SEMPRE de `LLMProvider.embed()` — nenhum módulo do sistema
    importa SDK de embedding direto, pela mesma razão que nenhum importa SDK de
    chat (`packages/llm/base.py`).
    """

    model_config = ConfigDict(from_attributes=True)

    id: str  # estável e derivável da fonte: reindexar não duplica
    namespace: str = "default"  # separa `knowledge` de `long_term` na mesma base
    text: str
    embedding: list[float]
    metadata: dict[str, str] = Field(default_factory=dict)


class VectorMatch(BaseModel):
    """Vizinho devolvido pela busca. `score` é similaridade: maior é melhor."""

    model_config = ConfigDict(from_attributes=True)

    record: VectorRecord
    score: float


@runtime_checkable
class VectorStore(Protocol):
    """Índice vetorial. Em memória por default; LanceDB onde a CPU permitir."""

    async def upsert(self, records: Sequence[VectorRecord]) -> int:
        """Insere ou substitui por `id`. Devolve quantos registros entraram."""
        ...

    async def search(
        self,
        embedding: Sequence[float],
        *,
        namespace: str = "default",
        limit: int = 5,
    ) -> list[VectorMatch]:
        """Top-k por similaridade, do mais próximo ao mais distante."""
        ...

    async def delete(self, ids: Sequence[str]) -> int:
        """Remove por `id`. Devolve quantos existiam de fato."""
        ...

    async def get_all(self, *, namespace: str | None = None) -> list[VectorRecord]:
        """Retorna todos os registros, opcionalmente filtrados por namespace."""
        ...


class ToolNotFound(Exception):
    """Miss no catálogo de tools. Na v1 vira `CapabilityGapDetected`."""

    def __init__(self, name: str) -> None:
        super().__init__(f"tool não registrada: {name}")
        self.name = name


__all__ = [
    "ConversationStore",
    "EventBus",
    "GoalStore",
    "GoalStatus",
    "TaskStatus",
    "ToolExecutor",
    "ToolNotFound",
    "VectorMatch",
    "VectorRecord",
    "VectorStore",
]
