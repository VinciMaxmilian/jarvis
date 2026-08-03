"""Rota de memória — serve a visualização de grafo dos vetores RAG."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path

from apps.api.deps import get_memory_vector_store
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

@router.get("/graph.json")
async def get_memory_graph_json(
    store: VectorStore = Depends(get_memory_vector_store)
):
    """Retorna o grafo JSON no formato NeuralMap."""
    records = await store.get_all()
    
    nodes = []
    links = []
    
    # Custom lobes for memory map
    lobes = [
        { "p": "knowledge", "x": -400, "y": 0, "z": 0, "n": "Knowledge" },
        { "p": "long_term", "x": 400, "y": 0, "z": 0, "n": "Long Term" }
    ]

    for record in records:
        label = record.text[:40].replace('\n', ' ') + ("..." if len(record.text) > 40 else "")
        nodes.append({
            "id": record.id,
            "label": label,
            "source_file": record.namespace,
            "file_type": "memory",
            "community": 1 if record.namespace == "knowledge" else 2,
            "deg": 0,
        })

    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            sim = cosine_similarity(records[i].embedding, records[j].embedding)
            if sim > 0.70:
                links.append({
                    "source": records[i].id,
                    "target": records[j].id,
                    "confidence": f"{sim:.2f}"
                })
                nodes[i]["deg"] += 1
                nodes[j]["deg"] += 1

    return JSONResponse(content={"nodes": nodes, "links": links, "lobes": lobes})


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

