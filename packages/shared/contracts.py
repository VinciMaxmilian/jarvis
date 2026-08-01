"""Fonte única de verdade dos contratos de dados do Jarvis.

As tabelas do Postgres derivam destes modelos; o schema TypeScript do frontend é
gerado do OpenAPI, que por sua vez sai daqui. Nenhum dicionário solto atravessa
fronteira de módulo.

Este módulo roda sob `mypy --strict` e não importa nada do projeto.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utcnow() -> datetime:
    """Timestamp UTC com tzinfo. Usado como default_factory em todo o módulo."""
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
# Goal / Task
# --------------------------------------------------------------------------- #


class GoalStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    BLOCKED = "blocked"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


#: Estados a partir dos quais não há transição (o objetivo/tarefa acabou).
TERMINAL_GOAL_STATUS: frozenset[GoalStatus] = frozenset(
    {GoalStatus.DONE, GoalStatus.FAILED, GoalStatus.CANCELLED}
)
TERMINAL_TASK_STATUS: frozenset[TaskStatus] = frozenset(
    {TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED}
)


class Goal(BaseModel):
    """Unidade de trabalho do sistema. Sobrevive ao fechamento da janela."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    title: str
    description: str = ""
    status: GoalStatus = GoalStatus.DRAFT
    priority: int = Field(default=50, ge=0, le=100)
    parent_goal_id: UUID | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None
    context: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_GOAL_STATUS


class Task(BaseModel):
    """Passo executável de um Goal. Executado por uma capability, nunca pelo Chief AI."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    goal_id: UUID
    title: str
    status: TaskStatus = TaskStatus.PENDING
    capability: str | None = None  # nome da capability que executa
    tool: str | None = None  # nome da tool dentro da capability
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    error: str | None = None
    depends_on: list[UUID] = Field(default_factory=list)
    attempts: int = 0
    max_attempts: int = 3
    dry_run: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_TASK_STATUS

    @property
    def can_retry(self) -> bool:
        return self.status == TaskStatus.FAILED and self.attempts < self.max_attempts


# --------------------------------------------------------------------------- #
# Evento
# --------------------------------------------------------------------------- #


class Event(BaseModel):
    """Fato ocorrido. Na v0 trafega por asyncio.Queue; na v2 por Redis Streams."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    type: str  # "task.completed", "capability.installed", ...
    source: str  # módulo emissor
    payload: dict[str, Any] = Field(default_factory=dict)
    goal_id: UUID | None = None
    task_id: UUID | None = None
    trace_id: str
    created_at: datetime = Field(default_factory=utcnow)


class EventType:
    """Nomes canônicos de evento. String literal solta em `Event.type` é bug."""

    GOAL_CREATED = "goal.created"
    GOAL_COMPLETED = "goal.completed"
    GOAL_BLOCKED = "goal.blocked"
    TASK_CREATED = "task.created"
    TASK_PLANNED = "task.planned"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TOOL_CALLED = "tool.called"
    TOOL_FINISHED = "tool.finished"
    MEMORY_UPDATED = "memory.updated"
    CAPABILITY_GAP_DETECTED = "capability.gap_detected"
    CAPABILITY_INSTALLED = "capability.installed"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_GRANTED = "approval.granted"
    BACKUP_COMPLETED = "backup.completed"


# --------------------------------------------------------------------------- #
# Conversa (persistida em Postgres; distinta da Message da camada de LLM)
# --------------------------------------------------------------------------- #


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatMessage(BaseModel):
    """Turno de conversa persistido. A `Message` de `packages.llm` é o formato de wire."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID
    role: MessageRole
    content: str = ""
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_call_id: str | None = None
    goal_id: UUID | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    model: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Conversation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    title: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- #
# Tools e capabilities
# --------------------------------------------------------------------------- #


class ToolSpec(BaseModel):
    """Descrição de uma tool. `input_schema` é JSON Schema, compatível com MCP."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    idempotent: bool = False
    requires_approval: bool = False


class CapabilityPermissions(BaseModel):
    """Escopo declarado. Lido em runtime pelo wrapper (v1), não é documentação."""

    model_config = ConfigDict(from_attributes=True)

    network: list[str] = Field(default_factory=list)  # hosts ou IPs; [] = sem rede
    filesystem: list[str] = Field(default_factory=list)  # paths absolutos permitidos
    process: bool = False  # pode iniciar subprocessos externos


class CapabilityStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    ACTIVE = "active"
    DISABLED = "disabled"


#: Nomes antigos de `CapabilityManifest.runtime` e o nome canônico de hoje.
#: O campo era `transport: Literal["mcp_stdio", "python"]` — dois valores fechados
#: dentro do contrato, o que fazia somar um runtime (Docker, CLI, HTTP) editar
#: `contracts.py` e todo consumidor junto (`plan-execution.md` §2). Virou
#: `runtime: str`, resolvido pelo kernel; este mapa existe só para que manifest
#: escrito antes da v1.2 continue carregando com o nome novo, em vez de virar um
#: runtime desconhecido em silêncio. Normalizar aqui, e não no kernel, é o que
#: garante que a tabela `capabilities` grave um nome só.
RUNTIME_ALIASES: dict[str, str] = {"mcp_stdio": "mcp", "python_inproc": "python"}

#: Default do campo. `mcp` é o mesmo valor que `mcp_stdio` significava antes do
#: rename: manifest sem runtime declarado não muda de comportamento na migração.
RUNTIME_PADRAO = "mcp"

#: Nome antigo, no singular, da chave de intenções no `manifest.yaml`. O campo
#: nasceu fora do contrato: o registry o lia por um modelo paralelo e o SDK por
#: outro, duas leituras do mesmo YAML fadadas a divergir. Agora ele é contrato, e
#: esta constante existe só para que manifest já escrito em disco continue
#: carregando — inclusive `capabilities/exemplo_nas/manifest.yaml`.
CHAVE_TRIGGER_LEGADA = "trigger_intent"


class CapabilityManifest(BaseModel):
    """Serializa exatamente o `manifest.yaml` no disco da capability."""

    model_config = ConfigDict(from_attributes=True)

    name: str  # slug único, ex.: "nas_sync"
    version: str  # semver
    description: str
    status: CapabilityStatus = CapabilityStatus.PENDING_APPROVAL
    approved_commit: str | None = None  # SHA do commit aprovado no Gate 2
    #: Como alcançar a implementação. O significado depende do `runtime`:
    #: `python` e `mcp` querem `modulo:atributo`; `http` quer a URL base.
    entrypoint: str
    #: Quem executa: `python`, `mcp`, `http`. `str` e não `Literal` de propósito —
    #: o conjunto de adapters é do kernel, e somar um não pode tocar o contrato.
    runtime: str = RUNTIME_PADRAO
    permissions: CapabilityPermissions = Field(default_factory=CapabilityPermissions)
    tools: list[ToolSpec] = Field(default_factory=list)
    #: Frases que devem acionar esta capability em `resolve()` (`plan.md` §6). É o
    #: campo mais forte do casamento de intenção, e é contrato — não anotação
    #: solta do YAML — porque quem o lê são dois módulos independentes (registry e
    #: Capability SDK) e campo lido por fora do schema diverge entre eles.
    trigger_intents: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)  # pacotes pip
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="before")
    @classmethod
    def _aceitar_trigger_intent_singular(cls, dados: Any) -> Any:
        """Mapeia a chave legada `trigger_intent` para o campo do contrato.

        Só quando o nome canônico está **ausente**. Manifest gerado traz os dois
        (o contrato serializa `trigger_intents`, o gerador ainda escreve o
        singular), e nesse caso quem manda é o campo do contrato — precedência
        pelo nome novo é o que faz a migração acabar em vez de empatar.
        """
        if (
            isinstance(dados, dict)
            and "trigger_intents" not in dados
            and CHAVE_TRIGGER_LEGADA in dados
        ):
            return {**dados, "trigger_intents": dados[CHAVE_TRIGGER_LEGADA]}
        return dados

    @field_validator("trigger_intents", mode="before")
    @classmethod
    def _normalizar_intents(cls, valor: object) -> object:
        """Aceita string solta e descarta entrada em branco.

        Uma intenção só é o caso comum, e obrigar `- frase` para ela seria erro
        de YAML esperando acontecer. Entrada vazia é descartada porque frase em
        branco casaria com qualquer intenção no índice do registry.
        """
        if isinstance(valor, str):
            valor = [valor]
        if isinstance(valor, (list, tuple)):
            return [str(item).strip() for item in valor if str(item).strip()]
        return valor

    @field_validator("runtime", mode="before")
    @classmethod
    def _canonizar_runtime(cls, valor: object) -> object:
        """Aceita o nome antigo e devolve o canônico. Vazio volta ao default."""
        if not isinstance(valor, str):
            return valor
        limpo = valor.strip().lower()
        if not limpo:
            return RUNTIME_PADRAO
        return RUNTIME_ALIASES.get(limpo, limpo)

    @property
    def is_loadable(self) -> bool:
        """O registry só carrega capability `active` (regra da seção 6 de plan.md)."""
        return self.status == CapabilityStatus.ACTIVE


class FileAccessRule(BaseModel):
    allowed_dirs: list[str] = Field(default_factory=list)
    allowed_extensions: list[str] = Field(default_factory=list)


#: Providers de LLM aceitos. A autoridade de *runtime* é o mapa de fábricas em
#: `apps/api/deps.py`; este Literal existe porque pydantic precisa do conjunto
#: estático para validar a entrada da API. Somar provider mexe nos dois — e o
#: `deps.py` derruba a app no import se eles divergirem.
ProviderId = Literal[
    "lmstudio", "gemini", "anthropic", "openai", "local", "ollama"
]


class SystemSettings(BaseModel):
    """Configurações dinâmicas de sistema que sobrescrevem os defaults do .env.

    `model` vazio significa "use o default do provider escolhido" — é o que evita
    manter modelo de um provider ao trocar para outro.
    """

    # Mesmo default de `Settings.chief_provider`: divergir faria a linha
    # persistida em banco discordar do boot sem que ninguém tivesse escolhido.
    provider: ProviderId = "lmstudio"
    model: str = ""
    temperature: float = 0.7
    system_prompt: str = ""


class Capability(BaseModel):
    """Entrada do registry: manifest + estado de runtime."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    manifest: CapabilityManifest
    installed_at: datetime = Field(default_factory=utcnow)
    last_used_at: datetime | None = None
    dry_run_completed: bool = False


__all__ = [
    "CHAVE_TRIGGER_LEGADA",
    "RUNTIME_ALIASES",
    "RUNTIME_PADRAO",
    "TERMINAL_GOAL_STATUS",
    "TERMINAL_TASK_STATUS",
    "Capability",
    "CapabilityManifest",
    "CapabilityPermissions",
    "CapabilityStatus",
    "ChatMessage",
    "Conversation",
    "Event",
    "EventType",
    "Goal",
    "GoalStatus",
    "MessageRole",
    "Task",
    "TaskStatus",
    "ToolSpec",
    "utcnow",
]
