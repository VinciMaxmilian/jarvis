"""Fala de preenchimento enquanto uma ferramenta roda.

**O problema.** Com o `ChiefAI` no caminho de voz, uma pergunta como "como está o
tempo?" dispara `web_search`, que é uma ida ao Tavily. São segundos de silêncio
absoluto — e silêncio numa chamada lê como travamento. O dono repete a pergunta,
o VAD corta a resposta que estava vindo, e a conversa piora.

**A solução.** `ChiefAI.respond()` emite `StreamChunk(type="tool_call")` ANTES de
executar a ferramenta. Esse chunk é o gancho para dizer algo curto enquanto a
ferramenta trabalha: responder, agir, responder de novo.

Quatro decisões que separam isto de virar irritante:

1. **Varia.** A mesma frase toda vez vira tique em dois dias de uso. Sorteia.
2. **Depende da tool.** `web_search` pede "deixa eu procurar"; `search_memory`
   pede "deixa eu lembrar". O nome está no chunk, usar é de graça e a diferença
   de naturalidade é grande.
3. **Só se a espera valer** — quem decide isso é quem chama, com o atraso de
   `ATRASO_ANTES_DE_FALAR`. Tool que responde em 200 ms não precisa de
   preenchimento; falar por cima dela ADICIONA latência em vez de esconder.
4. **Não entra no histórico.** É artefato de interface, não fala do assistente.
   Gravado no histórico, envenena o contexto das próximas respostas — o modelo
   passa a achar que costuma dizer "deixa eu ver" e imita.
"""

from __future__ import annotations

import random
from typing import Final

#: Espera antes de falar o preenchimento. Se a tool responder antes disto, nada é
#: dito. Escolhido para ficar abaixo do ponto em que o silêncio começa a parecer
#: falha, e acima da duração das tools rápidas (memória local, leitura de arquivo).
ATRASO_ANTES_DE_FALAR: Final = 0.6

_POR_TOOL: Final[dict[str, tuple[str, ...]]] = {
    "web_search": (
        "Deixa eu procurar isso.",
        "Vou dar uma olhada na internet.",
        "Só um instante, estou pesquisando.",
    ),
    "search_memory": (
        "Deixa eu lembrar.",
        "Vou olhar no que eu guardei.",
        "Só um segundo, procurando na memória.",
    ),
    "knowledge_save": (
        "Anotando isso.",
        "Vou guardar.",
    ),
    "analyze_image": (
        "Deixa eu olhar essa imagem.",
        "Estou vendo a imagem.",
    ),
    "save_modified_image": (
        "Salvando a imagem.",
    ),
    "criar_servidor_mcp": (
        "Isso vai levar um instante, estou escrevendo o código.",
        "Deixa eu montar essa ferramenta.",
    ),
}

#: Para tool desconhecida — inclusive as de MCP, que nascem em runtime e nunca
#: estarão no mapa acima.
_GENERICOS: Final[tuple[str, ...]] = (
    "Só um instante.",
    "Deixa eu verificar.",
    "Estou vendo isso agora.",
    "Um momento.",
)


def escolher(tool: str, *, rng: random.Random | None = None) -> str:
    """Frase de preenchimento para `tool`. Genérica se a tool for desconhecida."""
    escolhas = _POR_TOOL.get(tool, _GENERICOS)
    r = rng or random
    return r.choice(escolhas)
