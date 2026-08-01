"""Nível `knowledge` — documentos indexados para busca semântica (RAG).

`plan.md` §10: "documentos ingeridos e indexados para busca semântica;
permanente até remoção da fonte".

Duas decisões que definem o módulo:

**O embedding vem da porta.** `LLMProvider.embed()`, injetado — nunca um SDK
importado direto. É a mesma regra que vale para chat (`packages/llm/base.py`) e
é o que permite trocar o modelo de embedding sem tocar aqui. Também é o que faz
a suíte rodar sem rede: o dublê devolve vetor determinístico.

**A reindexação é incremental.** Reingerir um documento cujo conteúdo não mudou
custa **zero** chamada de embedding: o hash do conteúdo é comparado contra o
índice e o trabalho é pulado. Conteúdo alterado remove os chunks velhos antes de
gravar os novos — sem isso a base acumularia duas versões do mesmo documento e a
busca devolveria a antiga com a mesma confiança da nova. É o que o job
`reindex_knowledge` da v1.4 vai chamar.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import structlog

from packages.llm.base import LLMProvider
from packages.memory.models import (
    IndexedDocument,
    IngestOutcome,
    IngestResult,
    KnowledgeDocument,
    MemoryLevel,
    MemoryUpdate,
    RetrievedChunk,
)
from packages.memory.ports import KnowledgeIndex
from packages.shared.contracts import Event, EventType, utcnow
from packages.shared.ports import EventBus, VectorRecord, VectorStore

logger = structlog.get_logger(__name__)

DEFAULT_NAMESPACE = "knowledge"
DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 120


def chunk_text(
    text: str,
    *,
    size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """Divide o texto em pedaços de até `size` caracteres, com sobreposição.

    A sobreposição existe porque a fronteira do corte é arbitrária: uma frase
    partida ao meio some das duas metades se nenhuma delas a contiver inteira.

    Determinístico por construção — o mesmo texto sempre gera os mesmos chunks,
    com os mesmos ids, e é isso que faz `upsert` substituir em vez de duplicar.
    """
    if size <= 0:
        raise ValueError("size precisa ser positivo")
    if not 0 <= overlap < size:
        raise ValueError("overlap precisa estar em [0, size)")

    limpo = "\n".join(linha.rstrip() for linha in text.strip().splitlines()).strip()
    if not limpo:
        return []
    if len(limpo) <= size:
        return [limpo]

    pedacos: list[str] = []
    inicio = 0
    minimo = max(1, size - overlap)
    while inicio < len(limpo):
        fim = min(inicio + size, len(limpo))
        if fim < len(limpo):
            # Recua até o último espaço para não partir palavra ao meio; nunca
            # antes de `minimo`, senão um texto sem espaços entraria em laço.
            corte = limpo.rfind(" ", inicio + minimo, fim)
            if corte != -1:
                fim = corte
        pedaco = limpo[inicio:fim].strip()
        if pedaco:
            pedacos.append(pedaco)
        if fim >= len(limpo):
            break
        inicio = max(fim - overlap, inicio + 1)
    return pedacos


def chunk_id(doc_id: str, index: int) -> str:
    """Id estável do chunk. Reingerir o mesmo documento reescreve as mesmas linhas."""
    return f"{doc_id}#{index}"


class KnowledgeBase:
    """RAG incremental sobre a porta `VectorStore`."""

    def __init__(
        self,
        provider: LLMProvider,
        store: VectorStore,
        index: KnowledgeIndex,
        *,
        namespace: str = DEFAULT_NAMESPACE,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
        event_bus: EventBus | None = None,
    ) -> None:
        self._provider = provider
        self._store = store
        self._index = index
        self._namespace = namespace
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._bus = event_bus

    # -- ingestão --------------------------------------------------------- #

    async def ingest(self, document: KnowledgeDocument) -> IngestResult:
        """Indexa o documento. Conteúdo inalterado sai sem calcular embedding."""
        anterior = await self._index.get(document.doc_id)
        hash_novo = document.content_hash

        if anterior is not None and anterior.content_hash == hash_novo:
            logger.debug("memory.knowledge.inalterado", doc_id=document.doc_id)
            return IngestResult(doc_id=document.doc_id, outcome=IngestOutcome.UNCHANGED)

        pedacos = chunk_text(
            document.text, size=self._chunk_size, overlap=self._chunk_overlap
        )
        if not pedacos:
            raise ValueError(
                f"documento {document.doc_id!r} não tem texto para indexar — "
                "ingerir vazio deixaria o índice mentindo sobre a cobertura"
            )

        embeddings = await self._provider.embed(pedacos)
        if len(embeddings) != len(pedacos):
            raise ValueError(
                f"provider devolveu {len(embeddings)} embeddings para "
                f"{len(pedacos)} chunks"
            )

        registros = [
            VectorRecord(
                id=chunk_id(document.doc_id, i),
                namespace=self._namespace,
                text=pedaco,
                embedding=list(vetor),
                metadata={
                    "doc_id": document.doc_id,
                    "source": document.source,
                    "title": document.title,
                    "chunk_index": str(i),
                    "content_hash": hash_novo,
                    "tags": ",".join(document.tags),
                },
            )
            for i, (pedaco, vetor) in enumerate(zip(pedacos, embeddings, strict=True))
        ]

        # Chunks velhos que a nova versão não reaproveita: um texto encurtado
        # deixaria os últimos chunks órfãos, e órfão é resultado de busca fantasma.
        novos_ids = {r.id for r in registros}
        antigos = anterior.chunk_ids if anterior else []
        obsoletos = [i for i in antigos if i not in novos_ids]
        removidos = await self._store.delete(obsoletos) if obsoletos else 0

        await self._store.upsert(registros)
        await self._index.put(
            IndexedDocument(
                doc_id=document.doc_id,
                source=document.source,
                content_hash=hash_novo,
                chunk_ids=sorted(novos_ids),
                indexed_at=utcnow(),
            )
        )

        resultado = IngestResult(
            doc_id=document.doc_id,
            outcome=(
                IngestOutcome.UPDATED if anterior is not None else IngestOutcome.INDEXED
            ),
            chunks_indexed=len(registros),
            chunks_removed=removidos,
        )
        logger.info(
            "memory.knowledge.ingerido",
            doc_id=document.doc_id,
            outcome=resultado.outcome.value,
            chunks=resultado.chunks_indexed,
        )
        await self._publicar(resultado)
        return resultado

    async def ingest_many(
        self, documents: Sequence[KnowledgeDocument]
    ) -> list[IngestResult]:
        """Reindexação incremental de um lote — o que o job da v1.4 chama."""
        return [await self.ingest(documento) for documento in documents]

    async def forget(self, doc_id: str) -> int:
        """Remove o documento e todos os chunks dele. `plan.md` §10: até a fonte sumir."""
        entrada = await self._index.delete(doc_id)
        if entrada is None:
            return 0
        removidos = await self._store.delete(entrada.chunk_ids)
        logger.info("memory.knowledge.esquecido", doc_id=doc_id, chunks=removidos)
        return removidos

    # -- busca ------------------------------------------------------------ #

    async def search(self, query: str, *, limit: int = 5) -> list[RetrievedChunk]:
        """Busca semântica. O vetor da consulta sai da mesma porta da ingestão."""
        if not query.strip():
            return []
        vetores = await self._provider.embed([query])
        if not vetores:
            return []
        achados = await self._store.search(
            vetores[0], namespace=self._namespace, limit=limit
        )
        return [
            RetrievedChunk(
                doc_id=m.record.metadata.get("doc_id", m.record.id),
                source=m.record.metadata.get("source", ""),
                title=m.record.metadata.get("title", ""),
                chunk_index=int(m.record.metadata.get("chunk_index", "0") or 0),
                text=m.record.text,
                score=m.score,
            )
            for m in achados
        ]

    # -- interno ---------------------------------------------------------- #

    async def _publicar(self, resultado: IngestResult) -> None:
        if self._bus is None or not resultado.touched:
            return
        update = MemoryUpdate(
            level=MemoryLevel.KNOWLEDGE,
            subject=resultado.doc_id,
            detail=resultado.outcome.value,
            count=resultado.chunks_indexed,
        )
        await self._bus.publish(
            Event(
                type=EventType.MEMORY_UPDATED,
                source="packages.memory.knowledge",
                payload=update.model_dump(mode="json"),
                trace_id=uuid4().hex,
            )
        )


def render_knowledge_context(
    chunks: Sequence[RetrievedChunk], *, max_chars: int = 1200
) -> str:
    """Formata os trechos recuperados para o prompt, com a fonte junto de cada um."""
    if not chunks:
        return ""
    linhas = ["Trechos relevantes da memória `knowledge`:"]
    linhas.extend(f"- ({c.source}) {c.text}" for c in chunks)
    return "\n".join(linhas)[:max_chars]


__all__ = [
    "DEFAULT_CHUNK_OVERLAP",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_NAMESPACE",
    "KnowledgeBase",
    "chunk_id",
    "chunk_text",
    "render_knowledge_context",
]
