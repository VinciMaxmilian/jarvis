"""Contratos dos cinco níveis de memória (`plan.md` §10).

Modelos Pydantic, nunca dicionário solto: o invariante de `plan-execution.md` §7
vale aqui igual ao resto. Ficam neste módulo, e não em `packages/shared/contracts.py`,
porque só a memória os consome — se um segundo pacote precisar deles, sobem para
o contrato compartilhado.

Roda sob `mypy` com `check_untyped_defs`.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.shared.contracts import utcnow

# --------------------------------------------------------------------------- #
# Nível `working` — estado vivo da task
# --------------------------------------------------------------------------- #


class AttemptOutcome(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Attempt(BaseModel):
    """Uma passada da task pelo executor. `STARTED` sem par é a que o kill pegou."""

    model_config = ConfigDict(from_attributes=True)

    number: int  # espelha `Task.attempts` no momento do registro
    outcome: AttemptOutcome = AttemptOutcome.STARTED
    capability: str | None = None
    tool: str | None = None
    error: str | None = None
    at: datetime = Field(default_factory=utcnow)


class PartialResult(BaseModel):
    """Resultado parcial: o que a task já produziu antes de ser interrompida."""

    model_config = ConfigDict(from_attributes=True)

    label: str
    content: str
    at: datetime = Field(default_factory=utcnow)


class WorkingMemoryState(BaseModel):
    """Estado da task em execução: plano, parciais e o que já foi tentado.

    Vida útil = a da task (`plan.md` §10). Persistido no **checkpoint** — o mesmo
    ponto em que `GoalManager.execute_next_task` chama `update_task` —, porque
    estado que só existe em RAM some junto com o processo, e é exatamente o kill
    no meio da task que este nível existe para sobreviver.
    """

    model_config = ConfigDict(from_attributes=True)

    task_id: UUID
    goal_id: UUID
    title: str = ""
    plan: list[str] = Field(default_factory=list)
    attempts: list[Attempt] = Field(default_factory=list)
    partials: list[PartialResult] = Field(default_factory=list)
    revision: int = 0  # incrementa a cada checkpoint; detecta escrita perdida
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def interrupted_attempt(self) -> Attempt | None:
        """A tentativa que ficou `STARTED` sem desfecho — a que o kill pegou."""
        for attempt in reversed(self.attempts):
            if attempt.outcome is AttemptOutcome.STARTED:
                return attempt
        return None

    @property
    def failures(self) -> list[Attempt]:
        return [a for a in self.attempts if a.outcome is AttemptOutcome.FAILED]


# --------------------------------------------------------------------------- #
# Nível `knowledge` — documentos indexados (RAG)
# --------------------------------------------------------------------------- #


def content_hash(text: str) -> str:
    """SHA-256 do texto normalizado. É o que faz a reindexação ser incremental.

    Normaliza espaço em branco antes de somar: reformatar um arquivo sem mudar o
    conteúdo não pode custar uma rodada inteira de embeddings.
    """
    normalizado = " ".join(text.split())
    return hashlib.sha256(normalizado.encode("utf-8")).hexdigest()


class KnowledgeDocument(BaseModel):
    """Documento a ingerir. `doc_id` default é a própria fonte — legível no log."""

    model_config = ConfigDict(from_attributes=True)

    source: str  # caminho, URL ou identificador da origem
    text: str
    doc_id: str = ""
    title: str = ""
    tags: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _default_doc_id(self) -> KnowledgeDocument:
        if not self.doc_id:
            self.doc_id = self.source
        return self

    @property
    def content_hash(self) -> str:
        return content_hash(self.text)


class IngestOutcome(StrEnum):
    INDEXED = "indexed"  # documento novo
    UPDATED = "updated"  # o conteúdo mudou; os chunks velhos saíram
    UNCHANGED = "unchanged"  # mesmo hash: nenhum embedding foi calculado


class IngestResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    doc_id: str
    outcome: IngestOutcome
    chunks_indexed: int = 0
    chunks_removed: int = 0

    @property
    def touched(self) -> bool:
        return self.outcome is not IngestOutcome.UNCHANGED


class RetrievedChunk(BaseModel):
    """Trecho devolvido pela busca semântica, com a proveniência junto.

    Sem `source` e `chunk_index` o RAG vira citação sem referência, e uma resposta
    errada fica impossível de rastrear até o documento que a causou.
    """

    model_config = ConfigDict(from_attributes=True)

    doc_id: str
    source: str
    title: str = ""
    chunk_index: int = 0
    text: str
    score: float


class IndexedDocument(BaseModel):
    """Linha do índice incremental: o que já está indexado e sob quais ids."""

    model_config = ConfigDict(from_attributes=True)

    doc_id: str
    source: str
    content_hash: str
    chunk_ids: list[str] = Field(default_factory=list)
    indexed_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- #
# Nível `experience` — padrões extraídos de execução
# --------------------------------------------------------------------------- #


class ExperienceKind(StrEnum):
    CAPABILITY_FAILURE = "capability_failure"
    CAPABILITY_SUCCESS = "capability_success"
    OWNER_PREFERENCE = "owner_preference"


_HEX_LONGO = re.compile(r"\b[0-9a-f]{8,}\b")
_DIGITOS = re.compile(r"\d+")
_ESPACO = re.compile(r"\s+")


def error_signature(error: str, *, max_len: int = 120) -> str:
    """Reduz uma mensagem de erro à sua forma repetível.

    Sem isto, "timeout após 30s" e "timeout após 45s" seriam dois registros de
    uma ocorrência cada, e a falha REPETIDA — que é a única que vira padrão —
    nunca alcançaria o limiar. Números e hashes viram marcador; o resto do texto
    é o que identifica a classe do erro.
    """
    texto = _HEX_LONGO.sub("<hex>", error.strip().lower())
    texto = _DIGITOS.sub("#", texto)
    return _ESPACO.sub(" ", texto).strip()[:max_len]


def experience_id(kind: ExperienceKind, subject: str, signature: str) -> str:
    """Id determinístico: a mesma falha da mesma capability cai no mesmo registro."""
    digest = hashlib.sha256(f"{kind}:{subject}:{signature}".encode()).hexdigest()
    return f"{kind.value}:{subject}:{digest[:12]}"


class ExperienceRecord(BaseModel):
    """Padrão observado. É o nível que separa o sistema de um chat com RAG.

    `occurrences` é o que dá peso: uma falha é acidente, a terceira é padrão. O
    limiar de promoção mora em `ExperienceMemory`, não aqui — o registro guarda o
    fato, quem decide o que é padrão é quem lê.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: ExperienceKind
    subject: str  # capability, tool ou área do conhecimento do dono
    signature: str = ""
    lesson: str
    occurrences: int = 1
    evidence: list[str] = Field(default_factory=list)  # mensagens cruas, limitadas
    goal_ids: list[str] = Field(default_factory=list)
    first_seen_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- #
# Evento de memória (payload de `EventType.MEMORY_UPDATED`)
# --------------------------------------------------------------------------- #


class MemoryLevel(StrEnum):
    SHORT = "short"
    WORKING = "working"
    LONG = "long"
    KNOWLEDGE = "knowledge"
    EXPERIENCE = "experience"


class MemoryUpdate(BaseModel):
    """Payload tipado de `memory.updated`. Vira dict só no `Event.payload`."""

    model_config = ConfigDict(from_attributes=True)

    level: MemoryLevel
    subject: str  # doc_id, task_id, id do registro de experiência
    detail: str = ""
    count: int = 1


__all__ = [
    "Attempt",
    "AttemptOutcome",
    "ExperienceKind",
    "ExperienceRecord",
    "IndexedDocument",
    "IngestOutcome",
    "IngestResult",
    "KnowledgeDocument",
    "MemoryLevel",
    "MemoryUpdate",
    "PartialResult",
    "RetrievedChunk",
    "WorkingMemoryState",
    "content_hash",
    "error_signature",
    "experience_id",
]
