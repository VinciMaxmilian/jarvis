"""Rota de memória — serve a visualização de grafo dos vetores RAG."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path

from apps.api.deps import get_chat_history_store, get_memory_vector_store
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

