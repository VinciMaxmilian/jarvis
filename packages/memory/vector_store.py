"""Dois adapters da porta `VectorStore`, e o motivo de serem dois.

**Por que existem dois.** O LanceDB é a escolha da v1 (`tools.md` §1.4:
embarcado, arquivo local, backup é copiar o diretório) e continua sendo. O que
mudou é que ele não roda *nesta* máquina: `import lancedb` não levanta
`ImportError`, ele **mata o processo com SIGILL** (exit 132). O binário Rust
exige AVX2/FMA/BMI2 e o i5-3470 (Ivy Bridge, 2012) só tem `avx f16c sse4_2`. É a
mesma parede de instrução que já tirou o KoboldCpp do projeto
(`plan-execution.md` §v1.0b). Nenhum pin de versão resolve — o `pip install`
funciona, o *import* é que morre.

Daí a forma: o LanceDB entra **atrás da porta**, exatamente como o adapter do
Ollama fica pronto-e-desligado. O default é o `InMemoryVectorStore`, cosseno em
Python puro, que roda em qualquer CPU e é o que a suíte exercita; o
`LanceDBVectorStore` está escrito, completo, e liga por configuração na máquina
que o suportar.

**Regra que não pode ser quebrada:** o `import lancedb` fica DENTRO do método.
No topo do módulo ele derrubaria o processo inteiro — API, orchestrator e a
suíte — em qualquer import de `packages.memory`.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import structlog

from packages.shared.ports import VectorMatch, VectorRecord

logger = structlog.get_logger(__name__)

#: Namespace vira predicado SQL no LanceDB; um conjunto fechado de caracteres é o
#: que impede uma aspa simples de virar injeção no `where`.
_NAMESPACE_VALIDO = re.compile(r"^[a-z0-9_]+$")


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosseno entre dois vetores. `0.0` quando um deles é nulo."""
    if len(a) != len(b):
        raise ValueError(
            f"dimensão incompatível: {len(a)} != {len(b)}. O índice foi escrito "
            "com outro modelo de embedding?"
        )
    produto = sum(x * y for x, y in zip(a, b, strict=True))
    norma_a = math.sqrt(sum(x * x for x in a))
    norma_b = math.sqrt(sum(y * y for y in b))
    if norma_a == 0.0 or norma_b == 0.0:
        return 0.0
    return produto / (norma_a * norma_b)


def _validar_namespace(namespace: str) -> str:
    if not _NAMESPACE_VALIDO.match(namespace):
        raise ValueError(
            f"namespace inválido: {namespace!r}. Use [a-z0-9_]+ — o valor entra "
            "num predicado do LanceDB."
        )
    return namespace


class InMemoryVectorStore:
    """`VectorStore` em dicionário, com cosseno em Python puro.

    É o adapter **default**: sem dependência nativa, roda em qualquer CPU e dá
    ranking determinístico, que é o que permite um teste afirmar a ordem exata
    dos vizinhos. O custo é linear no número de registros — irrelevante na ordem
    de grandeza de um sistema de uma pessoa, e o dia em que deixar de ser é o dia
    de ligar o LanceDB.
    """

    def __init__(self, persist_path: str | Path | None = None) -> None:
        self._registros: dict[str, VectorRecord] = {}
        self._persist_path = Path(persist_path) if persist_path else None
        
        if self._persist_path and self._persist_path.exists():
            self._load()

    def _load(self) -> None:
        """Carrega os vetores do arquivo JSON de forma síncrona (boot)."""
        if not self._persist_path:
            return
        try:
            with self._persist_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            
            for item in data:
                record = VectorRecord(**item)
                self._registros[record.id] = record
            logger.info("memory.vector_store.loaded", path=str(self._persist_path), records=len(self._registros))
        except Exception as exc:
            logger.error("memory.vector_store.load_failed", error=str(exc))

    def _save(self) -> None:
        """Salva os vetores no arquivo JSON (de forma síncrona). 
        Usamos I/O síncrono rápido porque o arquivo não deve passar de alguns MB."""
        if not self._persist_path:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = [r.model_dump(mode="json") for r in self._registros.values()]
            
            # Save to a temporary file and atomic rename to avoid corruption
            temp_path = self._persist_path.with_suffix(".tmp")
            with temp_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            
            temp_path.replace(self._persist_path)
        except Exception as exc:
            logger.error("memory.vector_store.save_failed", error=str(exc))

    async def upsert(self, records: Sequence[VectorRecord]) -> int:
        for record in records:
            _validar_namespace(record.namespace)
            self._registros[record.id] = record.model_copy(deep=True)
        
        self._save()
        return len(records)

    async def search(
        self,
        embedding: Sequence[float],
        *,
        namespace: str = "default",
        limit: int = 5,
    ) -> list[VectorMatch]:
        candidatos = [
            VectorMatch(
                record=registro.model_copy(deep=True),
                score=cosine_similarity(embedding, registro.embedding),
            )
            for registro in self._registros.values()
            if registro.namespace == namespace
        ]
        # Desempate pelo id: dois chunks com o mesmo score precisam sair na mesma
        # ordem em toda execução, ou a asserção de ranking vira sorteio.
        candidatos.sort(key=lambda m: (-m.score, m.record.id))
        return candidatos[: max(0, limit)]

    async def delete(self, ids: Sequence[str]) -> int:
        removed = sum(1 for rid in ids if self._registros.pop(rid, None) is not None)
        if removed > 0:
            self._save()
        return removed

    async def get_all(self, *, namespace: str | None = None) -> list[VectorRecord]:
        return [
            registro.model_copy(deep=True)
            for registro in self._registros.values()
            if namespace is None or registro.namespace == namespace
        ]

    # -- inspeção (fora da porta; usada por teste e por job de reindexação) -- #

    def __len__(self) -> int:
        return len(self._registros)

    def ids(self) -> list[str]:
        return sorted(self._registros)


class LanceDBVectorStore:
    """`VectorStore` sobre LanceDB embarcado. **Não roda em CPU sem AVX2.**

    Escrito e completo, ligado por configuração (ver `packages/memory/factory.py`).
    Toda referência ao `lancedb` é lazy: ver o cabeçalho do módulo para o porquê.

    O `metadata` vai como coluna JSON de texto, e não como colunas soltas, porque
    o schema do Arrow é fixo por tabela — cada chave nova viraria migração de
    schema, e o RAG ganha chave nova toda vez que uma fonte nova é ingerida.
    """

    def __init__(
        self,
        path: str,
        *,
        table: str = "memory",
        dim: int,
    ) -> None:
        self._path = path
        self._table_name = table
        self._dim = dim
        self._table: Any | None = None

    # -- conexão ---------------------------------------------------------- #

    def _abrir(self) -> Any:
        """Abre (ou cria) a tabela. Síncrono: chamado sempre via `to_thread`."""
        if self._table is not None:
            return self._table

        # Import DENTRO do método, de propósito — ver o cabeçalho do módulo.
        import lancedb
        import pyarrow as pa

        db = lancedb.connect(self._path)
        schema = pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field("namespace", pa.string()),
                pa.field("text", pa.string()),
                pa.field("metadata", pa.string()),  # JSON serializado
                pa.field("vector", pa.list_(pa.float32(), self._dim)),
            ]
        )
        if self._table_name in db.table_names():
            self._table = db.open_table(self._table_name)
        else:
            self._table = db.create_table(self._table_name, schema=schema)
        return self._table

    # -- porta ------------------------------------------------------------ #

    async def upsert(self, records: Sequence[VectorRecord]) -> int:
        for record in records:
            _validar_namespace(record.namespace)
            if len(record.embedding) != self._dim:
                raise ValueError(
                    f"embedding de {len(record.embedding)} dimensões numa tabela "
                    f"de {self._dim}. Trocar de modelo de embedding exige "
                    "reindexar, não gravar por cima."
                )
        if not records:
            return 0
        await asyncio.to_thread(self._upsert_sync, list(records))
        return len(records)

    def _upsert_sync(self, records: list[VectorRecord]) -> None:
        tabela = self._abrir()
        # Delete-then-add em vez de `merge_insert`: o segundo mudou de assinatura
        # entre versões do LanceDB, e o par abaixo vale em todas.
        self._delete_sync([r.id for r in records])
        tabela.add(
            [
                {
                    "id": r.id,
                    "namespace": r.namespace,
                    "text": r.text,
                    "metadata": json.dumps(r.metadata, ensure_ascii=False),
                    "vector": [float(v) for v in r.embedding],
                }
                for r in records
            ]
        )

    async def search(
        self,
        embedding: Sequence[float],
        *,
        namespace: str = "default",
        limit: int = 5,
    ) -> list[VectorMatch]:
        _validar_namespace(namespace)
        linhas = await asyncio.to_thread(
            self._search_sync, [float(v) for v in embedding], namespace, max(0, limit)
        )
        saida: list[VectorMatch] = []
        for linha in linhas:
            bruto = linha.get("metadata") or "{}"
            try:
                metadata = json.loads(bruto)
            except ValueError:
                logger.error("memory.vector.metadata_invalido", id=linha.get("id"))
                metadata = {}
            saida.append(
                VectorMatch(
                    record=VectorRecord(
                        id=str(linha["id"]),
                        namespace=str(linha["namespace"]),
                        text=str(linha["text"]),
                        embedding=[float(v) for v in linha.get("vector", [])],
                        metadata={str(k): str(v) for k, v in metadata.items()},
                    ),
                    # A métrica é `cosine`, então a distância vem em [0, 2] e a
                    # similaridade é o complemento — a porta promete similaridade,
                    # onde maior é melhor, e não distância.
                    score=1.0 - float(linha.get("_distance", 1.0)),
                )
            )
        return saida

    def _search_sync(
        self, embedding: list[float], namespace: str, limit: int
    ) -> list[dict[str, Any]]:
        if limit == 0:
            return []
        tabela = self._abrir()
        consulta = (
            tabela.search(embedding)
            .metric("cosine")
            .where(f"namespace = '{namespace}'")
            .limit(limit)
        )
        resultado: list[dict[str, Any]] = consulta.to_list()
        return resultado

    async def delete(self, ids: Sequence[str]) -> int:
        if not ids:
            return 0
        return await asyncio.to_thread(self._delete_sync, list(ids))

    def _delete_sync(self, ids: list[str]) -> int:
        tabela = self._abrir()
        antes = tabela.count_rows()
        # O in no lanceSQL requer string formatada com aspas
        lista_sql = ", ".join(f"'{i}'" for i in ids)
        tabela.delete(f"id IN ({lista_sql})")
        depois = tabela.count_rows()
        return antes - depois

    async def get_all(self, *, namespace: str | None = None) -> list[VectorRecord]:
        return await asyncio.to_thread(self._get_all_sync, namespace)

    def _get_all_sync(self, namespace: str | None) -> list[VectorRecord]:
        tabela = self._abrir()
        query = tabela.search(None)
        if namespace is not None:
            query = query.where(f"namespace = '{namespace}'", prefilter=True)
        # `query.limit(None)` ou alto para trazer todos
        # LanceDB sem limit por padrão traz poucos registros (e.g. 10)
        df = query.limit(1000000).to_pandas()
        records = []
        for _, row in df.iterrows():
            records.append(
                VectorRecord(
                    id=row["id"],
                    namespace=row["namespace"],
                    text=row["text"],
                    embedding=list(row["vector"]),
                    metadata=json.loads(row["metadata"]) if row.get("metadata") else {},
                )
            )
        return records


__all__ = [
    "InMemoryVectorStore",
    "LanceDBVectorStore",
    "cosine_similarity",
]
