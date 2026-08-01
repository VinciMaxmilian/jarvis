"""Adapters das portas internas: um em memória, um em arquivo JSON.

O par existe pelo mesmo motivo em toda porta deste repositório: o de memória é
determinístico e serve a suíte; o de disco é o que roda de verdade. E aqui a
diferença não é conveniência — o aceite da v1.3 é *matar o processo e recuperar*,
e só o adapter de disco tem como passar nisso.

**A escrita é atômica** (`tmp` no mesmo diretório + `os.replace`). Escrever por
cima do arquivo bom e morrer no meio deixaria um JSON truncado, e o resume leria
lixo em vez de ler nada — que é o pior dos dois desfechos possíveis.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

import structlog

from packages.memory.models import (
    ExperienceRecord,
    IndexedDocument,
    WorkingMemoryState,
)

logger = structlog.get_logger(__name__)


def _escrever_atomico(destino: Path, conteudo: str) -> None:
    """Grava por `tmp` + `os.replace`, que é atômico no mesmo sistema de arquivos."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.fspath(destino.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as arquivo:
            arquivo.write(conteudo)
            arquivo.flush()
            # fsync antes do replace: sem ele o `kill -9` pode deixar o rename
            # feito e o conteúdo ainda no page cache.
            os.fsync(arquivo.fileno())
        os.replace(tmp, destino)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _ler_json(caminho: Path) -> str | None:
    try:
        return caminho.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


# --------------------------------------------------------------------------- #
# working
# --------------------------------------------------------------------------- #


class InMemoryWorkingMemoryStore:
    """`WorkingMemoryStore` em dicionário. Não sobrevive ao processo, de propósito."""

    def __init__(self) -> None:
        self._estados: dict[UUID, WorkingMemoryState] = {}

    async def load(self, task_id: UUID) -> WorkingMemoryState | None:
        estado = self._estados.get(task_id)
        return estado.model_copy(deep=True) if estado else None

    async def save(self, state: WorkingMemoryState) -> None:
        self._estados[state.task_id] = state.model_copy(deep=True)

    async def delete(self, task_id: UUID) -> bool:
        return self._estados.pop(task_id, None) is not None


class JsonFileWorkingMemoryStore:
    """`WorkingMemoryStore` em disco: um arquivo por task.

    Um arquivo por task, e não um só com tudo: duas tasks em paralelo escrevendo
    o mesmo arquivo perderiam uma da outra, e o checkpoint deixaria de ser
    checkpoint.
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def _caminho(self, task_id: UUID) -> Path:
        return self._root / f"{task_id}.json"

    async def load(self, task_id: UUID) -> WorkingMemoryState | None:
        bruto = await asyncio.to_thread(_ler_json, self._caminho(task_id))
        if bruto is None:
            return None
        try:
            return WorkingMemoryState.model_validate_json(bruto)
        except ValueError as exc:
            # Arquivo corrompido é ruído conhecido, não crash: a task recomeça sem
            # contexto, que é pior do que ter o contexto e melhor do que não subir.
            logger.error(
                "memory.working.arquivo_invalido", task_id=str(task_id), error=str(exc)
            )
            return None

    async def save(self, state: WorkingMemoryState) -> None:
        await asyncio.to_thread(
            _escrever_atomico,
            self._caminho(state.task_id),
            state.model_dump_json(indent=2),
        )

    async def delete(self, task_id: UUID) -> bool:
        caminho = self._caminho(task_id)
        existia = await asyncio.to_thread(caminho.exists)
        if existia:
            await asyncio.to_thread(caminho.unlink, True)
        return existia


# --------------------------------------------------------------------------- #
# knowledge (índice incremental)
# --------------------------------------------------------------------------- #


class InMemoryKnowledgeIndex:
    """`KnowledgeIndex` em dicionário."""

    def __init__(self) -> None:
        self._entradas: dict[str, IndexedDocument] = {}

    async def get(self, doc_id: str) -> IndexedDocument | None:
        entrada = self._entradas.get(doc_id)
        return entrada.model_copy(deep=True) if entrada else None

    async def put(self, entry: IndexedDocument) -> None:
        self._entradas[entry.doc_id] = entry.model_copy(deep=True)

    async def delete(self, doc_id: str) -> IndexedDocument | None:
        return self._entradas.pop(doc_id, None)

    async def all(self) -> list[IndexedDocument]:
        return [e.model_copy(deep=True) for e in self._entradas.values()]


class JsonFileKnowledgeIndex:
    """`KnowledgeIndex` num único arquivo JSON, carregado na primeira leitura.

    Arquivo único aqui (e não um por documento) porque o índice é lido inteiro a
    cada reindexação e escrito raramente — o custo está invertido em relação ao
    working memory.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._cache: dict[str, IndexedDocument] | None = None
        self._lock = asyncio.Lock()

    async def _carregar(self) -> dict[str, IndexedDocument]:
        if self._cache is not None:
            return self._cache
        bruto = await asyncio.to_thread(_ler_json, self._path)
        entradas: dict[str, IndexedDocument] = {}
        if bruto:
            try:
                linhas = json.loads(bruto)
                for linha in linhas:
                    entrada = IndexedDocument.model_validate(linha)
                    entradas[entrada.doc_id] = entrada
            except ValueError as exc:
                logger.error("memory.knowledge.indice_invalido", error=str(exc))
                entradas = {}
        self._cache = entradas
        return entradas

    async def _persistir(self) -> None:
        entradas = await self._carregar()
        conteudo = json.dumps(
            [e.model_dump(mode="json") for e in entradas.values()], indent=2
        )
        await asyncio.to_thread(_escrever_atomico, self._path, conteudo)

    async def get(self, doc_id: str) -> IndexedDocument | None:
        async with self._lock:
            entrada = (await self._carregar()).get(doc_id)
            return entrada.model_copy(deep=True) if entrada else None

    async def put(self, entry: IndexedDocument) -> None:
        async with self._lock:
            (await self._carregar())[entry.doc_id] = entry.model_copy(deep=True)
            await self._persistir()

    async def delete(self, doc_id: str) -> IndexedDocument | None:
        async with self._lock:
            removida = (await self._carregar()).pop(doc_id, None)
            if removida is not None:
                await self._persistir()
            return removida

    async def all(self) -> list[IndexedDocument]:
        async with self._lock:
            return [e.model_copy(deep=True) for e in (await self._carregar()).values()]


# --------------------------------------------------------------------------- #
# experience
# --------------------------------------------------------------------------- #


class InMemoryExperienceStore:
    """`ExperienceStore` em dicionário."""

    def __init__(self) -> None:
        self._registros: dict[str, ExperienceRecord] = {}

    async def get(self, record_id: str) -> ExperienceRecord | None:
        registro = self._registros.get(record_id)
        return registro.model_copy(deep=True) if registro else None

    async def put(self, record: ExperienceRecord) -> None:
        self._registros[record.id] = record.model_copy(deep=True)

    async def all(self) -> list[ExperienceRecord]:
        return [r.model_copy(deep=True) for r in self._registros.values()]

    async def delete(self, record_ids: Sequence[str]) -> int:
        return sum(1 for rid in record_ids if self._registros.pop(rid, None) is not None)


class JsonFileExperienceStore:
    """`ExperienceStore` num arquivo JSON. Permanente, cresce por acúmulo."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._cache: dict[str, ExperienceRecord] | None = None
        self._lock = asyncio.Lock()

    async def _carregar(self) -> dict[str, ExperienceRecord]:
        if self._cache is not None:
            return self._cache
        bruto = await asyncio.to_thread(_ler_json, self._path)
        registros: dict[str, ExperienceRecord] = {}
        if bruto:
            try:
                for linha in json.loads(bruto):
                    registro = ExperienceRecord.model_validate(linha)
                    registros[registro.id] = registro
            except ValueError as exc:
                logger.error("memory.experience.arquivo_invalido", error=str(exc))
                registros = {}
        self._cache = registros
        return registros

    async def _persistir(self) -> None:
        registros = await self._carregar()
        conteudo = json.dumps(
            [r.model_dump(mode="json") for r in registros.values()], indent=2
        )
        await asyncio.to_thread(_escrever_atomico, self._path, conteudo)

    async def get(self, record_id: str) -> ExperienceRecord | None:
        async with self._lock:
            registro = (await self._carregar()).get(record_id)
            return registro.model_copy(deep=True) if registro else None

    async def put(self, record: ExperienceRecord) -> None:
        async with self._lock:
            (await self._carregar())[record.id] = record.model_copy(deep=True)
            await self._persistir()

    async def all(self) -> list[ExperienceRecord]:
        async with self._lock:
            return [r.model_copy(deep=True) for r in (await self._carregar()).values()]

    async def delete(self, record_ids: Sequence[str]) -> int:
        async with self._lock:
            registros = await self._carregar()
            removidos = sum(
                1 for rid in record_ids if registros.pop(rid, None) is not None
            )
            if removidos:
                await self._persistir()
            return removidos


__all__ = [
    "InMemoryExperienceStore",
    "InMemoryKnowledgeIndex",
    "InMemoryWorkingMemoryStore",
    "JsonFileExperienceStore",
    "JsonFileKnowledgeIndex",
    "JsonFileWorkingMemoryStore",
]
