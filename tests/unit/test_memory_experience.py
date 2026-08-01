"""Nível `experience` — aceite 3 da v1.3 (`plan-execution.md` §3).

> "Falha repetida de capability gera registro em `experience` que aparece no
> contexto do próximo planejamento."

A frase tem duas metades e as duas são testadas ponta a ponta, sem mock: a falha
entra pelo gancho que o `GoalManager` chama de verdade (`on_task_failed`) e sai
pelo prompt que o `GoalManager` monta de verdade (`decompose_goal`). Um teste que
chamasse `record_capability_failure()` e depois lesse `patterns()` provaria que
duas funções minhas conversam entre si — não que o sistema aprende.

A regra que dá sentido ao nível é **acidente não é padrão**: uma falha isolada
não pode entrar no prompt. Metade destes testes existe para fixar o que *não*
aparece, porque um nível que promove tudo enche o contexto de ruído e faz o
planejador evitar capability que funciona.

Sem rede e sem modelo: o `FakeLLMProvider` guarda as mensagens recebidas em
`received`, e é nelas que se lê o que o planejador teria visto.
"""

from __future__ import annotations

import pytest

from packages.agents.goal_manager import DECOMPOSE_PROMPT, GoalManager
from packages.memory.experience import ExperienceMemory, render_experience_context
from packages.memory.models import ExperienceKind
from packages.memory.stores import InMemoryExperienceStore
from packages.memory.system import MemorySystem
from packages.shared.contracts import EventType, Goal, Task
from tests.conftest import (
    FakeLLMProvider,
    InMemoryEventBus,
    InMemoryGoalStore,
    RecordingToolExecutor,
)

CAPABILITY = "nas_sync"
ERRO_NAS = "ConnectionError: NAS em standby, share não montou"


def memoria(
    *, event_bus: InMemoryEventBus | None = None, threshold: int = 2
) -> MemorySystem:
    """Só o nível `experience`. Os outros são `None` de propósito.

    A fachada aceita nível ausente, e um teste de `experience` que precisasse
    montar `knowledge` e `working` para rodar estaria testando a fachada.
    """
    return MemorySystem(
        experience=ExperienceMemory(
            InMemoryExperienceStore(),
            event_bus=event_bus,
            pattern_threshold=threshold,
        )
    )


def task_da(goal: Goal, *, capability: str = CAPABILITY) -> Task:
    return Task(goal_id=goal.id, title="sincronizar o NAS", capability=capability)


@pytest.fixture
def goal() -> Goal:
    return Goal(title="manter o backup em dia", description="rotina noturna")


# --------------------------------------------------------------------------- #
# Aceite 3 — ponta a ponta, pelo caminho que o GoalManager usa
# --------------------------------------------------------------------------- #


async def test_falha_repetida_aparece_no_prompt_do_planejamento_seguinte(
    goal: Goal,
    fake_llm: FakeLLMProvider,
    goal_store: InMemoryGoalStore,
    tool_executor: RecordingToolExecutor,
) -> None:
    """ACEITE v1.3 (3): duas falhas viram lição, e a lição entra no prompt.

    O `GoalManager` é o real. O que se inspeciona é a mensagem `system` que ele
    montou — se a lição não estiver ali, o modelo nunca a viu, e o registro em
    `experience` seria um diário que ninguém lê.
    """
    mem = memoria()
    manager = GoalManager(goal_store, tool_executor, fake_llm, memory=mem)
    fake_llm.queue_text('[{"title": "acordar o NAS", "depends_on_index": []}]')

    await mem.on_task_failed(task_da(goal), ERRO_NAS)
    await mem.on_task_failed(task_da(goal), ERRO_NAS)

    await manager.decompose_goal(goal)

    system = fake_llm.received[0][0]
    assert system.role == "system"
    assert CAPABILITY in system.content, "a capability que falhou não chegou ao prompt"
    assert "falhou 2x" in system.content
    # O prompt original continua inteiro: o contexto soma, não substitui.
    assert DECOMPOSE_PROMPT in system.content


async def test_uma_falha_so_nao_entra_no_prompt(
    goal: Goal,
    fake_llm: FakeLLMProvider,
    goal_store: InMemoryGoalStore,
    tool_executor: RecordingToolExecutor,
) -> None:
    """Acidente não é padrão. Sem esta linha, o nível vira log de erros no prompt."""
    mem = memoria()
    manager = GoalManager(goal_store, tool_executor, fake_llm, memory=mem)
    fake_llm.queue_text("[]")

    await mem.on_task_failed(task_da(goal), ERRO_NAS)
    await manager.decompose_goal(goal)

    assert fake_llm.received[0][0].content == DECOMPOSE_PROMPT


async def test_sem_memoria_o_prompt_e_o_de_antes(
    goal: Goal,
    fake_llm: FakeLLMProvider,
    goal_store: InMemoryGoalStore,
    tool_executor: RecordingToolExecutor,
) -> None:
    """`memory=None` mantém o comportamento anterior à v1.3, byte a byte."""
    manager = GoalManager(goal_store, tool_executor, fake_llm)
    fake_llm.queue_text("[]")

    await manager.decompose_goal(goal)

    assert fake_llm.received[0][0].content == DECOMPOSE_PROMPT


# --------------------------------------------------------------------------- #
# Agrupamento — o que faz "repetida" significar alguma coisa
# --------------------------------------------------------------------------- #


async def test_mesmo_erro_com_numeros_diferentes_e_um_padrao_so(goal: Goal) -> None:
    """"timeout após 30s" e "timeout após 45s" são a mesma falha.

    Sem normalizar os números, cada ocorrência viraria um registro de uma
    ocorrência — e nenhum deles jamais alcançaria o limiar. O nível ficaria
    permanentemente vazio justamente para o erro mais comum que existe.
    """
    mem = memoria()
    assert mem.experience is not None

    await mem.on_task_failed(task_da(goal), "TimeoutError: timeout após 30s")
    await mem.on_task_failed(task_da(goal), "TimeoutError: timeout após 45s")

    padroes = await mem.experience.patterns()
    assert len(padroes) == 1
    assert padroes[0].occurrences == 2


async def test_capabilities_diferentes_nao_se_misturam(goal: Goal) -> None:
    """O assunto do registro é a capability. Somar falhas de duas seria mentira."""
    mem = memoria()
    assert mem.experience is not None

    await mem.on_task_failed(task_da(goal, capability="nas_sync"), ERRO_NAS)
    await mem.on_task_failed(task_da(goal, capability="cafeteira"), ERRO_NAS)

    assert await mem.experience.patterns() == []


async def test_evidencia_e_goal_de_origem_ficam_no_registro(goal: Goal) -> None:
    """O registro precisa levar a quem investiga de volta ao caso concreto."""
    mem = memoria()
    assert mem.experience is not None

    await mem.on_task_failed(task_da(goal), ERRO_NAS)
    await mem.on_task_failed(task_da(goal), ERRO_NAS)

    (registro,) = await mem.experience.patterns()
    assert ERRO_NAS in registro.evidence
    assert str(goal.id) in registro.goal_ids
    assert registro.subject == CAPABILITY


# --------------------------------------------------------------------------- #
# Contrapeso — o nível não pode ser só más notícias
# --------------------------------------------------------------------------- #


async def test_sucesso_e_registrado_mas_nao_polui_o_planejamento(goal: Goal) -> None:
    """Sucesso é contado (senão "falhou 3x" é meia-verdade), e fica fora do prompt.

    O planejador precisa saber o que evitar. "Funcionou 40x" não muda decisão
    nenhuma e gastaria contexto que é caro.
    """
    mem = memoria()
    assert mem.experience is not None

    for _ in range(3):
        await mem.on_task_succeeded(task_da(goal))

    registros = await mem.experience.all()
    (sucesso,) = [r for r in registros if r.kind is ExperienceKind.CAPABILITY_SUCCESS]
    assert sucesso.occurrences == 3
    assert await mem.experience.patterns() == []


async def test_preferencia_do_dono_entra_no_planejamento(goal: Goal) -> None:
    """O terceiro conteúdo do nível (`plan.md` §10) chega ao prompt como os outros."""
    mem = memoria(threshold=1)
    assert mem.experience is not None

    await mem.experience.record_owner_preference(
        "backup", "o dono prefere rodar backup depois da meia-noite"
    )

    contexto = await mem.planning_context(goal)
    assert "depois da meia-noite" in contexto


# --------------------------------------------------------------------------- #
# Efeitos colaterais e robustez
# --------------------------------------------------------------------------- #


async def test_promocao_a_padrao_e_anunciada_no_bus(goal: Goal) -> None:
    """A promoção é o fato observável: é quando o sistema passou a saber algo."""
    bus = InMemoryEventBus()
    mem = memoria(event_bus=bus)

    await mem.on_task_failed(task_da(goal), ERRO_NAS)
    await mem.on_task_failed(task_da(goal), ERRO_NAS)

    eventos = bus.of_type(EventType.MEMORY_UPDATED)
    assert len(eventos) == 2
    assert eventos[-1].payload["detail"] == "padrão promovido"
    assert eventos[-1].payload["count"] == 2


async def test_task_sem_capability_nao_cria_registro(goal: Goal) -> None:
    """Task que rodou direto no LLM não tem capability sobre a qual acumular.

    Inventar um nome ("llm") criaria padrão que ninguém consegue agir sobre.
    """
    mem = memoria()
    assert mem.experience is not None
    task = Task(goal_id=goal.id, title="responder")

    await mem.on_task_failed(task, ERRO_NAS)
    await mem.on_task_failed(task, ERRO_NAS)

    assert await mem.experience.all() == []


async def test_memoria_quebrada_nao_derruba_a_task(goal: Goal) -> None:
    """Regra da camada: erra-se mais por lembrar do que por esquecer.

    Um gancho que levanta transformaria disco cheio em falha de execução.
    """

    class StoreQuebrado(InMemoryExperienceStore):
        async def put(self, record: object) -> None:  # type: ignore[override]
            raise OSError("disco cheio")

    mem = MemorySystem(experience=ExperienceMemory(StoreQuebrado()))

    await mem.on_task_failed(task_da(goal), ERRO_NAS)  # não levanta
    assert await mem.planning_context(goal) == ""


def test_o_bloco_diz_o_que_fazer_com_a_informacao() -> None:
    """Lista sem instrução é lida como contexto decorativo."""
    assert render_experience_context([]) == ""
