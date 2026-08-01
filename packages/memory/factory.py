"""Montagem dos níveis a partir de configuração.

O backend de vetores é escolhido por **valor de configuração**, não por import:
`memory` (default, roda em qualquer CPU) ou `lancedb` (a escolha da v1, ligada na
máquina que tiver AVX2 — ver o cabeçalho de `vector_store.py`).

**Duas variáveis novas, ainda fora de `Settings`.** `packages/shared/settings.py`
está sendo editado por outra fatia agora, e o contrato daquele arquivo diz que
toda variável declarada lá entra no `.env.example` no mesmo commit. Então elas
moram aqui, com default seguro, e a promoção para `Settings` fica registrada como
pendência da fatia:

| Variável | Default | Papel |
|---|---|---|
| `MEMORY_VECTOR_BACKEND` | `memory` | `memory` ou `lancedb` |
| `MEMORY_DATA_DIR` | `./data/memory` | working memory, índice e experience em JSON |

`LANCEDB_PATH` já existe em `Settings` e é o caminho usado quando o backend é
`lancedb` — nada novo é inventado para isso.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import structlog

from packages.llm.base import LLMProvider
from packages.memory.experience import ExperienceMemory
from packages.memory.knowledge import KnowledgeBase
from packages.memory.long_term import LongTermMemory
from packages.memory.stores import (
    JsonFileExperienceStore,
    JsonFileKnowledgeIndex,
    JsonFileWorkingMemoryStore,
)
from packages.memory.system import MemorySystem
from packages.memory.vector_store import InMemoryVectorStore, LanceDBVectorStore
from packages.memory.working import WorkingMemory
from packages.shared.ports import EventBus, VectorStore

logger = structlog.get_logger(__name__)

VectorBackend = Literal["memory", "lancedb"]

#: Default `memory`: um backend que não sobe em CPU sem AVX2 não pode ser o
#: caminho padrão de um sistema que precisa subir.
DEFAULT_VECTOR_BACKEND: VectorBackend = "memory"
VECTOR_BACKEND_ENV = "MEMORY_VECTOR_BACKEND"
DATA_DIR_ENV = "MEMORY_DATA_DIR"
DEFAULT_DATA_DIR = "./data/memory"

#: Dimensão do vetor da tabela LanceDB. O schema do Arrow é fixo: trocar de modelo
#: de embedding exige reindexar, não gravar por cima.
DEFAULT_EMBEDDING_DIM = 1024


def vector_backend(env: Mapping[str, str] | None = None) -> VectorBackend:
    """Lê o backend da configuração. Valor desconhecido falha nomeando os válidos."""
    bruto = (env or os.environ).get(VECTOR_BACKEND_ENV, DEFAULT_VECTOR_BACKEND).strip()
    if bruto not in ("memory", "lancedb"):
        raise ValueError(
            f"{VECTOR_BACKEND_ENV}={bruto!r} desconhecido. Válidos: memory, lancedb."
        )
    return "lancedb" if bruto == "lancedb" else "memory"


def build_vector_store(
    backend: VectorBackend = DEFAULT_VECTOR_BACKEND,
    *,
    lancedb_path: str = "./data/lancedb",
    table: str = "memory",
    dim: int = DEFAULT_EMBEDDING_DIM,
) -> VectorStore:
    """Constrói o adapter escolhido. Nada de `lancedb` é importado no caminho `memory`."""
    if backend == "lancedb":
        logger.info("memory.vector_store.lancedb", path=lancedb_path)
        return LanceDBVectorStore(lancedb_path, table=table, dim=dim)

    persist_path = Path(lancedb_path).parent / "vector" / f"{table}_index.json"
    logger.info("memory.vector_store.in_memory", persist_path=str(persist_path))
    return InMemoryVectorStore(persist_path=persist_path)


def build_memory_system(
    provider: LLMProvider,
    *,
    data_dir: Path | str | None = None,
    backend: VectorBackend | None = None,
    lancedb_path: str = "./data/lancedb",
    embedding_dim: int = DEFAULT_EMBEDDING_DIM,
    event_bus: EventBus | None = None,
    env: Mapping[str, str] | None = None,
) -> MemorySystem:
    """Os cinco níveis prontos para injeção, com persistência em disco.

    `short_term` fica de fora: ele já existe, é Redis, e quem o constrói precisa
    da URL do Redis — que é responsabilidade de quem monta a app, não daqui.
    """
    ambiente = env or os.environ
    raiz = Path(data_dir or ambiente.get(DATA_DIR_ENV, DEFAULT_DATA_DIR))
    escolhido = backend or vector_backend(ambiente)

    store = build_vector_store(
        escolhido, lancedb_path=lancedb_path, dim=embedding_dim
    )

    return MemorySystem(
        working=WorkingMemory(
            JsonFileWorkingMemoryStore(raiz / "working"), event_bus=event_bus
        ),
        knowledge=KnowledgeBase(
            provider,
            store,
            JsonFileKnowledgeIndex(raiz / "knowledge_index.json"),
            event_bus=event_bus,
        ),
        experience=ExperienceMemory(
            JsonFileExperienceStore(raiz / "experience.json"), event_bus=event_bus
        ),
        long_term=LongTermMemory(provider, store, event_bus=event_bus),
    )


__all__ = [
    "DATA_DIR_ENV",
    "DEFAULT_DATA_DIR",
    "DEFAULT_EMBEDDING_DIM",
    "DEFAULT_VECTOR_BACKEND",
    "VECTOR_BACKEND_ENV",
    "VectorBackend",
    "build_memory_system",
    "build_vector_store",
    "vector_backend",
]
