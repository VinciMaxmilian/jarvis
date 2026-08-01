"""Rota de memória — serve a visualização de grafo dos vetores RAG."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_chat_history_store
from packages.memory.vector_store import cosine_similarity
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
            background-color: #1a1a1a;
            color: #fff;
            font-family: sans-serif;
            overflow: hidden;
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
            "color": "#4a4a4a",
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
    store: VectorStore = Depends(get_chat_history_store)
):
    """Retorna o HTML com o grafo do VectorStore num JSON para driblar o Cloudflare."""
    records = await store.get_all()
    html_content = generate_graph_html(records)
    return JSONResponse(content={"html": html_content})
