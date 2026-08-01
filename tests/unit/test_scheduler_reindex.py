"""`ReindexService` — a parte de "reindexação incremental" que é incremental.

O valor do job está em **não** reindexar: vetorizar o corpus inteiro toda
madrugada é o custo que a palavra "incremental" existe para evitar. Por isso os
testes centrais são `unchanged`, e não `added`.

Nada aqui depende de inferência: o diff é SHA-256 de conteúdo, e o índice é o
dublê em memória. Vetorizar é responsabilidade do adaptador atrás da porta.
"""

from __future__ import annotations

import os
from pathlib import Path

from packages.scheduler.reindex import InMemoryKnowledgeIndex, ReindexService


def escrever(raiz: Path, nome: str, texto: str) -> Path:
    arquivo = raiz / nome
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(texto, encoding="utf-8")
    return arquivo


def make_service(corpus: Path, indice: InMemoryKnowledgeIndex) -> ReindexService:
    return ReindexService(source_dir=corpus, index=indice)


async def test_primeira_passada_indexa_tudo(tmp_path: Path) -> None:
    escrever(tmp_path, "a.md", "alfa")
    escrever(tmp_path, "sub/b.txt", "beta")
    indice = InMemoryKnowledgeIndex()

    resultado = await make_service(tmp_path, indice).run()

    assert (resultado.scanned, resultado.added, resultado.unchanged) == (2, 2, 0)
    assert sorted(indice.texts) == ["a.md", "sub/b.txt"]


async def test_segunda_passada_sem_mudanca_nao_toca_em_nada(tmp_path: Path) -> None:
    escrever(tmp_path, "a.md", "alfa")
    indice = InMemoryKnowledgeIndex()
    servico = make_service(tmp_path, indice)

    await servico.run()
    resultado = await servico.run()

    assert resultado.unchanged == 1
    assert resultado.changed == 0


async def test_mtime_novo_com_conteudo_igual_nao_reindexa(tmp_path: Path) -> None:
    """`git checkout`, `cp -p` e o próprio restore mexem em mtime sem mudar byte.
    Decidir por mtime faria cada um deles disparar uma vetorização completa."""
    arquivo = escrever(tmp_path, "a.md", "alfa")
    indice = InMemoryKnowledgeIndex()
    servico = make_service(tmp_path, indice)
    await servico.run()

    futuro = arquivo.stat().st_mtime + 86400
    os.utime(arquivo, (futuro, futuro))

    resultado = await servico.run()

    assert resultado.changed == 0
    assert resultado.unchanged == 1


async def test_conteudo_alterado_e_reindexado(tmp_path: Path) -> None:
    escrever(tmp_path, "a.md", "alfa")
    indice = InMemoryKnowledgeIndex()
    servico = make_service(tmp_path, indice)
    await servico.run()

    escrever(tmp_path, "a.md", "alfa revisado")
    resultado = await servico.run()

    assert (resultado.added, resultado.updated, resultado.removed) == (0, 1, 0)
    assert indice.texts["a.md"] == "alfa revisado"


async def test_documento_apagado_sai_do_indice(tmp_path: Path) -> None:
    escrever(tmp_path, "a.md", "alfa")
    escrever(tmp_path, "b.md", "beta")
    indice = InMemoryKnowledgeIndex()
    servico = make_service(tmp_path, indice)
    await servico.run()

    (tmp_path / "b.md").unlink()
    resultado = await servico.run()

    assert resultado.removed == 1
    assert sorted(indice.texts) == ["a.md"]


async def test_mistura_de_novo_alterado_e_removido(tmp_path: Path) -> None:
    escrever(tmp_path, "fica.md", "igual")
    escrever(tmp_path, "muda.md", "antes")
    escrever(tmp_path, "some.md", "efêmero")
    indice = InMemoryKnowledgeIndex()
    servico = make_service(tmp_path, indice)
    await servico.run()

    escrever(tmp_path, "muda.md", "depois")
    escrever(tmp_path, "novo.md", "recém-chegado")
    (tmp_path / "some.md").unlink()

    resultado = await servico.run()

    assert resultado.scanned == 3
    assert resultado.added == 1
    assert resultado.updated == 1
    assert resultado.removed == 1
    assert resultado.unchanged == 1


async def test_binario_e_arquivo_gigante_ficam_de_fora(tmp_path: Path) -> None:
    """PDF vira conhecimento depois de extraído — trabalho de capability, não de
    scheduler (`plan-execution.md` §2b.6)."""
    escrever(tmp_path, "doc.md", "texto")
    (tmp_path / "manual.pdf").write_bytes(b"%PDF-1.7")
    escrever(tmp_path, "enorme.md", "x" * 500)

    indice = InMemoryKnowledgeIndex()
    resultado = await ReindexService(
        source_dir=tmp_path, index=indice, max_bytes=100
    ).run()

    assert resultado.scanned == 1
    assert sorted(indice.texts) == ["doc.md"]


async def test_sem_indice_o_job_diz_por_que_pulou(tmp_path: Path) -> None:
    """Pular em silêncio seria o D-11 de volta: log de 'concluído' sem trabalho."""
    resultado = await ReindexService(source_dir=tmp_path, index=None).run()

    assert resultado.skipped_reason
    assert "KnowledgeIndex" in resultado.skipped_reason
    assert resultado.scanned == 0


async def test_corpus_inexistente_diz_o_caminho(tmp_path: Path) -> None:
    ausente = tmp_path / "knowledge"
    resultado = await ReindexService(
        source_dir=ausente, index=InMemoryKnowledgeIndex()
    ).run()

    assert str(ausente) in resultado.skipped_reason


async def test_doc_id_e_o_caminho_relativo_em_posix(tmp_path: Path) -> None:
    """Estável entre Windows e Linux: o mesmo corpus indexado nas duas máquinas
    não pode produzir dois documentos para o mesmo arquivo."""
    escrever(tmp_path, "nivel1/nivel2/nota.md", "conteúdo")
    indice = InMemoryKnowledgeIndex()

    await make_service(tmp_path, indice).run()

    assert list(indice.texts) == ["nivel1/nivel2/nota.md"]
