"""Rota de memória — grafo dos vetores RAG e leitura dos cinco níveis."""

from __future__ import annotations

import hashlib
import json
import math
import os
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path

from apps.api.deps import get_chat_history_store, get_db, get_memory_vector_store
from packages.memory.vector_store import cosine_similarity
from packages.memory.graphify_store import GraphifyVectorStore
from packages.shared.ports import VectorStore

router = APIRouter()

# Template HTML base, idêntico ao do graphify, mas adaptado
HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Jarvis Vector Memory</title>
    <script type="text/javascript" src="https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js"></script>
    <style type="text/css">
        html, body {
            width: 100%;
            height: 100%;
            margin: 0;
            padding: 0;
            background-color: transparent;
            color: #fff;
            font-family: sans-serif;
            overflow: hidden;
            color-scheme: light dark;
        }
        #mynetwork {
            width: 100%;
            height: 100%;
            position: absolute;
            top: 0;
            left: 0;
        }
    </style>
</head>
<body>
<div id="mynetwork"></div>
<script type="text/javascript">
    var nodes = new vis.DataSet({nodes});
    var edges = new vis.DataSet({edges});

    var container = document.getElementById('mynetwork');
    var data = {
        nodes: nodes,
        edges: edges
    };
    var options = {
        nodes: {
            shape: 'dot',
            size: 16,
            font: {
                color: '#fff',
                size: 14,
                face: 'sans-serif',
                strokeWidth: 2,
                strokeColor: '#000'
            },
            borderWidth: 2
        },
        edges: {
            width: 1,
            color: { inherit: 'both', opacity: 0.5 },
            smooth: { type: 'continuous' }
        },
        physics: {
            forceAtlas2Based: {
                gravitationalConstant: -50,
                centralGravity: 0.01,
                springLength: 100,
                springConstant: 0.08
            },
            maxVelocity: 50,
            solver: 'forceAtlas2Based',
            timestep: 0.35,
            stabilization: { iterations: 150 }
        },
        interaction: {
            hover: true,
            tooltipDelay: 200
        }
    };
    var network = new vis.Network(container, data, options);
</script>
</body>
</html>
"""

def generate_graph_html(records) -> str:
    # 1. Montar nós
    nodes_data = []
    
    # Cores por namespace
    colors = {
        "knowledge": "#4CAF50", # Verde
        "long_term": "#2196F3", # Azul
        "default": "#FFC107"    # Amarelo
    }

    if not records:
        nodes_data.append({
            "id": "empty",
            "label": "Sem Memórias",
            "title": "Jarvis ainda não gravou nenhuma memória.",
            "color": "#63b3ed",
            "group": "empty"
        })
    else:
        for record in records:
            if record.namespace == "knowledge":
                color = "#4E79A7" # Azul suave
            elif record.namespace == "long_term":
                color = "#F28E2B" # Laranja
            else:
                color = "#59A14F" # Verde

            content = record.text[:200] + "..." if len(record.text) > 200 else record.text
            
            nodes_data.append({
                "id": record.id,
                "label": f"[{record.namespace}]",
                "title": content.replace("\n", "<br>"),
                "color": color,
                "group": record.namespace
            })

    # 2. Montar arestas (similaridade > 0.70)
    edges_data = []
    
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            sim = cosine_similarity(records[i].embedding, records[j].embedding)
            if sim > 0.70:
                edges_data.append({
                    "from": records[i].id,
                    "to": records[j].id,
                    "value": sim, # Areta mais grossa para similaridade maior
                    "title": f"Sim: {sim:.2f}"
                })

    html = HTML_TEMPLATE.replace(
        "{nodes}", json.dumps(nodes_data)
    ).replace(
        "{edges}", json.dumps(edges_data)
    )
    
    return html


@router.get("/memory.html")
async def get_memory_html(
    store: VectorStore = Depends(get_memory_vector_store)
):
    """Retorna o HTML com o grafo do VectorStore num JSON para driblar o Cloudflare."""
    records = await store.get_all()
    html_content = generate_graph_html(records)
    return JSONResponse(content={"html": html_content})

# --- Grafo no formato NeuralMap (mesmo motor da aba Brain) -------------------

# Nomes amigáveis por namespace; qualquer outro vira Title Case automático.
_NOMES_LOBO = {
    "knowledge": "Knowledge",
    "long_term": "Long Term",
    "chat_history": "Chat History",
    "default": "Core",
}

# Abaixo disso a aresta vira ruído: com embeddings densos quase tudo passa de 0.5.
_SIM_MINIMA = 0.70
# Acima disso a aresta é sólida; entre os dois o Engine desenha tracejado
# (confidence === "INFERRED"), que é como o grafo de código marca relação fraca.
_SIM_FORTE = 0.82
# Sem teto por nó um corpus homogêneo vira bola de pelo — cada nó fica só com
# seus vizinhos mais próximos.
_MAX_ARESTAS_POR_NO = 6


def _lobos_da_memoria(namespaces: list[str]) -> list[dict[str, Any]]:
    """Distribui um lobo por namespace num anel — o Engine posiciona os nós
    ao redor do lobo cujo `p` casa com o `source_file`."""
    total = max(1, len(namespaces))
    raio = 0 if total == 1 else 420 + 90 * total
    lobos = []
    for i, ns in enumerate(namespaces):
        ang = 2 * math.pi * i / total
        lobos.append({
            "p": ns,
            "x": round(math.cos(ang) * raio),
            "y": 0,
            "z": round(math.sin(ang) * raio),
            "n": _NOMES_LOBO.get(ns, ns.replace("_", " ").title()),
        })
    return lobos


def _rotulo(texto: str, limite: int = 48) -> str:
    limpo = " ".join(texto.split())
    return limpo[:limite] + "…" if len(limpo) > limite else limpo or "(vazio)"


@router.get("/version")
async def get_memory_version() -> dict[str, Any]:
    """Assinatura barata do estado da memória, para a UI saber quando refazer o grafo.

    **Por que polling e não push.** Gravar na memória acontece em vários pontos
    (`knowledge_save`, o indexador de conversa, a ingestão de documentos) e alguns
    são fire-and-forget fora do ciclo de requisição. Fazer cada um deles publicar
    um evento até o navegador exigiria acoplar todos a um canal de UI — muita
    superfície nova para um sistema de um usuário só. Uma assinatura que a UI
    compara resolve igual, sem tocar em nenhum caminho de escrita.

    **Por que não devolver o grafo inteiro.** É esse o ponto: o grafo é caro de
    montar (vizinhança por similaridade entre todos os nós) e a UI só precisa
    saber SE mudou. Isto aqui lê os registros e devolve dois números.

    **Por que hash do conteúdo e não `updated_at`.** A primeira versão disto usava
    o timestamp mais recente do metadata — e ele voltava VAZIO, porque os
    registros desta memória não guardam timestamp. A assinatura teria degradado
    para a contagem sozinha, que não detecta edição: corrigir um fato mantém o
    total e mudaria o grafo sem a UI perceber. O hash sobre (id, texto) pega
    inclusão, remoção E edição, e não depende de um campo que pode não existir.

    `blake2b` com digest curto: não é hash criptográfico aqui, é detector de
    mudança, e 16 hex já tornam colisão irrelevante nesta escala.
    """
    # A MESMA fonte do grafo, de propósito: se a assinatura cobrisse menos do que
    # o desenho, gravar no histórico não dispararia o refetch e a aba mostraria
    # um retrato velho sem avisar.
    records = await _registros_da_memoria()

    h = hashlib.blake2b(digest_size=8)
    # Ordenado por id: a ordem de `get_all()` não é contratual, e uma assinatura
    # que muda só porque o store devolveu na outra ordem faria a UI refazer o
    # grafo caro à toa, em looping.
    for r in sorted(records, key=lambda x: str(x.id)):
        h.update(str(r.id).encode())
        h.update(b"\x00")
        h.update((r.text or "").encode())
        h.update(b"\x00")

    return {"count": len(records), "hash": h.hexdigest()}


# Teto de nós no grafo. O cálculo de arestas é O(n²) em similaridade de cossenos,
# e o `chat_history` cresce a cada mensagem — sem teto, a aba que hoje monta em
# milissegundos viraria segundos de CPU dentro de um ano de uso, num i5-3470.
# Quando estourar, o corte é no histórico: `knowledge` é curado e pequeno, o
# histórico é volumoso e o mais antigo é o menos interessante.
_MAX_NOS_GRAFO = 400


async def _registros_da_memoria() -> list[Any]:
    """Todos os níveis que a aba Memory desenha, num só conjunto.

    Até esta versão só o store `memory` entrava, e a aba mostrava três fatos
    enquanto 39 registros de histórico ficavam invisíveis. Os dois são memória do
    mesmo sistema e o grafo já sabia desenhá-los — `_NOMES_LOBO` mapeia
    `chat_history` e `long_term` desde sempre, e `_lobos_da_memoria` cria um lobo
    por namespace. Faltava só entregar os dados.

    O nível `long` não aparece aqui como fonte separada de propósito: ele é um
    NAMESPACE do mesmo store `memory` (ver packages/memory/long_term.py), então
    entra sozinho assim que alguém gravar nele — hoje está vazio porque nada
    escreve ali ainda.
    """
    principais = await get_memory_vector_store().get_all()
    historico = await get_chat_history_store().get_all()

    # O corte cai no histórico, e sobra espaço para o `knowledge` inteiro.
    espaco = max(0, _MAX_NOS_GRAFO - len(principais))
    return [*principais, *historico[:espaco]]


@router.get("/graph.json")
async def get_memory_graph_json():
    """Retorna o grafo JSON no formato NeuralMap (nós + links + lobos)."""
    records = await _registros_da_memoria()

    namespaces = sorted({r.namespace for r in records}) or ["default"]
    indice_ns = {ns: i for i, ns in enumerate(namespaces)}

    nodes = [
        {
            "id": r.id,
            "label": _rotulo(r.text),
            "source_file": r.namespace,
            "file_type": r.namespace,
            "community": indice_ns.get(r.namespace, 0),
            "community_name": _NOMES_LOBO.get(r.namespace, r.namespace),
        }
        for r in records
    ]

    # Similaridade par a par → top-K por nó. União dos top-K (não interseção):
    # um nó periférico continua ligado ao seu único vizinho relevante.
    vizinhos: dict[int, list[tuple[float, int]]] = {i: [] for i in range(len(records))}
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            sim = cosine_similarity(records[i].embedding, records[j].embedding)
            if sim <= _SIM_MINIMA:
                continue
            vizinhos[i].append((sim, j))
            vizinhos[j].append((sim, i))

    vistos: set[tuple[str, str]] = set()
    links = []
    for i, pares in vizinhos.items():
        pares.sort(key=lambda p: p[0], reverse=True)
        for sim, j in pares[:_MAX_ARESTAS_POR_NO]:
            chave = (records[i].id, records[j].id) if i < j else (records[j].id, records[i].id)
            if chave in vistos:
                continue
            vistos.add(chave)
            links.append({
                "source": chave[0],
                "target": chave[1],
                "relation": "similar",
                "confidence": "EXTRACTED" if sim >= _SIM_FORTE else "INFERRED",
                "confidence_score": round(float(sim), 3),
                "weight": round(float(sim), 3),
            })

    return JSONResponse(content={
        "nodes": nodes,
        "links": links,
        "lobes": _lobos_da_memoria(namespaces),
    })


@router.post("/graphify/update")
async def trigger_graphify_update(
    store: VectorStore = Depends(get_memory_vector_store)
):
    """Dispara a rotina em background do Graphify para processar o corpus da memória."""
    if isinstance(store, GraphifyVectorStore):
        store.trigger_graphify_update()
        return JSONResponse(content={"status": "ok", "message": "Graphify update iniciado em background."})
    return JSONResponse(
        content={"status": "error", "message": "O backend de memória atual não é 'graphify'."},
        status_code=400
    )


# --------------------------------------------------------------------------- #
# Os cinco níveis (`plan.md` §10) — o que a aba Memory lista ao lado do grafo
# --------------------------------------------------------------------------- #
#
# Por que um endpoint só, e não cinco. Cada nível mora num lugar diferente
# (Postgres, arquivo JSON, vetor), mas a aba os mostra sempre juntos: cinco
# chamadas por tique de polling seriam cinco vezes o overhead para desenhar uma
# tela só. O formato dos itens é o MESMO para os cinco de propósito — a UI
# desenha um card genérico, e somar um nível não pede componente novo.
#
# Nível que falha não derruba a resposta: cada bloco tem o seu `try`, e o erro
# vira campo do nível. A regra é a mesma de `packages/memory/system.py` — memória
# indisponível não pode virar tela em branco.

#: Teto de itens POR NÍVEL. A aba é um painel de leitura, não um exportador: o
#: histórico de conversa sozinho passa de mil linhas, e mandá-lo inteiro a cada
#: 4s gastaria banda para desenhar uma lista que ninguém rola até o fim.
_MAX_ITENS_NIVEL = 40
#: Corte do texto de cada item. O card mostra duas ou três linhas; o resto seria
#: payload que só o `overflow: hidden` do CSS consumiria.
_MAX_DETALHE = 280


def _corta(texto: str, limite: int = _MAX_DETALHE) -> str:
    limpo = " ".join((texto or "").split())
    return limpo[: limite - 1] + "…" if len(limpo) > limite else limpo


def _quando(valor: Any) -> str | None:
    """ISO-8601 de um datetime, ou o próprio valor quando já é string."""
    if valor is None:
        return None
    if isinstance(valor, str):
        return valor or None
    iso = getattr(valor, "isoformat", None)
    return iso() if callable(iso) else str(valor)


def _dir_memoria() -> Path:
    """Raiz dos níveis em disco — a mesma que `build_memory_system` usa.

    Lido do ambiente aqui em vez de receber um `MemorySystem` injetado porque a
    API não monta um: `build_memory_system` exige um `LLMProvider` (para o
    `embed()` do `knowledge`/`long`) e esta rota só LÊ. Construir o provider para
    listar arquivo JSON pagaria uma resolução de modelo por tique de polling.
    """
    from packages.memory.factory import DATA_DIR_ENV, DEFAULT_DATA_DIR

    return Path(os.environ.get(DATA_DIR_ENV, DEFAULT_DATA_DIR))


async def _nivel_short(session: AsyncSession) -> dict[str, Any]:
    """`short` — turnos recentes da conversa corrente.

    **Por que Postgres e não o Redis de `packages/memory/short_term.py`.**
    Aquele adapter existe e funciona, mas nada no repositório chama
    `set_state()`: escanear o Redis mostraria as streams do event bus, que não
    são memória de conversa. O que de fato cumpre o papel do nível hoje — os
    turnos recentes que o `ChiefAI` relê — são as mensagens da conversa mais
    recente. Mostrar isso é mostrar o nível; mostrar chaves de Redis vazias seria
    mostrar a implementação.
    """
    from apps.api.db.models import ChatMessageRow, ConversationRow

    # Duas consultas em vez de "as N mensagens mais recentes de qualquer
    # conversa": esta última mistura o fim de uma conversa com o começo de outra
    # e o nível deixaria de ser "a conversa corrente" para virar "o log global".
    ultima = (
        await session.execute(
            select(ChatMessageRow.conversation_id)
            .order_by(desc(ChatMessageRow.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()

    if ultima is None:
        return {
            "count": 0,
            "items": [],
            "backend": "postgres · chat_messages",
            "empty_hint": "Nenhuma conversa ainda.",
        }

    stmt = (
        select(ChatMessageRow)
        .where(ChatMessageRow.conversation_id == ultima)
        .order_by(desc(ChatMessageRow.created_at))
        .limit(_MAX_ITENS_NIVEL)
    )
    linhas = list((await session.execute(stmt)).scalars())
    # A consulta veio do mais novo para o mais velho (é assim que se pega "os
    # recentes" sem varrer a tabela); a leitura é do mais velho para o mais novo.
    linhas.reverse()

    conversa = await session.get(ConversationRow, ultima)
    titulo = (conversa.title if conversa else "") or str(ultima)

    itens = [
        {
            "id": str(linha.id),
            "title": str(linha.role),
            "detail": _corta(linha.content or ""),
            "at": _quando(linha.created_at),
            "badge": linha.model or None,
        }
        for linha in linhas
    ]
    return {
        "count": len(itens),
        "items": itens,
        "backend": f"postgres · {_corta(titulo, 60)}",
    }


async def _nivel_working() -> dict[str, Any]:
    """`working` — um arquivo por task viva em `MEMORY_DATA_DIR/working`.

    Vazio é o estado NORMAL: o nível é descartado quando a task conclui
    (`MemorySystem.on_task_succeeded`), então só aparece aqui task em curso ou
    interrompida. A UI recebe `empty_hint` para dizer isso em vez de sugerir que
    algo quebrou.
    """
    from packages.memory.models import AttemptOutcome, WorkingMemoryState

    raiz = _dir_memoria() / "working"
    arquivos = sorted(
        raiz.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ) if raiz.is_dir() else []

    itens: list[dict[str, Any]] = []
    for caminho in arquivos[:_MAX_ITENS_NIVEL]:
        try:
            estado = WorkingMemoryState.model_validate_json(
                caminho.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            # Mesmo critério de `JsonFileWorkingMemoryStore.load`: arquivo
            # corrompido é uma linha a menos, não uma aba quebrada.
            continue

        falhas = sum(1 for a in estado.attempts if a.outcome is AttemptOutcome.FAILED)
        partes = [f"{len(estado.attempts)} tentativa(s)"]
        if falhas:
            partes.append(f"{falhas} falha(s)")
        if estado.plan:
            partes.append(f"plano com {len(estado.plan)} passo(s)")
        if estado.partials:
            partes.append(f"{len(estado.partials)} parcial(is)")
        if estado.interrupted_attempt is not None:
            partes.append("interrompida (processo morreu)")

        itens.append({
            "id": str(estado.task_id),
            "title": estado.title or str(estado.task_id),
            "detail": " · ".join(partes),
            "at": _quando(estado.updated_at),
            "badge": f"rev {estado.revision}",
        })

    return {
        "count": len(itens),
        "items": itens,
        "backend": f"json · {raiz.as_posix()}",
        "empty_hint": "Nenhuma task em execução — o nível é descartado quando a task conclui.",
    }


def _nivel_vetorial(registros: list[Any], namespace: str) -> dict[str, Any]:
    """Fatia de um namespace do vector store (`long_term` ou `knowledge`)."""
    do_ns = [r for r in registros if r.namespace == namespace]
    itens = [
        {
            "id": str(r.id),
            "title": _corta(r.text, 80),
            "detail": _corta(r.text),
            "at": _quando((r.metadata or {}).get("updated_at")),
            "badge": (r.metadata or {}).get("source") or None,
        }
        for r in do_ns[:_MAX_ITENS_NIVEL]
    ]
    # `count` é o total do namespace, não o tamanho da página: o card diz quantos
    # fatos existem, e a lista mostra os primeiros.
    return {"count": len(do_ns), "items": itens}


async def _nivel_knowledge(registros: list[Any]) -> dict[str, Any]:
    """`knowledge` — documentos do índice incremental + chunks no vector store.

    Duas fontes porque as duas respondem perguntas diferentes: o índice diz
    QUAIS documentos entraram (é ele que torna a reindexação incremental), o
    vector store diz em quantos chunks eles viraram. Um documento no índice sem
    chunk correspondente é justamente o sintoma que vale ver na tela.
    """
    from packages.memory.factory import vector_backend
    from packages.memory.models import IndexedDocument

    chunks = _nivel_vetorial(registros, "knowledge")

    docs: list[dict[str, Any]] = []
    caminho = _dir_memoria() / "knowledge_index.json"
    try:
        bruto = caminho.read_text(encoding="utf-8")
    except OSError:
        bruto = ""
    if bruto:
        try:
            for linha in json.loads(bruto):
                doc = IndexedDocument.model_validate(linha)
                docs.append({
                    "id": doc.doc_id,
                    "title": doc.source or doc.doc_id,
                    "detail": f"{len(doc.chunk_ids)} chunk(s) indexado(s)",
                    "at": _quando(doc.indexed_at),
                    "badge": "doc",
                })
        except ValueError:
            docs = []

    # Documentos primeiro: são a unidade que o dono reconhece ("o PDF que
    # ingeri"); os chunks são o detalhe de implementação do RAG.
    itens = [*docs[:_MAX_ITENS_NIVEL], *chunks["items"]][:_MAX_ITENS_NIVEL]
    return {
        "count": chunks["count"] + len(docs),
        "items": itens,
        "backend": f"{vector_backend()} · {len(docs)} doc(s), {chunks['count']} chunk(s)",
    }


async def _nivel_experience() -> dict[str, Any]:
    """`experience` — padrões acumulados, do mais recorrente ao menos.

    A ordem é a mesma de `ExperienceMemory.patterns()`, e `occurrences` vem no
    badge: é o número que separa acidente (1x) de padrão (>= o limiar), e sem ele
    a lista pareceria um log de erros.
    """
    from packages.memory.experience import DEFAULT_PATTERN_THRESHOLD
    from packages.memory.models import ExperienceRecord

    caminho = _dir_memoria() / "experience.json"
    try:
        bruto = caminho.read_text(encoding="utf-8")
    except OSError:
        bruto = ""

    registros: list[ExperienceRecord] = []
    if bruto:
        try:
            registros = [
                ExperienceRecord.model_validate(linha) for linha in json.loads(bruto)
            ]
        except ValueError:
            registros = []

    registros.sort(key=lambda r: (-r.occurrences, -r.last_seen_at.timestamp(), r.id))

    itens = [
        {
            "id": r.id,
            "title": r.subject,
            "detail": _corta(r.lesson),
            "at": _quando(r.last_seen_at),
            "badge": f"{r.kind.value.replace('capability_', '')} ×{r.occurrences}",
            "promoted": r.occurrences >= DEFAULT_PATTERN_THRESHOLD,
        }
        for r in registros[:_MAX_ITENS_NIVEL]
    ]
    return {
        "count": len(registros),
        "items": itens,
        "backend": f"json · {caminho.as_posix()}",
        "empty_hint": (
            f"Nada acumulado ainda — um padrão entra a partir de "
            f"{DEFAULT_PATTERN_THRESHOLD} ocorrências da mesma assinatura."
        ),
    }


#: Descrição fixa de cada nível: rótulo, o que guarda e por quanto tempo vive.
#: Fica no backend, e não no front, para que a aba e o `plan.md` §10 não
#: divirjam em dois arquivos diferentes.
_DESCRICAO_NIVEIS: list[dict[str, str]] = [
    {
        "id": "short",
        "name": "Short",
        "subtitle": "turnos recentes da conversa corrente",
        "lifetime": "sessão",
    },
    {
        "id": "working",
        "name": "Working",
        "subtitle": "plano, parciais e tentativas da task em execução",
        "lifetime": "a task",
    },
    {
        "id": "long",
        "name": "Long",
        "subtitle": "fatos duráveis: máquinas, caminhos, contas, preferências",
        "lifetime": "permanente, editável",
    },
    {
        "id": "knowledge",
        "name": "Knowledge",
        "subtitle": "documentos ingeridos e recuperados por busca semântica (RAG)",
        "lifetime": "permanente",
    },
    {
        "id": "experience",
        "name": "Experience",
        "subtitle": "padrões de execução: o que falha, o que funciona, como o dono decide",
        "lifetime": "permanente, por acúmulo",
    },
]


@router.get("/levels")
async def get_memory_levels(session: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Os cinco níveis de `plan.md` §10 num payload só, para a aba Memory.

    Até esta versão a aba mostrava **apenas** o grafo de vetores — ou seja,
    `knowledge` e `long` misturados num desenho, e nada de `short`, `working` ou
    `experience`. Quem olhasse a tela concluía que a memória do sistema era um
    RAG. Os outros três níveis existiam, gravavam em disco e alimentavam o
    planejamento sem nenhuma superfície de leitura.
    """
    # Uma leitura do vector store para os dois níveis que moram nele: `get_all()`
    # carrega embeddings, e chamá-lo duas vezes por tique dobraria o custo do
    # nível mais pesado da lista.
    try:
        registros = await get_memory_vector_store().get_all()
    except Exception as exc:  # noqa: BLE001 — nível quebrado não derruba a aba
        registros = []
        erro_vetorial: str | None = str(exc)
    else:
        erro_vetorial = None

    async def _seguro(coro) -> dict[str, Any]:
        try:
            return await coro
        except Exception as exc:  # noqa: BLE001
            return {"count": 0, "items": [], "error": str(exc)}

    dados: dict[str, dict[str, Any]] = {
        "short": await _seguro(_nivel_short(session)),
        "working": await _seguro(_nivel_working()),
        "experience": await _seguro(_nivel_experience()),
    }

    if erro_vetorial is not None:
        vazio = {"count": 0, "items": [], "error": erro_vetorial}
        dados["long"] = dict(vazio)
        dados["knowledge"] = dict(vazio)
    else:
        dados["long"] = {
            **_nivel_vetorial(registros, "long_term"),
            "backend": "vector store · namespace long_term",
            "empty_hint": "Nenhum fato gravado ainda.",
        }
        dados["knowledge"] = await _seguro(_nivel_knowledge(registros))

    return JSONResponse(content={
        "levels": [{**nivel, **dados[nivel["id"]]} for nivel in _DESCRICAO_NIVEIS]
    })


@router.get("/graphify.html")
async def get_graphify_html():
    """Retorna o HTML interativo gerado nativamente pelo Graphify."""
    # O arquivo é gerado em: data/memory_corpus/graphify-out/graph.html
    html_path = Path("./data/memory_corpus/graphify-out/graph.html")
    if html_path.exists():
        return FileResponse(html_path)
    
    return HTMLResponse(
        content="<html><body><h2>O grafo ainda não foi gerado.</h2><p>Vá em 'Memory' -> 'Atualizar Grafo' para iniciar a extração do Graphify.</p></body></html>",
        status_code=404
    )

