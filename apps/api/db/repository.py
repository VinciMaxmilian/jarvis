"""Implementação concreta de GoalStore, ConversationStore e CapabilityStore.

Adaptador SQLAlchemy ↔ contratos Pydantic. Nenhum outro módulo toca no ORM: as
portas ficam em `packages/shared/ports.py` e `packages/registry/ports.py`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.models import (
    CapabilityRow,
    ChatMessageRow,
    ConversationRow,
    GoalRow,
    TaskRow,
)
from packages.registry.records import CapabilityHealth, CapabilityRecord
from packages.shared.contracts import (
    ChatMessage,
    Goal,
    GoalStatus,
    Task,
    TaskStatus,
    utcnow,
)


class PgGoalStore:
    """GoalStore backed by Postgres."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create_goal(self, goal: Goal) -> Goal:
        row = GoalRow(
            id=goal.id,
            title=goal.title,
            description=goal.description,
            status=goal.status,
            priority=goal.priority,
            parent_goal_id=goal.parent_goal_id,
            context=goal.context,
            created_at=goal.created_at,
            updated_at=goal.updated_at,
        )
        self._s.add(row)
        await self._s.flush()
        return goal

    async def get_goal(self, goal_id: UUID) -> Goal | None:
        row = await self._s.get(GoalRow, goal_id)
        if row is None:
            return None
        return Goal.model_validate(row)

    async def list_goals(
        self, status: GoalStatus | None = None, limit: int = 50
    ) -> list[Goal]:
        stmt = select(GoalRow).order_by(GoalRow.created_at.desc()).limit(limit)
        if status is not None:
            stmt = stmt.where(GoalRow.status == status)
        result = await self._s.execute(stmt)
        return [Goal.model_validate(r) for r in result.scalars()]

    async def update_goal_status(
        self, goal_id: UUID, status: GoalStatus
    ) -> Goal | None:
        row = await self._s.get(GoalRow, goal_id)
        if row is None:
            return None
        row.status = status.value
        row.updated_at = utcnow()
        if status == GoalStatus.DONE:
            row.completed_at = utcnow()
        await self._s.flush()
        return Goal.model_validate(row)

    async def create_tasks(self, tasks: Sequence[Task]) -> list[Task]:
        rows = []
        for t in tasks:
            row = TaskRow(
                id=t.id,
                goal_id=t.goal_id,
                title=t.title,
                status=t.status,
                capability=t.capability,
                tool=t.tool,
                input_data=t.input,
                depends_on=[str(d) for d in t.depends_on],
                attempts=t.attempts,
                max_attempts=t.max_attempts,
                dry_run=t.dry_run,
                created_at=t.created_at,
            )
            rows.append(row)
        self._s.add_all(rows)
        await self._s.flush()
        return list(tasks)

    async def get_task(self, task_id: UUID) -> Task | None:
        row = await self._s.get(TaskRow, task_id)
        if row is None:
            return None
        return self._task_from_row(row)

    async def list_tasks(self, goal_id: UUID) -> list[Task]:
        stmt = (
            select(TaskRow)
            .where(TaskRow.goal_id == goal_id)
            .order_by(TaskRow.created_at)
        )
        result = await self._s.execute(stmt)
        return [self._task_from_row(r) for r in result.scalars()]

    async def update_task(self, task: Task) -> Task:
        row = await self._s.get(TaskRow, task.id)
        if row is None:
            raise ValueError(f"Task {task.id} not found")
        row.status = task.status.value
        row.output_data = task.output
        row.error = task.error
        row.attempts = task.attempts
        row.started_at = task.started_at
        row.finished_at = task.finished_at
        await self._s.flush()
        return task

    async def next_pending_task(self, goal_id: UUID) -> Task | None:
        tasks = await self.list_tasks(goal_id)
        done_ids = {t.id for t in tasks if t.status == TaskStatus.DONE}
        for t in tasks:
            if t.status != TaskStatus.PENDING:
                continue
            if all(dep in done_ids for dep in t.depends_on):
                return t
        return None

    @staticmethod
    def _task_from_row(row: TaskRow) -> Task:
        return Task(
            id=row.id,
            goal_id=row.goal_id,
            title=row.title,
            status=TaskStatus(row.status),
            capability=row.capability,
            tool=row.tool,
            input=row.input_data or {},
            output=row.output_data,
            error=row.error,
            depends_on=[UUID(d) for d in (row.depends_on or [])],
            attempts=row.attempts,
            max_attempts=row.max_attempts,
            dry_run=row.dry_run,
            created_at=row.created_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )


class PgConversationStore:
    """ConversationStore backed by Postgres."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def append(self, message: ChatMessage) -> ChatMessage:
        row = ChatMessageRow(
            id=message.id,
            conversation_id=message.conversation_id,
            role=message.role,
            content=message.content,
            tool_calls=message.tool_calls,
            tool_call_id=message.tool_call_id,
            goal_id=message.goal_id,
            input_tokens=message.input_tokens,
            output_tokens=message.output_tokens,
            model=message.model,
            created_at=message.created_at,
        )
        self._s.add(row)
        await self._s.flush()
        return message

    async def history(
        self, conversation_id: UUID, limit: int = 50
    ) -> list[ChatMessage]:
        stmt = (
            select(ChatMessageRow)
            .where(ChatMessageRow.conversation_id == conversation_id)
            .order_by(ChatMessageRow.created_at)
            .limit(limit)
        )
        result = await self._s.execute(stmt)
        return [ChatMessage.model_validate(r) for r in result.scalars()]

    async def ensure_conversation(
        self, conversation_id: UUID, title: str | None = None
    ) -> UUID:
        existing = await self._s.get(ConversationRow, conversation_id)
        if existing is None:
            final_title = title[:150] if title else "Nova Conversa"
            self._s.add(ConversationRow(id=conversation_id, title=final_title))
            await self._s.flush()
        return conversation_id


class PgCapabilityStore:
    """`CapabilityStore` (packages/registry/ports.py) sobre Postgres.

    Casa por `name`, não por `id`: o nome é a chave em disco, e é ele que o
    manifest e o diretório garantem único. O `id` é derivado do nome
    (`capability_id()`), então os dois concordam — mas quem manda é o nome, para
    o dia em que a derivação mudar.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def upsert(self, record: CapabilityRecord) -> CapabilityRecord:
        row = await self._row(record.name)
        if row is None:
            row = CapabilityRow(id=record.id, name=record.name)
            self._s.add(row)

        row.version = record.version
        row.runtime = record.runtime
        row.status = record.status.value
        row.permissions = record.permissions.model_dump(mode="json")
        row.dependencies = list(record.dependencies)
        row.approved_commit = record.approved_commit
        row.health = record.health.value
        # `last_used_at` só avança: um `discover()` sem estado hidratado não pode
        # apagar o último uso que já estava gravado.
        if record.last_used_at is not None:
            row.last_used_at = record.last_used_at
        await self._s.flush()
        return CapabilityRecord.model_validate(row)

    async def list_all(self) -> list[CapabilityRecord]:
        stmt = select(CapabilityRow).order_by(CapabilityRow.name)
        result = await self._s.execute(stmt)
        return [CapabilityRecord.model_validate(r) for r in result.scalars()]

    async def get_by_name(self, name: str) -> CapabilityRecord | None:
        row = await self._row(name)
        return None if row is None else CapabilityRecord.model_validate(row)

    async def mark_used(self, name: str, when: datetime) -> None:
        row = await self._row(name)
        if row is None:
            return
        row.last_used_at = when
        await self._s.flush()

    async def set_health(self, name: str, health: CapabilityHealth) -> None:
        row = await self._row(name)
        if row is None:
            return
        row.health = health.value
        await self._s.flush()

    async def _row(self, name: str) -> CapabilityRow | None:
        stmt = select(CapabilityRow).where(CapabilityRow.name == name)
        result = await self._s.execute(stmt)
        return result.scalars().first()
