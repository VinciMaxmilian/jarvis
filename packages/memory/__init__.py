"""Os cinco níveis de memória de `plan.md` §10.

| Nível | Módulo | Tempo de vida |
|---|---|---|
| `short` | `short_term.py` | sessão (Redis) |
| `working` | `working.py` | duração da task; persistido no checkpoint |
| `long` | `long_term.py` | permanente, editável |
| `knowledge` | `knowledge.py` | permanente até a fonte sumir; RAG incremental |
| `experience` | `experience.py` | permanente, cresce por acúmulo |

`MemorySystem` (em `system.py`) é a fachada: é dela que o `GoalManager` depende,
e é `None` por default — sem memória configurada, o laço de execução se comporta
exatamente como antes desta fatia.
"""

from packages.memory.experience import ExperienceMemory, render_experience_context
from packages.memory.factory import (
    build_memory_system,
    build_vector_store,
    vector_backend,
)
from packages.memory.knowledge import KnowledgeBase, chunk_text, render_knowledge_context
from packages.memory.long_term import LongTermMemory
from packages.memory.models import (
    Attempt,
    AttemptOutcome,
    ExperienceKind,
    ExperienceRecord,
    IndexedDocument,
    IngestOutcome,
    IngestResult,
    KnowledgeDocument,
    MemoryLevel,
    MemoryUpdate,
    PartialResult,
    RetrievedChunk,
    WorkingMemoryState,
)
from packages.memory.ports import ExperienceStore, KnowledgeIndex, WorkingMemoryStore
from packages.memory.short_term import ShortTermMemory
from packages.memory.stores import (
    InMemoryExperienceStore,
    InMemoryKnowledgeIndex,
    InMemoryWorkingMemoryStore,
    JsonFileExperienceStore,
    JsonFileKnowledgeIndex,
    JsonFileWorkingMemoryStore,
)
from packages.memory.system import MemorySystem
from packages.memory.vector_store import InMemoryVectorStore, LanceDBVectorStore
from packages.memory.working import WorkingMemory, render_working_context

__all__ = [
    "Attempt",
    "AttemptOutcome",
    "ExperienceKind",
    "ExperienceMemory",
    "ExperienceRecord",
    "ExperienceStore",
    "InMemoryExperienceStore",
    "InMemoryKnowledgeIndex",
    "InMemoryVectorStore",
    "InMemoryWorkingMemoryStore",
    "IndexedDocument",
    "IngestOutcome",
    "IngestResult",
    "JsonFileExperienceStore",
    "JsonFileKnowledgeIndex",
    "JsonFileWorkingMemoryStore",
    "KnowledgeBase",
    "KnowledgeDocument",
    "KnowledgeIndex",
    "LanceDBVectorStore",
    "LongTermMemory",
    "MemoryLevel",
    "MemorySystem",
    "MemoryUpdate",
    "PartialResult",
    "RetrievedChunk",
    "ShortTermMemory",
    "WorkingMemory",
    "WorkingMemoryState",
    "WorkingMemoryStore",
    "build_memory_system",
    "build_vector_store",
    "chunk_text",
    "render_experience_context",
    "render_knowledge_context",
    "render_working_context",
    "vector_backend",
]
