"""Portas que o scheduler **consome**.

Ficam aqui, e não em `packages/shared/ports.py`, porque são portas de um
consumidor só: quem define o contrato é quem precisa dele. `packages/shared`
guarda o que atravessa o sistema inteiro (`GoalStore`, `EventBus`); um protocolo
que apenas o job de limpeza usa não tem por que virar vocabulário global.

As três existem pelo mesmo motivo prático: **testar sem processo externo, sem
rede e sem inferência**. `pg_dump`, Redis e o índice vetorial são substituídos
por dublês determinísticos na suíte; o que a suíte exercita é a lógica dos jobs,
que é onde os bugs moram.

Nota sobre o LanceDB: **nenhum módulo deste pacote importa `lancedb`.** Nesta
máquina (i5-3470, Ivy Bridge, sem AVX2/FMA) o binário Rust da biblioteca aborta
o processo com SIGILL no *import* — um `import lancedb` no topo de um módulo do
scheduler derrubaria a aplicação inteira. O snapshot do backup é cópia de
diretório (não usa a biblioteca) e a reindexação fala com `KnowledgeIndex`, que
o adaptador de `packages/memory` implementa com import preguiçoso.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from packages.scheduler.models import (
    CommandResult,
    IndexedDocument,
    KnowledgeDocument,
)


@runtime_checkable
class CommandRunner(Protocol):
    """Executa um processo externo e devolve o resultado já decodificado.

    Existe para que o backup possa ser testado sem `pg_dump` instalado: o dublê
    escreve um arquivo qualquer e devolve `returncode=0`, e a suíte verifica o
    que o job faz com isso — manifesto, digest, evento, retenção.
    """

    async def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> CommandResult: ...


@runtime_checkable
class KnowledgeIndex(Protocol):
    """Índice do nível `knowledge` da memória (v1.3), visto pelo reindexador.

    Deliberadamente pequeno: o scheduler decide **o que** reindexar (diff por
    SHA-256), nunca **como** vetorizar. Embedding depende de modelo de
    inferência; diff de conteúdo não depende de nada. É essa fronteira que
    permite a reindexação incremental ser exercitada numa máquina sem modelo
    algum rodando.

    O adaptador real vive em `packages/memory` (v1.3) e envolve a porta
    `VectorStore` de `packages/shared/ports.py`.
    """

    async def list_indexed(self) -> list[IndexedDocument]:
        """Tudo que já está no índice, com o SHA-256 usado na última indexação."""
        ...

    async def upsert(self, document: KnowledgeDocument) -> None:
        """Insere ou substitui. Idempotente por `doc_id`."""
        ...

    async def delete(self, doc_ids: Sequence[str]) -> int:
        """Remove por id. Devolve quantos saíram de fato."""
        ...


@runtime_checkable
class ShortTermKeyspace(Protocol):
    """Visão de manutenção sobre o keyspace da short-term memory (Redis).

    Não é a porta de *uso* da memória (`ShortTermMemory.get_state` e afins) — é
    a de *faxina*. Separar as duas é o que impede o job de limpeza de precisar
    conhecer o formato do que está guardado.
    """

    async def scan(self, pattern: str) -> list[str]:
        """Chaves que casam com o padrão (`SCAN MATCH`, nunca `KEYS`)."""
        ...

    async def ttl_seconds(self, key: str) -> int:
        """Semântica do Redis: `-1` = sem expiração, `-2` = chave inexistente."""
        ...

    async def delete(self, keys: Sequence[str]) -> int: ...


__all__ = ["CommandRunner", "KnowledgeIndex", "ShortTermKeyspace"]
