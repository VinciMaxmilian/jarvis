"""SQLAlchemy ORM tables derivados dos contratos Pydantic.

Regra: contracts.py é a verdade; estas tabelas espelham. Toda alteração de schema
passa por migration Alembic — sem create_all().
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from packages.registry.records import CapabilityHealth
from packages.shared.contracts import (
    CapabilityStatus,
    GoalStatus,
    MessageRole,
    TaskStatus,
)


class Base(DeclarativeBase):
    """Base declarativa. Alembic importa daqui."""
    pass


class GoalRow(Base):
    __tablename__ = "goals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(
        SAEnum(
            GoalStatus,
            name="goal_status",
            values_callable=lambda obj: [e.value for e in obj],
            create_constraint=True,
        ),
        default=GoalStatus.DRAFT,
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(Integer, default=50)
    parent_goal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("goals.id"), nullable=True
    )
    context: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tasks: Mapped[list[TaskRow]] = relationship(
        back_populates="goal", cascade="all, delete-orphan"
    )


class TaskRow(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    goal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("goals.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        SAEnum(
            TaskStatus,
            name="task_status",
            values_callable=lambda obj: [e.value for e in obj],
            create_constraint=True,
        ),
        default=TaskStatus.PENDING,
        nullable=False,
    )
    capability: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tool: Mapped[str | None] = mapped_column(String(200), nullable=True)
    input_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    output_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    depends_on: Mapped[list] = mapped_column(JSONB, default=list)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    goal: Mapped[GoalRow] = relationship(back_populates="tasks")


class SystemSettingsRow(Base):
    __tablename__ = "system_settings"

    # Singleton row, we'll just use id=1
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    provider: Mapped[str] = mapped_column(String(50), default="anthropic")
    model: Mapped[str] = mapped_column(String(100), default="claude-sonnet-4")
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class CapabilityRow(Base):
    """Catálogo de capabilities (v1.1).

    Espelha `packages.registry.records.CapabilityRecord`. O manifest continua em
    disco e versionado com o código; o que esta tabela guarda é o estado que o
    disco não tem — `health` e `last_used_at` — e que antes morria a cada
    restart, porque o registry era um dicionário reconstruído por varredura.

    `name` é a chave natural (é o nome do diretório da capability); `id` é
    derivado dele por uuid5 em `capability_id()`, então o mesmo diretório dá
    sempre a mesma linha.
    """

    __tablename__ = "capabilities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    version: Mapped[str] = mapped_column(String(50), nullable=False, default="0.0.0")
    # `transport` do manifest de hoje; a v1.2 renomeia o campo do contrato para
    # `runtime` e a coluna já nasce com o nome final.
    runtime: Mapped[str] = mapped_column(String(50), nullable=False, default="mcp_stdio")
    status: Mapped[str] = mapped_column(
        SAEnum(
            CapabilityStatus,
            name="capability_status",
            values_callable=lambda obj: [e.value for e in obj],
            create_constraint=True,
        ),
        default=CapabilityStatus.PENDING_APPROVAL,
        nullable=False,
    )
    permissions: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    dependencies: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    approved_commit: Mapped[str | None] = mapped_column(String(128), nullable=True)
    health: Mapped[str] = mapped_column(
        SAEnum(
            CapabilityHealth,
            name="capability_health",
            values_callable=lambda obj: [e.value for e in obj],
            create_constraint=True,
        ),
        default=CapabilityHealth.UNKNOWN,
        nullable=False,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ConversationRow(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    messages: Mapped[list[ChatMessageRow]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class ChatMessageRow(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        SAEnum(
            MessageRole,
            name="message_role",
            values_callable=lambda obj: [e.value for e in obj],
            create_constraint=True,
        ),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, default="")
    tool_calls: Mapped[list] = mapped_column(JSONB, default=list)
    tool_call_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    goal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    conversation: Mapped[ConversationRow] = relationship(back_populates="messages")
