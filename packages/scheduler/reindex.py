"""Reindexação **incremental** do nível `knowledge` da memória.

Incremental é a palavra que carrega o peso: reindexar tudo toda madrugada custa
uma vetorização completa do corpus por dia, e vetorização é a operação cara (e,
nesta máquina, indisponível — não há modelo de inferência rodando). O trabalho
real do job é decidir **o mínimo** que precisa ser tocado.

O critério é SHA-256 do conteúdo, não `mtime`: `git checkout`, `cp -p` e
restauração de backup mexem em timestamp sem mudar byte, e cada um deles
dispararia uma reindexação inteira à toa. Conteúdo igual, digest igual, nada a
fazer.

A vetorização em si fica atrás de `KnowledgeIndex`. Este módulo **não** importa
`lancedb` nem provider de LLM: o diff é aritmética de hash e roda em qualquer
CPU, o que é o que permite testar a lógica sem modelo algum.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import structlog

from packages.scheduler.models import (
    IndexedDocument,
    KnowledgeDocument,
    ReindexResult,
)
from packages.scheduler.ports import KnowledgeIndex
from packages.shared.contracts import utcnow

logger = structlog.get_logger(__name__)

#: Extensões consideradas documento de conhecimento. Binário não entra: o índice
#: guarda texto vetorizável, e um PDF só vira conhecimento depois de extraído —
#: o que é trabalho de capability, não de scheduler (`plan-execution.md` §2b.6).
DEFAULT_PATTERNS: tuple[str, ...] = ("*.md", "*.txt", "*.rst")

#: Teto por arquivo. Documento maior que isto quase sempre é log ou dump que caiu
#: na pasta errada; indexá-lo custa caro e polui a busca.
DEFAULT_MAX_BYTES = 2 * 1024 * 1024


class ReindexService:
    """Compara o disco com o índice e aplica só a diferença."""

    def __init__(
        self,
        *,
        source_dir: Path | None = None,
        index: KnowledgeIndex | None = None,
        patterns: Sequence[str] = DEFAULT_PATTERNS,
        max_bytes: int = DEFAULT_MAX_BYTES,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._source = source_dir
        self._index = index
        self._patterns = tuple(patterns)
        self._max_bytes = max_bytes
        self._clock = clock

    async def run(self) -> ReindexResult:
        motivo = self._motivo_para_pular()
        if motivo:
            logger.warning("scheduler.reindex.skipped", reason=motivo)
            return ReindexResult(skipped_reason=motivo)

        # `_motivo_para_pular` já garantiu que os dois existem.
        assert self._source is not None
        assert self._index is not None

        no_disco = self._varrer(self._source)
        indexados = {doc.doc_id: doc for doc in await self._index.list_indexed()}

        novos: list[KnowledgeDocument] = []
        alterados: list[KnowledgeDocument] = []
        for doc_id, documento in no_disco.items():
            anterior = indexados.get(doc_id)
            if anterior is None:
                novos.append(documento)
            elif anterior.content_hash != documento.sha256:
                alterados.append(documento)

        removidos = sorted(set(indexados) - set(no_disco))

        for documento in (*novos, *alterados):
            await self._index.upsert(documento)
        apagados = await self._index.delete(removidos) if removidos else 0

        resultado = ReindexResult(
            scanned=len(no_disco),
            added=len(novos),
            updated=len(alterados),
            removed=apagados,
            unchanged=len(no_disco) - len(novos) - len(alterados),
        )
        logger.info(
            "scheduler.reindex.done",
            scanned=resultado.scanned,
            added=resultado.added,
            updated=resultado.updated,
            removed=resultado.removed,
            unchanged=resultado.unchanged,
        )
        return resultado

    # -- interno ------------------------------------------------------------ #

    def _motivo_para_pular(self) -> str:
        """Motivo legível, ou string vazia quando dá para trabalhar.

        Pular é **logado em warning** e devolvido no resultado, nunca escondido:
        job que não faz nada e diz "concluído" é o defeito D-11 de volta com
        outra roupa.
        """
        if self._index is None:
            return "sem KnowledgeIndex ligado (v1.3 ainda não entregou o adaptador)"
        if self._source is None:
            return "sem diretório de origem configurado"
        if not self._source.is_dir():
            return f"diretório de origem inexistente: {self._source}"
        return ""

    def _varrer(self, raiz: Path) -> dict[str, KnowledgeDocument]:
        encontrados: dict[str, KnowledgeDocument] = {}
        for padrao in self._patterns:
            for arquivo in sorted(raiz.rglob(padrao)):
                if not arquivo.is_file():
                    continue
                estado = arquivo.stat()
                if estado.st_size > self._max_bytes:
                    logger.warning(
                        "scheduler.reindex.skipped_file",
                        path=arquivo.relative_to(raiz).as_posix(),
                        bytes=estado.st_size,
                        reason="acima do limite",
                    )
                    continue
                bruto = arquivo.read_bytes()
                doc_id = arquivo.relative_to(raiz).as_posix()
                encontrados[doc_id] = KnowledgeDocument(
                    doc_id=doc_id,
                    source=str(arquivo),
                    sha256=hashlib.sha256(bruto).hexdigest(),
                    text=bruto.decode("utf-8", errors="replace"),
                    modified_at=datetime.fromtimestamp(estado.st_mtime, tz=UTC),
                )
        return encontrados


class InMemoryKnowledgeIndex:
    """`KnowledgeIndex` em dicionário — o default enquanto a v1.3 não chega.

    Não é dublê de teste disfarçado: é o mesmo papel do `InMemoryVectorStore` que
    a v1.3 usa como default. Ele torna o job **exercitável** (o diff roda, o
    resultado é real) sem prometer busca semântica que ninguém pode entregar numa
    máquina sem inferência. O que ele não faz — sobreviver a restart — é
    exatamente o que o adaptador do LanceDB vai fazer.
    """

    def __init__(self) -> None:
        self._docs: dict[str, IndexedDocument] = {}
        self.texts: dict[str, str] = {}

    async def list_indexed(self) -> list[IndexedDocument]:
        return [doc.model_copy(deep=True) for doc in self._docs.values()]

    async def upsert(self, document: KnowledgeDocument) -> None:
        self._docs[document.doc_id] = IndexedDocument(
            doc_id=document.doc_id, sha256=document.sha256
        )
        self.texts[document.doc_id] = document.text

    async def delete(self, doc_ids: Sequence[str]) -> int:
        apagados = 0
        for doc_id in doc_ids:
            if self._docs.pop(doc_id, None) is not None:
                self.texts.pop(doc_id, None)
                apagados += 1
        return apagados


__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_PATTERNS",
    "InMemoryKnowledgeIndex",
    "ReindexService",
]
