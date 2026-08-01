"""Os dublês são testados como código de produção.

Dublê que sai da porta transforma a suíte em teatro: verde contra um contrato que
não existe. As portas são `runtime_checkable`, então a conformidade é verificável
com `isinstance` — e é aqui que ela é verificada.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from packages.llm.base import LLMProvider, Message, StreamChunk
from packages.shared.contracts import ChatMessage, Event, EventType, MessageRole
from packages.shared.ports import (
    ConversationStore,
    EventBus,
    GoalStore,
    ToolExecutor,
)
from tests.conftest import (
    FakeLLMProvider,
    InMemoryConversationStore,
    InMemoryEventBus,
    InMemoryGoalStore,
    RecordingToolExecutor,
    cosine,
    stable_embedding,
)

# --------------------------------------------------------------------------- #
# Conformidade com as portas
# --------------------------------------------------------------------------- #


def test_fake_llm_implementa_a_porta(fake_llm: FakeLLMProvider) -> None:
    assert isinstance(fake_llm, LLMProvider)


def test_in_memory_goal_store_implementa_a_porta(
    goal_store: InMemoryGoalStore,
) -> None:
    assert isinstance(goal_store, GoalStore)


def test_in_memory_event_bus_implementa_a_porta(event_bus: InMemoryEventBus) -> None:
    assert isinstance(event_bus, EventBus)


def test_in_memory_conversation_store_implementa_a_porta(
    conversation_store: InMemoryConversationStore,
) -> None:
    assert isinstance(conversation_store, ConversationStore)


def test_recording_tool_executor_implementa_a_porta(
    tool_executor: RecordingToolExecutor,
) -> None:
    assert isinstance(tool_executor, ToolExecutor)


# --------------------------------------------------------------------------- #
# FakeLLMProvider
# --------------------------------------------------------------------------- #


async def test_roteiro_e_consumido_na_ordem(fake_llm: FakeLLMProvider) -> None:
    fake_llm.queue_text("primeira").queue_text("segunda")
    msgs = [Message(role="user", content="oi")]

    assert (await fake_llm.complete(msgs)).text == "primeira"
    assert (await fake_llm.complete(msgs)).text == "segunda"
    assert (await fake_llm.complete(msgs)).text == fake_llm.default_text
    assert fake_llm.complete_calls == 3
    assert fake_llm.pending == 0


async def test_tool_call_sob_demanda(fake_llm: FakeLLMProvider) -> None:
    fake_llm.queue_tool_call("web_search", {"q": "jarvis"}, call_id="c1")

    completion = await fake_llm.complete([Message(role="user", content="busca")])

    assert completion.wants_tools is True
    assert completion.tool_calls[0].name == "web_search"
    assert completion.tool_calls[0].arguments == {"q": "jarvis"}
    assert completion.tool_calls[0].id == "c1"


async def test_stream_termina_em_done(fake_llm: FakeLLMProvider) -> None:
    fake_llm.queue_text("olá")

    chunks: list[StreamChunk] = [
        c async for c in fake_llm.stream([Message(role="user", content="oi")])
    ]

    assert [c.type for c in chunks] == ["text", "done"]
    assert chunks[-1].completion is not None
    assert fake_llm.stream_calls == 1


async def test_mensagens_recebidas_ficam_registradas(fake_llm: FakeLLMProvider) -> None:
    await fake_llm.complete(
        [Message(role="system", content="s"), Message(role="user", content="u")]
    )

    assert [m.role for m in fake_llm.received[0]] == ["system", "user"]


# --------------------------------------------------------------------------- #
# embed(): determinismo e ranking
# --------------------------------------------------------------------------- #


async def test_embed_e_estavel_para_o_mesmo_texto(fake_llm: FakeLLMProvider) -> None:
    primeiro = await fake_llm.embed(["nas_sync"])
    segundo = await fake_llm.embed(["nas_sync"])

    assert primeiro == segundo


async def test_embed_devolve_vetor_unitario(fake_llm: FakeLLMProvider) -> None:
    (vetor,) = await fake_llm.embed(["backup do postgres"])

    assert len(vetor) == fake_llm.embedding_dim
    assert cosine(vetor, vetor) == pytest.approx(1.0)


async def test_embed_separa_textos_diferentes(fake_llm: FakeLLMProvider) -> None:
    a, b = await fake_llm.embed(["backup", "cloudflare"])

    assert a != b
    assert cosine(a, b) < 1.0


async def test_ranking_por_similaridade_e_exato(fake_llm: FakeLLMProvider) -> None:
    """A consulta idêntica ao documento é sempre o primeiro colocado."""
    corpus = ["backup do postgres", "tunnel do cloudflare", "sync com o nas"]
    vetores = await fake_llm.embed(corpus)
    consulta = stable_embedding("tunnel do cloudflare", dim=fake_llm.embedding_dim)

    ranking = sorted(
        zip(corpus, vetores, strict=True),
        key=lambda par: cosine(consulta, par[1]),
        reverse=True,
    )

    assert ranking[0][0] == "tunnel do cloudflare"
    assert cosine(consulta, ranking[0][1]) == pytest.approx(1.0)


def test_embedding_nao_depende_do_hash_semeado_do_processo() -> None:
    """Valor fixado à mão: `hash()` embutido mudaria a cada execução."""
    esperado = stable_embedding("nas_sync", dim=4)

    assert stable_embedding("nas_sync", dim=4) == esperado
    assert stable_embedding("nas_sync", dim=4) != stable_embedding("nas_syn", dim=4)


# --------------------------------------------------------------------------- #
# InMemoryEventBus
# --------------------------------------------------------------------------- #


async def test_bus_grava_tudo_que_foi_publicado(event_bus: InMemoryEventBus) -> None:
    await event_bus.publish(
        Event(type=EventType.CAPABILITY_GAP_DETECTED, source="registry", trace_id="t1")
    )
    await event_bus.publish(
        Event(type=EventType.GOAL_BLOCKED, source="goal_manager", trace_id="t1")
    )

    assert event_bus.types == ["capability.gap_detected", "goal.blocked"]
    assert len(event_bus.of_type(EventType.GOAL_BLOCKED)) == 1

    event_bus.clear()
    assert event_bus.published == []


# --------------------------------------------------------------------------- #
# InMemoryConversationStore
# --------------------------------------------------------------------------- #


async def test_conversation_store_mantem_ordem_e_isola_conversas(
    conversation_store: InMemoryConversationStore,
) -> None:
    conversa = await conversation_store.ensure_conversation(uuid4())
    outra = uuid4()

    await conversation_store.append(
        ChatMessage(conversation_id=conversa, role=MessageRole.USER, content="oi")
    )
    await conversation_store.append(
        ChatMessage(conversation_id=conversa, role=MessageRole.ASSISTANT, content="olá")
    )
    await conversation_store.append(
        ChatMessage(conversation_id=outra, role=MessageRole.USER, content="outra")
    )

    historico = await conversation_store.history(conversa)
    assert [m.content for m in historico] == ["oi", "olá"]
    assert conversa in conversation_store.conversations
