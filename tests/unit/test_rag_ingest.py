"""Fase 0 do `plano-pesquisa-knowledge.md` — o ponto único de indexação.

O bug que originou este módulo não quebrava nada: `_knowledge_save` mandava o
arquivo inteiro como UM vetor, o embedder truncava na janela dele e o resto do
documento desaparecia do índice **em silêncio**. Nenhuma exceção, nenhum log de
erro, e a busca continuava respondendo — com um vetor médio que não se parece
com pergunta nenhuma.

Por isso a suíte olha para o **conteúdo do `VectorStore`**, não para o retorno
da função: contar chunks no relatório provaria só que o laço rodou. O que
precisa ser verdade é que os ids `#0..#N-1` existem na loja, que a segunda
ingestão do mesmo texto não gastou embedding, e que encurtar o texto não deixou
chunk fantasma para trás.

Sem rede: `FakeEmbeddingProvider` e `InMemoryVectorStore` são os mesmos dublês
de `test_memory_knowledge.py` — a porta exercitada é a de produção.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from packages.memory.models import IngestOutcome
from packages.memory.vector_store import InMemoryVectorStore
from packages.rag.ingest import ingest_document
from tests.conftest import FakeEmbeddingProvider

# --------------------------------------------------------------------------- #
# Corpus
# --------------------------------------------------------------------------- #
#
# Texto com espaços de verdade: `chunk_text` recua até o último espaço para não
# partir palavra ao meio, e uma string de 3000 caracteres sem espaço nenhum
# exercitaria o caminho degenerado em vez do normal.

_FRASE = (
    "Um algoritmo é uma sequência finita de passos que resolve um problema bem "
    "definido, e a lógica de programação é o que decide a ordem desses passos. "
)
TEXTO_LONGO = _FRASE * 40  # ~5.6 KB
TEXTO_CURTO = "O usuário gosta da cor vermelha."


async def _ingerir(
    texto: str,
    *,
    store: InMemoryVectorStore,
    provider: FakeEmbeddingProvider,
    doc_id: str = "docs/logica.md",
    **kwargs: object,
):
    return await ingest_document(
        text=texto,
        doc_id=doc_id,
        source=doc_id,
        embed_llm=provider,
        memory_store=store,
        **kwargs,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- #
# Chunking — o bug da Fase 0
# --------------------------------------------------------------------------- #


async def test_ingest_document_chunka(
    fake_embeddings: FakeEmbeddingProvider,
) -> None:
    """Documento grande vira N chunks com ids `#0..#N-1`, não um vetor só."""
    store = InMemoryVectorStore()

    relatorio = await _ingerir(TEXTO_LONGO, store=store, provider=fake_embeddings)

    assert relatorio.outcome is IngestOutcome.INDEXED
    assert relatorio.chunks_indexed > 1, "documento de ~5 KB tem que virar vários chunks"

    gravados = await store.get_all(namespace="knowledge")
    assert len(gravados) == relatorio.chunks_indexed
    assert {r.id for r in gravados} == {
        f"docs/logica.md#{i}" for i in range(relatorio.chunks_indexed)
    }
    # Cada chunk cabe na janela do embedder; o texto do documento inteiro não.
    assert all(len(r.text) <= 800 for r in gravados)


async def test_ingest_document_grava_proveniencia(
    fake_embeddings: FakeEmbeddingProvider,
) -> None:
    """Sem `doc_id`/`source` no metadata não existe "esqueça tudo sobre X"."""
    store = InMemoryVectorStore()

    await _ingerir(
        TEXTO_LONGO,
        store=store,
        provider=fake_embeddings,
        metadata={"kind": "web", "topico": "logica"},
    )

    primeiro = next(
        r for r in await store.get_all(namespace="knowledge") if r.id.endswith("#0")
    )
    assert primeiro.metadata["doc_id"] == "docs/logica.md"
    assert primeiro.metadata["source"] == "docs/logica.md"
    assert primeiro.metadata["chunk_index"] == "0"
    assert primeiro.metadata["content_hash"]
    # Metadata do chamador sobrevive à ingestão.
    assert primeiro.metadata["kind"] == "web"
    assert primeiro.metadata["topico"] == "logica"
    # `VectorRecord.metadata` é `dict[str, str]`: um int aqui estouraria a
    # validação no meio do laço, com parte dos chunks já gravada.
    assert all(isinstance(v, str) for v in primeiro.metadata.values())


# --------------------------------------------------------------------------- #
# Incremental — conteúdo inalterado custa zero
# --------------------------------------------------------------------------- #


async def test_ingest_document_inalterado_nao_embeda(
    fake_embeddings: FakeEmbeddingProvider,
) -> None:
    """Reingerir o mesmo texto não chama o provider de embedding nenhuma vez.

    É o que impede o `knowledge_save` de reembedar o arquivo temático inteiro a
    cada fato de uma linha acrescentado.
    """
    store = InMemoryVectorStore()

    await _ingerir(TEXTO_LONGO, store=store, provider=fake_embeddings)
    chamadas_apos_primeira = fake_embeddings.embed_calls
    assert chamadas_apos_primeira == 1

    relatorio = await _ingerir(TEXTO_LONGO, store=store, provider=fake_embeddings)

    assert relatorio.outcome is IngestOutcome.UNCHANGED
    assert relatorio.chunks_indexed == 0
    assert fake_embeddings.embed_calls == chamadas_apos_primeira


# --------------------------------------------------------------------------- #
# Órfãos — o que a `KnowledgeBase` faz certo e as tools não faziam
# --------------------------------------------------------------------------- #


async def test_ingest_document_remove_orfaos(
    fake_embeddings: FakeEmbeddingProvider,
) -> None:
    """Texto que encurtou apaga os chunks que sobraram da versão anterior.

    Órfão não é lixo inerte: ele continua sendo devolvido pela busca como se
    fosse o documento atual.
    """
    store = InMemoryVectorStore()

    longo = await _ingerir(TEXTO_LONGO, store=store, provider=fake_embeddings)
    assert longo.chunks_indexed > 1

    curto = await _ingerir(TEXTO_CURTO, store=store, provider=fake_embeddings)

    assert curto.outcome is IngestOutcome.UPDATED
    assert curto.chunks_indexed == 1
    assert curto.chunks_removed == longo.chunks_indexed - 1

    restantes = await store.get_all(namespace="knowledge")
    assert [r.id for r in restantes] == ["docs/logica.md#0"]
    assert restantes[0].text == TEXTO_CURTO


# --------------------------------------------------------------------------- #
# Degradação — erro vira resultado, não exceção
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("vazio", ["", "   \n\t  \n "])
async def test_ingest_document_texto_vazio(
    fake_embeddings: FakeEmbeddingProvider, vazio: str
) -> None:
    """Quem chama é uma tool: exceção ali derrubaria o turno inteiro do chat."""
    store = InMemoryVectorStore()

    relatorio = await _ingerir(vazio, store=store, provider=fake_embeddings)

    assert relatorio.outcome is IngestOutcome.UNCHANGED
    assert relatorio.chunks_indexed == 0
    assert fake_embeddings.embed_calls == 0
    assert await store.get_all(namespace="knowledge") == []


class _AgnoQuebrado:
    """Knowledge do Agno indisponível — Postgres fora do ar, chave vencida."""

    def remove_vectors_by_name(self, name: str) -> None:
        raise RuntimeError("pgvector indisponível")

    async def add_content_async(self, **kwargs: object) -> None:
        raise RuntimeError("pgvector indisponível")


async def test_ingest_document_agno_falha_nao_derruba(
    fake_embeddings: FakeEmbeddingProvider,
) -> None:
    """O `VectorStore` é o caminho garantido; o Agno é a segunda cópia.

    Se a falha do Agno propagasse, o dono ficaria sem NENHUMA cópia do que
    mandou lembrar — inclusive a que já tinha sido calculada.
    """
    store = InMemoryVectorStore()

    relatorio = await _ingerir(
        TEXTO_LONGO,
        store=store,
        provider=fake_embeddings,
        agno_knowledge=_AgnoQuebrado(),
    )

    assert relatorio.outcome is IngestOutcome.INDEXED
    assert relatorio.chunks_indexed > 1
    assert len(await store.get_all(namespace="knowledge")) == relatorio.chunks_indexed


# --------------------------------------------------------------------------- #
# Regressão — `knowledge_save` passa pelo chunking
# --------------------------------------------------------------------------- #


async def test_knowledge_save_usa_chunking(
    tmp_path: Path,
    fake_embeddings: FakeEmbeddingProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O handler que gravava `f"{doc_id}#0"` e mais nada agora gera N vetores.

    O arquivo temático já existe com ~5 KB quando o fato novo chega — é
    exatamente o caso em que a versão antiga truncava tudo menos o começo.
    """
    from packages.agents.tools.executor import SystemToolExecutor

    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "estudos.md").write_text(TEXTO_LONGO, encoding="utf-8")
    monkeypatch.setenv("JARVIS_KNOWLEDGE_PATH", str(knowledge_dir))

    store = InMemoryVectorStore()
    executor = SystemToolExecutor(
        tavily_api_key="nao-usada",
        llm=fake_embeddings,
        chat_history_store=InMemoryVectorStore(),
        memory_vector_store=store,
        embed_llm=fake_embeddings,
    )

    resultado = await executor.execute(
        "knowledge_save",
        {"fato": "O usuário estuda lógica de programação.", "categoria": "estudos"},
    )

    assert resultado["sucesso"] is True
    assert resultado["categoria"] == "estudos"
    assert resultado["caminho"].endswith("estudos.md")

    gravados = await store.get_all(namespace="knowledge")
    assert len(gravados) > 1, "arquivo temático grande não pode virar um vetor só"
    assert resultado["chunks"] == len(gravados)
    assert all(r.metadata["categoria"] == "estudos" for r in gravados)
    assert all(r.metadata["kind"] == "fato" for r in gravados)
    # O fato novo entrou no disco e, portanto, no último chunk.
    assert "lógica de programação" in (knowledge_dir / "estudos.md").read_text(
        encoding="utf-8"
    )
