"""Nível `knowledge` — aceite 2 da v1.3 (`plan-execution.md` §3).

> "Documento novo em `knowledge` é recuperável por busca semântica."

O aceite é sobre **recuperação**, não sobre ingestão: gravar um documento e
contar chunks provaria só que o laço rodou. O que precisa ser verdade é que uma
consulta escrita com outras palavras — a pergunta que o dono faria — traga de
volta o documento certo, e não um dos outros que já estavam no índice.

**Sem rede, e sem fingir que há.** Não há modelo de inferência nesta máquina. O
embedding vem da porta `LLMProvider.embed()`, injetada, e o dublê
`FakeEmbeddingProvider` (em `tests/conftest.py`) devolve um saco de palavras com
hashing: sobreposição de vocabulário vira proximidade de cosseno. É a propriedade
mínima de um embedding real e a única de que este aceite precisa — e, sendo
SHA-256 por token, o ranking é idêntico em qualquer máquina.

A segunda metade do arquivo cobre o que dá sentido a "RAG **incremental**":
reingerir conteúdo inalterado custa **zero** chamada de embedding, e conteúdo
alterado remove os chunks velhos antes de gravar os novos.
"""

from __future__ import annotations

import pytest

from packages.memory.knowledge import (
    DEFAULT_NAMESPACE,
    KnowledgeBase,
    chunk_id,
    chunk_text,
    render_knowledge_context,
)
from packages.memory.long_term import LongTermMemory
from packages.memory.models import IngestOutcome, KnowledgeDocument, content_hash
from packages.memory.stores import InMemoryKnowledgeIndex
from packages.memory.vector_store import InMemoryVectorStore
from packages.shared.contracts import EventType
from tests.conftest import FakeEmbeddingProvider, InMemoryEventBus

# --------------------------------------------------------------------------- #
# Corpus
# --------------------------------------------------------------------------- #
#
# Vocabulários deliberadamente disjuntos: se todos os documentos falassem do
# mesmo assunto, o acerto da busca seria sorte, não recuperação.

NAS = KnowledgeDocument(
    source="infra/nas.md",
    title="NAS de casa",
    text=(
        "O NAS Synology entra em standby depois de trinta minutos ocioso. "
        "Acordar o NAS por wake-on-lan antes de qualquer rotina de backup, "
        "senão a montagem do share falha."
    ),
)
CAFETEIRA = KnowledgeDocument(
    source="casa/cafeteira.md",
    title="Cafeteira",
    text=(
        "A cafeteira expresso trabalha a nove bares de pressão. "
        "O moedor fica na posição doze para o grão do sítio."
    ),
)
CLUSTER = KnowledgeDocument(
    source="trabalho/cluster.md",
    title="Cluster de homologação",
    text=(
        "O cluster de homologação roda três nós. "
        "O ingress termina TLS no balanceador e o certificado renova sozinho."
    ),
)
PIANO = KnowledgeDocument(
    source="casa/piano.md",
    title="Piano",
    text=(
        "O piano de armário precisa de afinação a cada seis meses. "
        "O afinador prefere agendar pela manhã e cobra por visita."
    ),
)


def make_base(
    provider: FakeEmbeddingProvider,
    *,
    store: InMemoryVectorStore | None = None,
    event_bus: InMemoryEventBus | None = None,
    chunk_size: int = 800,
) -> tuple[KnowledgeBase, InMemoryVectorStore]:
    loja = store or InMemoryVectorStore()
    base = KnowledgeBase(
        provider,
        loja,
        InMemoryKnowledgeIndex(),
        chunk_size=chunk_size,
        chunk_overlap=min(120, chunk_size // 4),
        event_bus=event_bus,
    )
    return base, loja


# --------------------------------------------------------------------------- #
# Aceite 2 — documento novo é recuperável por busca semântica
# --------------------------------------------------------------------------- #


async def test_documento_novo_e_recuperavel_por_busca_semantica(
    fake_embeddings: FakeEmbeddingProvider,
) -> None:
    """ACEITE v1.3 (2): ingerir um documento novo e achá-lo por uma pergunta.

    A consulta não repete o texto do documento: ela é escrita como o dono
    perguntaria. Recuperar por igualdade de string seria `grep`, não RAG.
    """
    base, _ = make_base(fake_embeddings)
    for documento in (NAS, CAFETEIRA, CLUSTER):
        await base.ingest(documento)

    consulta = "afinação do piano de armário"
    antes = await base.search(consulta)
    assert PIANO.doc_id not in [c.doc_id for c in antes], "o corpus já continha o piano"

    resultado = await base.ingest(PIANO)
    achados = await base.search(consulta)

    assert resultado.outcome is IngestOutcome.INDEXED, "o documento não era novo"
    assert achados, "a busca não devolveu nada"
    assert achados[0].doc_id == "casa/piano.md", (
        f"o vizinho mais próximo foi {achados[0].doc_id}, não o documento novo"
    )
    assert achados[0].score > achados[1].score, "o ranking empatou — não houve escolha"
    # Proveniência junto: sem ela o RAG vira citação sem referência.
    assert achados[0].source == "casa/piano.md"
    assert achados[0].title == "Piano"
    assert "afinação" in achados[0].text


async def test_busca_traz_o_documento_do_assunto_perguntado(
    fake_embeddings: FakeEmbeddingProvider,
) -> None:
    """Duas perguntas, dois assuntos, dois documentos — o índice discrimina."""
    base, _ = make_base(fake_embeddings)
    for documento in (NAS, CAFETEIRA, CLUSTER, PIANO):
        await base.ingest(documento)

    nas = await base.search("o NAS entra em standby antes do backup", limit=1)
    cafe = await base.search("qual a pressão em bares da cafeteira expresso", limit=1)

    assert nas[0].doc_id == "infra/nas.md"
    assert cafe[0].doc_id == "casa/cafeteira.md"


async def test_documento_longo_e_recuperado_pelo_trecho_certo(
    fake_embeddings: FakeEmbeddingProvider,
) -> None:
    """Chunking existe para isto: a resposta é o trecho, não o arquivo inteiro."""
    texto = (
        "Capítulo um. O disjuntor geral do quadro fica atrás da porta da cozinha "
        "e desarma quando o chuveiro e o forno ligam juntos. "
    ) + (
        "Capítulo dois. A caixa d'água tem mil litros e a boia foi trocada em "
        "janeiro; o registro de manutenção fica na garagem."
    )
    base, _ = make_base(fake_embeddings, chunk_size=140)
    await base.ingest(KnowledgeDocument(source="casa/manual.md", text=texto))

    achados = await base.search("quantos litros tem a caixa d'água", limit=1)

    assert achados[0].doc_id == "casa/manual.md"
    assert "mil litros" in achados[0].text
    assert achados[0].chunk_index > 0, "o trecho certo era o segundo, não o primeiro"


async def test_consulta_vazia_nao_gasta_embedding(
    fake_embeddings: FakeEmbeddingProvider,
) -> None:
    base, _ = make_base(fake_embeddings)
    await base.ingest(PIANO)
    chamadas = fake_embeddings.embed_calls

    assert await base.search("   ") == []
    assert fake_embeddings.embed_calls == chamadas


# --------------------------------------------------------------------------- #
# Incremental — o que faz a reindexação valer a pena
# --------------------------------------------------------------------------- #


async def test_reingerir_igual_custa_zero_embedding(
    fake_embeddings: FakeEmbeddingProvider,
) -> None:
    """"Incremental" é isto e nada mais: conteúdo igual, trabalho nenhum."""
    base, loja = make_base(fake_embeddings)
    await base.ingest(NAS)
    vetorizados = fake_embeddings.embedded_count

    resultado = await base.ingest(NAS)

    assert resultado.outcome is IngestOutcome.UNCHANGED
    assert resultado.touched is False
    assert fake_embeddings.embedded_count == vetorizados, "recalculou embedding à toa"
    assert len(loja) == 1


async def test_espaco_em_branco_diferente_ainda_e_o_mesmo_conteudo(
    fake_embeddings: FakeEmbeddingProvider,
) -> None:
    """Reformatar um arquivo não pode custar uma rodada inteira de embeddings."""
    base, _ = make_base(fake_embeddings)
    await base.ingest(NAS)
    vetorizados = fake_embeddings.embedded_count

    reformatado = NAS.model_copy(update={"text": NAS.text.replace(" ", "\n  ")})
    resultado = await base.ingest(reformatado)

    assert resultado.outcome is IngestOutcome.UNCHANGED
    assert fake_embeddings.embedded_count == vetorizados


async def test_conteudo_alterado_apaga_os_chunks_velhos(
    fake_embeddings: FakeEmbeddingProvider,
) -> None:
    """Sem remoção, a base guardaria duas versões e a busca devolveria a antiga."""
    longo = " ".join(f"parágrafo {i} sobre a rotina antiga de backup." for i in range(30))
    base, loja = make_base(fake_embeddings, chunk_size=120)
    primeiro = await base.ingest(KnowledgeDocument(source="infra/rotina.md", text=longo))
    assert primeiro.chunks_indexed > 3

    segundo = await base.ingest(
        KnowledgeDocument(source="infra/rotina.md", text="a rotina agora é diária.")
    )

    assert segundo.outcome is IngestOutcome.UPDATED
    assert segundo.chunks_indexed == 1
    assert segundo.chunks_removed == primeiro.chunks_indexed - 1
    assert len(loja) == 1, f"chunks órfãos ficaram no índice: {loja.ids()}"
    achados = await base.search("rotina antiga de backup")
    assert all("parágrafo" not in c.text for c in achados), "a versão velha voltou"


async def test_forget_tira_o_documento_da_busca(
    fake_embeddings: FakeEmbeddingProvider,
) -> None:
    """`plan.md` §10: permanente **até a fonte sumir**."""
    base, loja = make_base(fake_embeddings)
    await base.ingest(NAS)
    await base.ingest(PIANO)

    removidos = await base.forget("infra/nas.md")

    assert removidos == 1
    assert len(loja) == 1
    achados = await base.search("o NAS entra em standby antes do backup")
    assert all(c.doc_id != "infra/nas.md" for c in achados)


async def test_forget_de_documento_inexistente_e_zero(
    fake_embeddings: FakeEmbeddingProvider,
) -> None:
    base, _ = make_base(fake_embeddings)

    assert await base.forget("nunca/existiu.md") == 0


async def test_ingest_many_devolve_um_resultado_por_documento(
    fake_embeddings: FakeEmbeddingProvider,
) -> None:
    """É o que o job `reindex_knowledge` da v1.4 chama."""
    base, _ = make_base(fake_embeddings)
    await base.ingest(NAS)

    resultados = await base.ingest_many([NAS, PIANO, CAFETEIRA])

    assert [r.outcome for r in resultados] == [
        IngestOutcome.UNCHANGED,
        IngestOutcome.INDEXED,
        IngestOutcome.INDEXED,
    ]


async def test_documento_vazio_e_recusado(fake_embeddings: FakeEmbeddingProvider) -> None:
    """Ingerir vazio deixaria o índice mentindo sobre a cobertura."""
    base, _ = make_base(fake_embeddings)

    with pytest.raises(ValueError, match="não tem texto"):
        await base.ingest(KnowledgeDocument(source="vazio.md", text="   \n  "))


async def test_ingestao_publica_memory_updated(
    fake_embeddings: FakeEmbeddingProvider, event_bus: InMemoryEventBus
) -> None:
    base, _ = make_base(fake_embeddings, event_bus=event_bus)

    await base.ingest(PIANO)
    await base.ingest(PIANO)  # unchanged: não publica

    eventos = event_bus.of_type(EventType.MEMORY_UPDATED)
    assert len(eventos) == 1
    assert eventos[0].payload["level"] == "knowledge"
    assert eventos[0].payload["subject"] == "casa/piano.md"
    assert eventos[0].payload["detail"] == "indexed"


# --------------------------------------------------------------------------- #
# Namespace — `knowledge` e `long` dividem a mesma loja
# --------------------------------------------------------------------------- #


async def test_knowledge_e_long_term_nao_se_misturam(
    fake_embeddings: FakeEmbeddingProvider,
) -> None:
    """Uma loja, dois níveis: o namespace é o que os mantém separados."""
    loja = InMemoryVectorStore()
    base, _ = make_base(fake_embeddings, store=loja)
    fatos = LongTermMemory(fake_embeddings, loja)

    await base.ingest(PIANO)
    await fatos.store_fact(
        "o piano de armário da sala é um Essenfelder", fact_id="fato-piano"
    )

    do_conhecimento = await base.search("afinação do piano de armário")
    dos_fatos = await fatos.search("qual é a marca do piano de armário")

    assert [c.doc_id for c in do_conhecimento] == ["casa/piano.md"]
    assert [c.doc_id for c in dos_fatos] == ["fato-piano"]


async def test_fato_editado_substitui_em_vez_de_acumular(
    fake_embeddings: FakeEmbeddingProvider,
) -> None:
    """`plan.md` §10: o nível `long` é **editável**, e id estável é o que permite."""
    loja = InMemoryVectorStore()
    fatos = LongTermMemory(fake_embeddings, loja)

    await fatos.store_fact("o NAS responde em 192.168.11.20", fact_id="fato-nas")
    await fatos.store_fact("o NAS responde em 192.168.1.20", fact_id="fato-nas")

    achados = await fatos.search("qual o endereço do NAS")
    assert len(loja) == 1
    assert achados[0].text == "o NAS responde em 192.168.1.20"
    assert await fatos.forget("fato-nas") is True


async def test_fato_vazio_e_recusado(fake_embeddings: FakeEmbeddingProvider) -> None:
    fatos = LongTermMemory(fake_embeddings, InMemoryVectorStore())

    with pytest.raises(ValueError, match="fato vazio"):
        await fatos.store_fact("   ")


# --------------------------------------------------------------------------- #
# Chunking e hash
# --------------------------------------------------------------------------- #


def test_chunk_text_e_deterministico() -> None:
    """Ids estáveis dependem disto: chunk diferente a cada passada duplicaria tudo."""
    texto = " ".join(f"palavra{i}" for i in range(300))

    assert chunk_text(texto, size=100, overlap=20) == chunk_text(
        texto, size=100, overlap=20
    )


def test_chunk_text_respeita_o_tamanho_e_nao_perde_texto() -> None:
    texto = " ".join(f"palavra{i}" for i in range(300))

    pedacos = chunk_text(texto, size=100, overlap=20)

    assert len(pedacos) > 1
    assert all(len(p) <= 100 for p in pedacos)
    assert pedacos[0].startswith("palavra0")
    assert texto.endswith(pedacos[-1])


def test_chunk_text_de_texto_curto_e_um_pedaco_so() -> None:
    assert chunk_text("uma linha só") == ["uma linha só"]


def test_chunk_text_de_texto_vazio_e_lista_vazia() -> None:
    assert chunk_text("   \n\t  ") == []


def test_chunk_text_sem_espaco_nenhum_termina() -> None:
    """Texto sem espaço não pode entrar em laço no recuo até o último espaço."""
    pedacos = chunk_text("x" * 500, size=100, overlap=20)

    # Passo = size - overlap = 80, começando em 0: 0, 80, 160, 240, 320, 400.
    # `ceil((500 - 100) / 80) + 1` = 6. Concatenar os pedaços NÃO devolve o
    # original — devolve 600 caracteres, porque cada um repete os 20 do anterior.
    # Recompor exige descartar a sobreposição, e é justamente essa conta que
    # prova que nenhum caractere se perdeu entre um corte e o seguinte.
    assert len(pedacos) == 6
    assert all(len(p) <= 100 for p in pedacos)
    recomposto = pedacos[0] + "".join(p[20:] for p in pedacos[1:])
    assert recomposto == "x" * 500


@pytest.mark.parametrize(
    ("size", "overlap"), [(0, 0), (-1, 0), (100, 100), (100, 200), (100, -1)]
)
def test_chunk_text_recusa_parametro_invalido(size: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        chunk_text("texto qualquer", size=size, overlap=overlap)


def test_chunk_id_e_estavel() -> None:
    assert chunk_id("infra/nas.md", 3) == "infra/nas.md#3"


def test_content_hash_ignora_espaco_em_branco() -> None:
    assert content_hash("a  b\n c") == content_hash("a b c")
    assert content_hash("a b c") != content_hash("a b d")


def test_doc_id_default_e_a_fonte() -> None:
    """Id legível no log; `doc_id` explícito continua ganhando."""
    assert KnowledgeDocument(source="infra/nas.md", text="x").doc_id == "infra/nas.md"
    assert (
        KnowledgeDocument(source="infra/nas.md", text="x", doc_id="nas").doc_id == "nas"
    )


def test_namespace_default_do_knowledge() -> None:
    assert DEFAULT_NAMESPACE == "knowledge"


# --------------------------------------------------------------------------- #
# Renderização para o prompt
# --------------------------------------------------------------------------- #


async def test_contexto_do_knowledge_cita_a_fonte(
    fake_embeddings: FakeEmbeddingProvider,
) -> None:
    base, _ = make_base(fake_embeddings)
    await base.ingest(PIANO)

    texto = render_knowledge_context(await base.search("afinação do piano"))

    assert "casa/piano.md" in texto
    assert "afinação" in texto


def test_contexto_vazio_para_busca_sem_resultado() -> None:
    assert render_knowledge_context([]) == ""
