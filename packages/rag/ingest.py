"""Ponto único de indexação de texto no nível `knowledge`.

Antes deste módulo havia três implementações divergentes de "indexar texto" no
repo — `KnowledgeBase.ingest`, o handler `_knowledge_save` e o adapter do
reindex — e foi essa divergência que deixou passar o bug do chunk único: o
handler gravava o arquivo inteiro como UM vetor, o embedder truncava na janela
dele e o resto do documento sumia do índice **sem erro nenhum**. Quem indexa
passa a ser um lugar só.

Três decisões carregam o desenho:

**Não depende de `KnowledgeIndex`.** `KnowledgeBase.ingest` faz a coisa certa,
mas exige a porta de índice incremental, que a API não instancia — só o
scheduler tem. Aqui o "índice" é lido de volta do próprio `VectorStore`: o
`content_hash` viaja no metadata de cada chunk, então `get_all(namespace=...)`
filtrado por `doc_id` reconstrói tanto o hash anterior quanto a lista de ids já
gravados. Custa uma varredura linear do namespace, o que na ordem de grandeza de
um sistema de uma pessoa é mais barato que manter um segundo arquivo de índice
em `data/knowledge/_index.json` — que ainda por cima poderia divergir do store
depois de um crash, e divergência silenciosa é exatamente o que se está
consertando.

**Conteúdo inalterado custa zero embedding.** É a mesma regra da
`KnowledgeBase`: hash igual → sai com `UNCHANGED` antes de tocar no provider.
Sem isso, o `knowledge_save` reembedaria o arquivo temático inteiro a cada fato
de uma linha acrescentado.

**O `VectorStore` é o caminho garantido; o Agno é o melhor esforço.** O Agno
depende de Postgres com pgvector e de chave do Gemini — falha dele vira warning
e a ingestão continua. O inverso deixaria o dono sem nenhuma cópia do que ele
mandou lembrar.

Erro aqui vira **resultado estruturado**, não exceção: quem chama é uma tool
dentro do laço do agente, e exceção ali derruba o turno inteiro do chat.
"""

from __future__ import annotations

from typing import Any

import structlog

from packages.memory.knowledge import DEFAULT_NAMESPACE, chunk_id, chunk_text
from packages.memory.models import IngestOutcome, IngestResult, content_hash
from packages.shared.ports import VectorRecord, VectorStore

logger = structlog.get_logger(__name__)

DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 120


class IngestReport(IngestResult):
    """O que a ingestão fez, em números.

    Herda de `IngestResult` (`packages/memory/models.py`) em vez de repetir os
    quatro campos: os dois relatam a mesma coisa e o dia em que divergirem é o
    dia em que a aba Memory passa a mostrar número diferente conforme o caminho
    que indexou. O nome próprio existe porque o chamador desta camada fala de
    "report", e porque herdar deixa espaço para campos de proveniência da
    pesquisa web sem mexer no modelo de memória.
    """


async def _estado_anterior(
    store: VectorStore, *, doc_id: str, namespace: str
) -> tuple[str | None, list[str]]:
    """Descobre o hash e os ids já gravados para `doc_id`, lendo o próprio store.

    Devolve `(hash_anterior, ids_anteriores)`. Hash `None` significa documento
    novo — ou documento gravado por uma versão anterior do código, que não
    escrevia `content_hash` no metadata; nesse caso reindexar é o certo, porque
    é justamente o vetor gigante e truncado que se quer substituir.
    """
    try:
        registros = await store.get_all(namespace=namespace)
    except Exception as exc:  # store fora do ar não pode virar "nunca indexado"
        logger.warning("rag.ingest.leitura_do_indice_falhou", doc_id=doc_id, error=str(exc))
        return None, []

    meus = [r for r in registros if r.metadata.get("doc_id") == doc_id]
    if not meus:
        return None, []

    hashes = {r.metadata.get("content_hash", "") for r in meus}
    # Hash divergente entre chunks do mesmo documento = ingestão interrompida no
    # meio. Tratar como "mudou" força a regravação completa, que é a saída.
    anterior = hashes.pop() if len(hashes) == 1 else None
    return (anterior or None), sorted(r.id for r in meus)


async def ingest_document(
    *,
    text: str,
    doc_id: str,
    source: str,
    metadata: dict[str, str] | None = None,
    embed_llm: Any,
    memory_store: VectorStore,
    agno_knowledge: Any | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    namespace: str = DEFAULT_NAMESPACE,
) -> IngestReport:
    """Indexa `text` no nível `knowledge`: chunk → hash → embed → grava.

    `metadata` do chamador é preservado e enriquecido com a proveniência
    (`doc_id`, `source`, `chunk_index`, `content_hash`). Tudo vira `str` porque
    `VectorRecord.metadata` é `dict[str, str]` — um `int` ali estoura a
    validação do pydantic no meio do laço, com metade dos chunks já gravados.

    Texto vazio devolve `UNCHANGED` com zero chunks em vez de levantar: o
    chamador é uma tool, e a ausência de conteúdo é um resultado, não um defeito
    do programa.
    """
    pedacos = chunk_text(text, size=chunk_size, overlap=chunk_overlap)
    if not pedacos:
        logger.warning("rag.ingest.texto_vazio", doc_id=doc_id, source=source)
        return IngestReport(doc_id=doc_id, outcome=IngestOutcome.UNCHANGED)

    hash_novo = content_hash(text)
    hash_anterior, ids_anteriores = await _estado_anterior(
        memory_store, doc_id=doc_id, namespace=namespace
    )

    if hash_anterior is not None and hash_anterior == hash_novo:
        logger.debug("rag.ingest.inalterado", doc_id=doc_id, chunks=len(ids_anteriores))
        return IngestReport(doc_id=doc_id, outcome=IngestOutcome.UNCHANGED)

    embeddings = await embed_llm.embed(pedacos)
    if len(embeddings) != len(pedacos):
        raise ValueError(
            f"provider devolveu {len(embeddings)} embeddings para {len(pedacos)} chunks"
        )

    base_meta = {str(k): str(v) for k, v in (metadata or {}).items()}
    registros = [
        VectorRecord(
            id=chunk_id(doc_id, i),
            namespace=namespace,
            text=pedaco,
            embedding=list(vetor),
            metadata={
                **base_meta,
                "doc_id": doc_id,
                "source": source,
                "chunk_index": str(i),
                "content_hash": hash_novo,
            },
        )
        for i, (pedaco, vetor) in enumerate(zip(pedacos, embeddings, strict=True))
    ]

    # Chunks da versão anterior que a nova não reaproveita. Um texto que encurtou
    # deixa os últimos ids órfãos, e órfão não é lixo inerte: ele continua sendo
    # devolvido pela busca como se fosse o documento atual.
    novos_ids = {r.id for r in registros}
    obsoletos = [i for i in ids_anteriores if i not in novos_ids]
    removidos = await memory_store.delete(obsoletos) if obsoletos else 0

    await memory_store.upsert(registros)

    if agno_knowledge is not None:
        try:
            from packages.rag.agno_knowledge import add_knowledge

            await add_knowledge(
                text=text,
                name=doc_id,
                metadata={**base_meta, "doc_id": doc_id, "source": source},
                knowledge=agno_knowledge,
                replace=True,
            )
        except Exception as exc:
            # O Agno é a segunda cópia, não a primeira: Postgres fora do ar ou
            # chave do Gemini vencida não podem apagar o que já entrou no store.
            logger.warning("rag.ingest.agno_falhou", doc_id=doc_id, error=str(exc))

    relatorio = IngestReport(
        doc_id=doc_id,
        outcome=(
            IngestOutcome.UPDATED if ids_anteriores else IngestOutcome.INDEXED
        ),
        chunks_indexed=len(registros),
        chunks_removed=removidos,
    )
    logger.info(
        "rag.ingest.concluido",
        doc_id=doc_id,
        outcome=relatorio.outcome.value,
        chunks=relatorio.chunks_indexed,
        removidos=relatorio.chunks_removed,
    )
    return relatorio


__all__ = [
    "DEFAULT_CHUNK_OVERLAP",
    "DEFAULT_CHUNK_SIZE",
    "IngestOutcome",
    "IngestReport",
    "ingest_document",
]
