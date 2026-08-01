"""Nível `long` — fatos duráveis sobre o dono e o ambiente.

`plan.md` §10: "máquinas, caminhos, contas, preferências fixas. Permanente,
editável."

O que este arquivo era até a v1.3: dois `TODO` e um `import lancedb` no corpo do
`connect()`, com `store_fact()` e `search()` que registravam um log e devolviam
nada. Pior do que não existir — a chamada tinha sucesso aparente. E o import
direto era, nesta máquina, uma bomba: `import lancedb` mata o processo com
SIGILL num i5-3470 (ver o cabeçalho de `vector_store.py`).

Agora é a mesma porta `VectorStore` do nível `knowledge`, em outro namespace, com
o embedding vindo de `LLMProvider.embed()` injetado. Fato é curto por definição —
não passa por chunking; um fato é um registro.

**Mudança de assinatura, de propósito:** os métodos viraram `async`, porque
`embed()` é `async`. Nenhum chamador existia no repositório (o `orchestrator`
importava um módulo que nem rodava — `tools.md` D1), então a quebra é de papel.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import structlog

from packages.llm.base import LLMProvider
from packages.memory.models import MemoryLevel, MemoryUpdate, RetrievedChunk
from packages.shared.contracts import Event, EventType, utcnow
from packages.shared.ports import EventBus, VectorRecord, VectorStore

logger = structlog.get_logger(__name__)

DEFAULT_NAMESPACE = "long_term"


class LongTermMemory:
    """Fatos duráveis, indexados por vetor e recuperáveis por busca semântica."""

    def __init__(
        self,
        provider: LLMProvider,
        store: VectorStore,
        *,
        namespace: str = DEFAULT_NAMESPACE,
        event_bus: EventBus | None = None,
    ) -> None:
        self._provider = provider
        self._store = store
        self._namespace = namespace
        self._bus = event_bus

    async def store_fact(
        self,
        fact: str,
        *,
        fact_id: str | None = None,
        tags: Sequence[str] = (),
        source: str = "dono",
    ) -> str:
        """Grava (ou substitui) um fato. Devolve o id, que é o que permite editar.

        `fact_id` explícito é o que torna o nível **editável**, como o plano
        exige: sem id estável, corrigir "o NAS é 192.168.11.20" significaria
        acrescentar a correção ao lado do erro e deixar a busca escolher.
        """
        texto = fact.strip()
        if not texto:
            raise ValueError("fato vazio não é fato")

        vetores = await self._provider.embed([texto])
        rid = fact_id or f"fact-{uuid4().hex[:12]}"
        await self._store.upsert(
            [
                VectorRecord(
                    id=rid,
                    namespace=self._namespace,
                    text=texto,
                    embedding=list(vetores[0]),
                    metadata={
                        "source": source,
                        "tags": ",".join(tags),
                        "updated_at": utcnow().isoformat(),
                    },
                )
            ]
        )
        logger.info("memory.long_term.gravado", fact_id=rid)
        await self._publicar(rid, texto)
        return rid

    async def search(self, query: str, *, limit: int = 5) -> list[RetrievedChunk]:
        """Busca semântica sobre os fatos."""
        if not query.strip():
            return []
        vetores = await self._provider.embed([query])
        achados = await self._store.search(
            vetores[0], namespace=self._namespace, limit=limit
        )
        return [
            RetrievedChunk(
                doc_id=m.record.id,
                source=m.record.metadata.get("source", ""),
                text=m.record.text,
                score=m.score,
            )
            for m in achados
        ]

    async def forget(self, fact_id: str) -> bool:
        """Remove um fato. Editável inclui apagável."""
        return await self._store.delete([fact_id]) > 0

    async def _publicar(self, fact_id: str, texto: str) -> None:
        if self._bus is None:
            return
        update = MemoryUpdate(
            level=MemoryLevel.LONG, subject=fact_id, detail=texto[:200]
        )
        await self._bus.publish(
            Event(
                type=EventType.MEMORY_UPDATED,
                source="packages.memory.long_term",
                payload=update.model_dump(mode="json"),
                trace_id=uuid4().hex,
            )
        )


__all__ = ["LongTermMemory"]
