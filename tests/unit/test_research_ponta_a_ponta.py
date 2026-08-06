"""O caminho completo: chat enfileira → orchestrator pesquisa → skill nasce.

Os testes por módulo cobrem cada estágio; este cobre a COSTURA, que é onde as
peças foram escritas por caminhos diferentes e podem discordar em silêncio — o
`tipo: "research"` que o executor grava e o `GoalManager` lê, o `topic` que o
pipeline escreve no metadado e o `skill_synthesize` procura, e o `{{SKILLS}}` que
o `chief.md` declara e o `ChiefAI` resolve.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from packages.agents.skills import SkillRegistry
from packages.agents.tools.executor import SystemToolExecutor
from packages.llm.base import Completion
from packages.memory.vector_store import InMemoryVectorStore
from packages.rag.research import ResearchConfig, ResearchPipeline
from packages.shared.contracts import GoalStatus
from tests.conftest import FakeEmbeddingProvider, InMemoryGoalStore

pytestmark = pytest.mark.anyio


class _LLM:
    """Responde conforme o estágio que perguntou."""

    name = "dublê"
    model = "m1"

    def __init__(self, *, skill: dict[str, Any] | None = None) -> None:
        self.skill = skill

    async def complete(self, messages, tools=None, temperature=0.7, **kwargs) -> Completion:
        sistema = messages[0].content
        if "subconsultas" in sistema:
            texto = json.dumps(["o que é"])
        elif 'Você escreve a "skill"' in sistema:
            texto = json.dumps(self.skill or {})
        else:
            texto = json.dumps(
                {
                    "util": True,
                    "titulo": "Algoritmo",
                    "resumo": "o que é um algoritmo",
                    "tags": ["fundamentos"],
                    "texto_limpo": "Um algoritmo é uma sequência finita de passos. " * 40,
                }
            )
        return Completion(text=texto, model=self.model, finish_reason="stop")

    async def embed(self, texts):
        raise AssertionError("embedding vem do embed_llm")


async def _busca(*, query: str, max_results: int = 10, incluir_conteudo: bool = False):
    return {
        "results": [
            {
                "url": "https://exemplo.com/algoritmo",
                "title": "Algoritmo",
                "content": "resumo",
                "raw_content": "conteúdo bruto da página. " * 200,
            }
        ]
    }


async def test_fluxo_completo(tmp_path: Path) -> None:
    knowledge = tmp_path / "knowledge"
    skills_dir = tmp_path / "skills"
    store = InMemoryVectorStore()
    embed = FakeEmbeddingProvider()
    goal_store = InMemoryGoalStore()
    registry = SkillRegistry(base_dir=skills_dir)

    llm = _LLM(
        skill={
            "name": "logica-de-programacao",
            "description": "Fundamentos de lógica. Use quando o dono perguntar sobre algoritmos.",
            "triggers": ["algoritmo", "laço"],
            "corpo": "## Quando usar\nSempre que o assunto for lógica.\n",
        }
    )

    # --- 1. o chat enfileira ------------------------------------------------ #
    executor = SystemToolExecutor(
        tavily_api_key="k",
        llm=llm,
        chat_history_store=InMemoryVectorStore(),
        memory_vector_store=store,
        embed_llm=embed,
        goal_store=goal_store,
        skill_registry=registry,
    )

    enfileirado = await executor.execute(
        "knowledge_research", {"topico": "lógica de programação", "profundidade": "rasa"}
    )
    assert enfileirado["sucesso"] is True
    goal_id = enfileirado["goal_id"]

    goals = await goal_store.list_goals(status=GoalStatus.DRAFT)
    assert len(goals) == 1
    assert goals[0].context["tipo"] == "research"
    assert goals[0].context["topico"] == "lógica de programação"

    # --- 2. o orchestrator executa ------------------------------------------ #
    from packages.agents.goal_manager import GoalManager

    pipeline = ResearchPipeline(
        llm=llm,
        embed_llm=embed,
        memory_store=store,
        web_search=_busca,
        knowledge_dir=knowledge,
        config=ResearchConfig(max_fontes=1),
    )
    gm = GoalManager(goal_store=goal_store, llm=llm, research_pipeline=pipeline)

    from uuid import UUID

    concluido = await gm.process_goal(UUID(goal_id))
    assert concluido is not None
    assert concluido.status == GoalStatus.DONE

    # O documento foi para o disco, sob a pasta do tópico...
    escritos = list(knowledge.rglob("*.md"))
    assert len(escritos) == 1
    assert escritos[0].parent.name == "logica-de-programacao"
    # ...e para o índice, com proveniência.
    registros = await store.get_all(namespace="knowledge")
    assert registros
    assert registros[0].metadata["topic"] == "logica-de-programacao"

    # --- 3. a skill nasce do que foi indexado -------------------------------- #
    sintetizada = await executor.execute(
        "skill_synthesize", {"topico": "lógica de programação"}
    )
    assert sintetizada["sucesso"] is True, sintetizada
    assert (skills_dir / "logica-de-programacao" / "SKILL.md").exists()

    # --- 4. e aparece no prompt sem restart ---------------------------------- #
    bloco = registry.render_prompt_block()
    assert "logica-de-programacao" in bloco
    assert "Fundamentos de lógica" in bloco
    # Divulgação progressiva: o CORPO não vai no prompt.
    assert "Sempre que o assunto for lógica" not in bloco

    corpo = await executor.execute("skill_load", {"nome": "logica-de-programacao"})
    assert corpo["sucesso"] is True
    assert "Sempre que o assunto for lógica" in corpo["conteudo"]


async def test_web_search_aceita_incluir_conteudo_e_repassa_ao_tavily() -> None:
    """Contrato entre o pipeline e a busca — a assinatura exata que ele chama.

    O `ResearchPipeline` chama `web_search(query=, max_results=, incluir_conteudo=)`
    por palavra-chave. Sem este teste, remover o parâmetro passa em toda a suíte e
    só aparece na primeira pesquisa de verdade, como `TypeError` engolido pelo
    `except` do estágio de descoberta — que transforma a falha em "0 fontes
    encontradas", o sintoma mais difícil de ler que existe.
    """
    import httpx

    from packages.agents.tools import executor as mod

    capturado: dict[str, Any] = {}

    class _Cliente:
        def __init__(self, *a, **k) -> None: ...

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json):
            capturado.update(json)
            return httpx.Response(
                200,
                json={
                    "answer": "",
                    "images": [],
                    "results": [
                        {
                            "title": "T",
                            "url": "https://a.com/x",
                            "content": "resumo",
                            "score": 0.9,
                            # O Tavily manda `null` para a página que não baixou.
                            "raw_content": None,
                        }
                    ],
                },
                request=httpx.Request("POST", url),
            )

    original = mod.httpx.AsyncClient
    mod.httpx.AsyncClient = _Cliente
    try:
        ex = SystemToolExecutor(
            tavily_api_key="k", llm=_LLM(), chat_history_store=InMemoryVectorStore()
        )
        saida = await ex._web_search(
            query="lógica", max_results=5, incluir_conteudo=True
        )
    finally:
        mod.httpx.AsyncClient = original

    assert capturado["include_raw_content"] is True
    # `None` do Tavily não pode chegar ao consumidor, que mede `len()` para
    # decidir se precisa do fetcher.
    assert saida["results"][0]["raw_content"] == ""

    # E o default continua barato para o chat comum.
    mod.httpx.AsyncClient = _Cliente
    try:
        ex = SystemToolExecutor(
            tavily_api_key="k", llm=_LLM(), chat_history_store=InMemoryVectorStore()
        )
        saida = await ex._web_search(query="lógica")
    finally:
        mod.httpx.AsyncClient = original

    assert capturado["include_raw_content"] is False
    assert "raw_content" not in saida["results"][0]


async def test_spec_do_web_search_declara_incluir_conteudo() -> None:
    """O modelo só usa o que está no schema."""
    from packages.agents.tools.executor import TAVILY_SEARCH_SPEC

    assert "incluir_conteudo" in TAVILY_SEARCH_SPEC.input_schema["properties"]


async def test_dispatch_do_web_search_repassa_o_argumento() -> None:
    """`execute()` é o caminho real do LLM; a assinatura sozinha não basta."""
    visto: dict[str, Any] = {}

    ex = SystemToolExecutor(
        tavily_api_key="k", llm=_LLM(), chat_history_store=InMemoryVectorStore()
    )

    async def _espiao(**kwargs):
        visto.update(kwargs)
        return {}

    ex._web_search = _espiao
    await ex.execute("web_search", {"query": "x", "incluir_conteudo": True})
    assert visto["incluir_conteudo"] is True


async def test_goal_de_pesquisa_sem_pipeline_falha_explicito(tmp_path: Path) -> None:
    """Sem pipeline o goal tem que FALHAR, não virar decomposição genérica."""
    from uuid import UUID

    from packages.agents.goal_manager import GoalManager
    from packages.shared.contracts import Goal

    goal_store = InMemoryGoalStore()
    criado = await goal_store.create_goal(
        Goal(title="Pesquisar: x", context={"tipo": "research", "topico": "x"})
    )
    gm = GoalManager(goal_store=goal_store, llm=_LLM(), research_pipeline=None)

    resultado = await gm.process_goal(UUID(str(criado.id)))
    assert resultado is not None
    assert resultado.status == GoalStatus.FAILED


async def test_skill_synthesize_sem_material_recusa(tmp_path: Path) -> None:
    """Não inventa skill sobre assunto que não foi estudado."""
    executor = SystemToolExecutor(
        tavily_api_key="k",
        llm=_LLM(skill={}),
        chat_history_store=InMemoryVectorStore(),
        memory_vector_store=InMemoryVectorStore(),
        embed_llm=FakeEmbeddingProvider(),
        skill_registry=SkillRegistry(base_dir=tmp_path / "skills"),
    )
    resultado = await executor.execute("skill_synthesize", {"topico": "nunca estudado"})
    assert resultado["sucesso"] is False
    assert "knowledge_research" in resultado["motivo"]


async def test_knowledge_research_sem_goal_store_nao_e_anunciada(tmp_path: Path) -> None:
    executor = SystemToolExecutor(
        tavily_api_key="k",
        llm=_LLM(),
        chat_history_store=InMemoryVectorStore(),
    )
    assert executor.has("knowledge_research") is False
    assert executor.has("skill_load") is False


async def test_topico_curto_e_recusado_antes_de_gastar(tmp_path: Path) -> None:
    executor = SystemToolExecutor(
        tavily_api_key="k",
        llm=_LLM(),
        chat_history_store=InMemoryVectorStore(),
        goal_store=InMemoryGoalStore(),
    )
    resultado = await executor.execute("knowledge_research", {"topico": "x"})
    assert resultado["sucesso"] is False


async def test_prompt_do_chief_resolve_o_marcador(tmp_path: Path) -> None:
    """`{{SKILLS}}` não pode vazar literal para o modelo."""
    from packages.agents.chief import ChiefAI
    from tests.conftest import InMemoryConversationStore, RecordingToolExecutor

    skills_dir = tmp_path / "skills"
    (skills_dir / "teste").mkdir(parents=True)
    (skills_dir / "teste" / "SKILL.md").write_text(
        "---\nname: teste\ndescription: Uma skill de teste.\n---\n\n## Quando usar\nNunca.\n",
        encoding="utf-8",
    )

    chief = ChiefAI(
        llm=_LLM(),
        tools=RecordingToolExecutor(),
        conversation_store=InMemoryConversationStore(),
        skill_registry=SkillRegistry(base_dir=skills_dir),
    )

    resolvido = chief._prompt_com_skills()
    assert "{{SKILLS}}" not in resolvido
    assert "Uma skill de teste." in resolvido


async def test_registro_de_skills_quebrado_nao_derruba_o_turno(tmp_path: Path) -> None:
    from packages.agents.chief import ChiefAI
    from tests.conftest import InMemoryConversationStore, RecordingToolExecutor

    class _Explode:
        def render_prompt_block(self):
            raise RuntimeError("disco fora")

    chief = ChiefAI(
        llm=_LLM(),
        tools=RecordingToolExecutor(),
        conversation_store=InMemoryConversationStore(),
        skill_registry=_Explode(),
    )
    resolvido = chief._prompt_com_skills()
    assert "{{SKILLS}}" not in resolvido
