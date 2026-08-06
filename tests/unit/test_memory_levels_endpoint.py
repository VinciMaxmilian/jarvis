"""Aba Memory — os cinco níveis de `plan.md` §10 numa leitura só.

Até esta versão a aba desenhava apenas o grafo de vetores, ou seja `knowledge` e
`long`. `short`, `working` e `experience` gravavam em disco e alimentavam o
planejamento **sem nenhuma superfície de leitura**: quem olhasse a tela concluía
que a memória do sistema era um RAG.

O que estes testes fixam é o que a tela precisa poder afirmar:

1. os cinco níveis vêm sempre, na ordem do plano, mesmo os vazios — um nível que
   some quando está vazio é indistinguível de um nível que não existe;
2. cada nível lê a SUA fonte (Postgres, arquivo JSON, vector store);
3. **nível quebrado não derruba a aba** — é a mesma regra de
   `packages/memory/system.py`, e sem ela um Postgres fora do ar apagaria também
   o `experience`, que mora em disco e estava perfeitamente legível.

Sem rede, sem banco e sem modelo: a sessão é um dublê e o vector store é uma
lista.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from apps.api.routers import memory as rota
from packages.memory.models import (
    Attempt,
    AttemptOutcome,
    ExperienceKind,
    ExperienceRecord,
    IndexedDocument,
    WorkingMemoryState,
)
from packages.shared.contracts import utcnow
from packages.shared.ports import VectorRecord


class SessaoVazia:
    """`AsyncSession` que não devolve nenhuma mensagem — banco recém-criado."""

    class _Resultado:
        def scalar_one_or_none(self):
            return None

        def scalars(self):
            return iter(())

    async def execute(self, _stmt):
        return self._Resultado()

    async def get(self, _modelo, _pk):
        return None


class SessaoQuebrada:
    """Postgres fora do ar. Só o nível `short` depende dele."""

    async def execute(self, _stmt):
        raise RuntimeError("postgres fora do ar")

    async def get(self, _modelo, _pk):
        raise RuntimeError("postgres fora do ar")


class StoreFalso:
    """Só o `get_all()` importa aqui — é o único método que a rota chama."""

    def __init__(self, registros: list[VectorRecord]) -> None:
        self._registros = registros

    async def get_all(self) -> list[VectorRecord]:
        return list(self._registros)


def fato(texto: str, *, namespace: str = "long_term") -> VectorRecord:
    return VectorRecord(
        id=f"fact-{uuid4().hex[:8]}",
        namespace=namespace,
        text=texto,
        embedding=[0.1, 0.2, 0.3],
        metadata={"source": "dono", "updated_at": utcnow().isoformat()},
    )


@pytest.fixture
def memoria_em_disco(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Aponta `MEMORY_DATA_DIR` para um diretório do teste.

    A rota lê o ambiente na hora da chamada (e não guarda o caminho num módulo)
    justamente para que isto funcione sem recarregar o import.
    """
    monkeypatch.setenv("MEMORY_DATA_DIR", str(tmp_path))
    return tmp_path


async def chamar(sessao, store: StoreFalso, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setattr(rota, "get_memory_vector_store", lambda: store)
    resposta = await rota.get_memory_levels(sessao)
    return json.loads(resposta.body)


def por_id(payload: dict) -> dict[str, dict]:
    return {nivel["id"]: nivel for nivel in payload["levels"]}


@pytest.mark.asyncio
async def test_os_cinco_niveis_vem_sempre_e_na_ordem_do_plano(
    memoria_em_disco: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Memória inteiramente vazia ainda descreve os cinco níveis.

    É o caso do primeiro boot, e é justamente nele que a tela precisa ensinar o
    que cada nível guarda — uma lista vazia diria ao dono que a aba está quebrada.
    """
    payload = await chamar(SessaoVazia(), StoreFalso([]), monkeypatch)

    assert [n["id"] for n in payload["levels"]] == [
        "short",
        "working",
        "long",
        "knowledge",
        "experience",
    ]
    for nivel in payload["levels"]:
        assert nivel["count"] == 0
        assert nivel["items"] == []
        # Rótulo e vida útil são o conteúdo didático da aba: sem eles o card
        # vazio não diz nada.
        assert nivel["name"] and nivel["subtitle"] and nivel["lifetime"]


@pytest.mark.asyncio
async def test_long_e_knowledge_saem_do_vector_store_separados(
    memoria_em_disco: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Os dois níveis vetoriais moram no MESMO store, em namespaces diferentes.

    O grafo os desenha juntos; a lista precisa separá-los, senão a aba continua
    dizendo que a memória é "um RAG só".
    """
    store = StoreFalso([
        fato("o NAS é 192.168.11.20"),
        fato("o dono prefere resposta curta"),
        fato("chunk de documento", namespace="knowledge"),
    ])

    niveis = por_id(await chamar(SessaoVazia(), store, monkeypatch))

    assert niveis["long"]["count"] == 2
    assert {i["detail"] for i in niveis["long"]["items"]} == {
        "o NAS é 192.168.11.20",
        "o dono prefere resposta curta",
    }
    # `knowledge` conta chunk + documento do índice; aqui não há índice em disco.
    assert niveis["knowledge"]["count"] == 1


@pytest.mark.asyncio
async def test_working_mostra_a_task_viva_com_o_que_ja_foi_tentado(
    memoria_em_disco: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O nível existe para sobreviver a `kill -9`; a aba tem que mostrar isso."""
    estado = WorkingMemoryState(
        task_id=uuid4(),
        goal_id=uuid4(),
        title="sincronizar o NAS",
        plan=["montar share", "rsync"],
        attempts=[
            Attempt(number=1, outcome=AttemptOutcome.FAILED, error="standby"),
            Attempt(number=2, outcome=AttemptOutcome.STARTED),
        ],
        revision=7,
    )
    destino = memoria_em_disco / "working"
    destino.mkdir(parents=True)
    (destino / f"{estado.task_id}.json").write_text(
        estado.model_dump_json(), encoding="utf-8"
    )

    niveis = por_id(await chamar(SessaoVazia(), StoreFalso([]), monkeypatch))
    item = niveis["working"]["items"][0]

    assert niveis["working"]["count"] == 1
    assert item["title"] == "sincronizar o NAS"
    assert item["badge"] == "rev 7"
    assert "1 falha(s)" in item["detail"]
    # A tentativa aberta sem par é a que o processo morrendo deixou: distingui-la
    # de uma falha é o ponto do nível.
    assert "interrompida" in item["detail"]


@pytest.mark.asyncio
async def test_experience_ordena_por_recorrencia_e_marca_o_que_virou_padrao(
    memoria_em_disco: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uma falha é acidente, a repetida é padrão — e só o padrão entra no prompt.

    Sem a marca, a lista pareceria um log de erros e o dono não teria como saber
    o que o planejador está de fato lendo.
    """
    acidente = ExperienceRecord(
        id="capability_failure:nas_sync:aaa",
        kind=ExperienceKind.CAPABILITY_FAILURE,
        subject="nas_sync",
        lesson="a capability 'nas_sync' falhou 1x com: timeout",
        occurrences=1,
    )
    padrao = ExperienceRecord(
        id="capability_failure:backup:bbb",
        kind=ExperienceKind.CAPABILITY_FAILURE,
        subject="backup",
        lesson="a capability 'backup' falhou 4x com: standby",
        occurrences=4,
    )
    (memoria_em_disco / "experience.json").write_text(
        json.dumps([r.model_dump(mode="json") for r in (acidente, padrao)]),
        encoding="utf-8",
    )

    niveis = por_id(await chamar(SessaoVazia(), StoreFalso([]), monkeypatch))
    itens = niveis["experience"]["items"]

    assert niveis["experience"]["count"] == 2
    assert [i["title"] for i in itens] == ["backup", "nas_sync"]
    assert itens[0]["promoted"] is True
    assert itens[1]["promoted"] is False


@pytest.mark.asyncio
async def test_knowledge_soma_documentos_do_indice_aos_chunks(
    memoria_em_disco: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Documento no índice sem chunk no store é o sintoma que vale ver na tela."""
    doc = IndexedDocument(
        doc_id="manual.md",
        source="/app/data/knowledge/manual.md",
        content_hash="abc",
        chunk_ids=["c1", "c2"],
    )
    (memoria_em_disco / "knowledge_index.json").write_text(
        json.dumps([doc.model_dump(mode="json")]), encoding="utf-8"
    )

    store = StoreFalso([fato("trecho do manual", namespace="knowledge")])
    niveis = por_id(await chamar(SessaoVazia(), store, monkeypatch))

    assert niveis["knowledge"]["count"] == 2  # 1 documento + 1 chunk
    assert niveis["knowledge"]["items"][0]["title"].endswith("manual.md")
    assert "2 chunk(s)" in niveis["knowledge"]["items"][0]["detail"]


@pytest.mark.asyncio
async def test_postgres_fora_do_ar_nao_apaga_os_niveis_que_estao_em_disco(
    memoria_em_disco: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Só `short` degrada; `experience` está no disco e continua legível."""
    registro = ExperienceRecord(
        id="owner_preference:tom:ccc",
        kind=ExperienceKind.OWNER_PREFERENCE,
        subject="tom",
        lesson="o dono prefere resposta curta",
        occurrences=3,
    )
    (memoria_em_disco / "experience.json").write_text(
        json.dumps([registro.model_dump(mode="json")]), encoding="utf-8"
    )

    niveis = por_id(await chamar(SessaoQuebrada(), StoreFalso([]), monkeypatch))

    assert "postgres fora do ar" in niveis["short"]["error"]
    assert niveis["experience"]["count"] == 1
    assert "error" not in niveis["experience"]


@pytest.mark.asyncio
async def test_vector_store_quebrado_degrada_long_e_knowledge_juntos(
    memoria_em_disco: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Os dois níveis compartilham o store: se ele cai, os dois caem — e só eles."""

    class StoreQuebrado:
        async def get_all(self):
            raise RuntimeError("índice corrompido")

    monkeypatch.setattr(rota, "get_memory_vector_store", lambda: StoreQuebrado())
    payload = json.loads((await rota.get_memory_levels(SessaoVazia())).body)
    niveis = por_id(payload)

    assert "índice corrompido" in niveis["long"]["error"]
    assert "índice corrompido" in niveis["knowledge"]["error"]
    assert "error" not in niveis["working"]
    assert "error" not in niveis["experience"]
