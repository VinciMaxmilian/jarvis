"""Resume após restart (`plan.md` §5).

O critério é o do checkpoint: matar o processo com uma task concluída e outra
pendente e voltar **da pendente**, sem repetir a concluída. Repetir uma task
`done` é o pior modo de falha desta camada — a task já teve efeito no mundo.

Roda inteiro sobre os dublês em memória: o "restart" aqui é construir uma
Executive nova sobre o mesmo store, que é exatamente o que o processo faz ao
subir contra o mesmo Postgres.
"""

from __future__ import annotations

from packages.agents.executive import Executive
from packages.agents.goal_manager import GoalManager
from packages.shared.contracts import Goal, GoalStatus, Task, TaskStatus
from tests.conftest import (
    FakeLLMProvider,
    InMemoryGoalStore,
    RecordingToolExecutor,
)


async def _goal_meio_caminho(
    store: InMemoryGoalStore,
) -> tuple[Goal, Task, Task]:
    """Goal ACTIVE com a task A `done` e a task B `pending`, B dependendo de A."""
    goal = await store.create_goal(
        Goal(title="goal interrompido", status=GoalStatus.ACTIVE)
    )
    a = Task(
        goal_id=goal.id,
        title="A já concluída",
        status=TaskStatus.DONE,
        attempts=1,
        output={"response": "resultado da A"},
    )
    b = Task(goal_id=goal.id, title="B pendente", depends_on=[a.id])
    await store.create_tasks([a, b])
    return goal, a, b


def _montar(
    store: InMemoryGoalStore, llm: FakeLLMProvider, tools: RecordingToolExecutor
) -> tuple[GoalManager, Executive]:
    gm = GoalManager(goal_store=store, tool_executor=tools, llm=llm)
    return gm, Executive(goal_manager=gm, goal_store=store, poll_interval=0.01)


# --------------------------------------------------------------------------- #
# resume_active_goals()
# --------------------------------------------------------------------------- #


async def test_resume_encontra_goal_com_task_pendente(
    goal_store: InMemoryGoalStore,
    fake_llm: FakeLLMProvider,
    tool_executor: RecordingToolExecutor,
) -> None:
    goal, _a, _b = await _goal_meio_caminho(goal_store)
    gm, _ = _montar(goal_store, fake_llm, tool_executor)

    assert await gm.resume_active_goals() == [goal.id]


async def test_resume_ignora_goal_com_todas_as_tasks_done(
    goal_store: InMemoryGoalStore,
    fake_llm: FakeLLMProvider,
    tool_executor: RecordingToolExecutor,
) -> None:
    goal, _a, b = await _goal_meio_caminho(goal_store)
    b.status = TaskStatus.DONE
    await goal_store.update_task(b)
    gm, _ = _montar(goal_store, fake_llm, tool_executor)

    assert await gm.resume_active_goals() == []


async def test_resume_ignora_goal_nao_active(
    goal_store: InMemoryGoalStore,
    fake_llm: FakeLLMProvider,
    tool_executor: RecordingToolExecutor,
) -> None:
    """Goal `blocked` espera o dono; retomar sozinho anularia o bloqueio."""
    goal, _a, _b = await _goal_meio_caminho(goal_store)
    await goal_store.update_goal_status(goal.id, GoalStatus.BLOCKED)
    gm, _ = _montar(goal_store, fake_llm, tool_executor)

    assert await gm.resume_active_goals() == []


async def test_resume_devolve_task_running_para_pending(
    goal_store: InMemoryGoalStore,
    fake_llm: FakeLLMProvider,
    tool_executor: RecordingToolExecutor,
) -> None:
    """Task `running` no momento do kill não tem quem a termine: volta à fila."""
    goal, _a, b = await _goal_meio_caminho(goal_store)
    b.status = TaskStatus.RUNNING
    b.started_at = b.created_at
    await goal_store.update_task(b)
    gm, _ = _montar(goal_store, fake_llm, tool_executor)

    assert await gm.resume_active_goals() == [goal.id]

    recarregada = await goal_store.get_task(b.id)
    assert recarregada is not None
    assert recarregada.status == TaskStatus.PENDING
    assert recarregada.started_at is None


async def test_resume_nao_mexe_na_task_done(
    goal_store: InMemoryGoalStore,
    fake_llm: FakeLLMProvider,
    tool_executor: RecordingToolExecutor,
) -> None:
    goal, a, _b = await _goal_meio_caminho(goal_store)
    gm, _ = _montar(goal_store, fake_llm, tool_executor)

    await gm.resume_active_goals()

    recarregada = await goal_store.get_task(a.id)
    assert recarregada is not None
    assert recarregada.status == TaskStatus.DONE
    assert recarregada.attempts == 1
    assert recarregada.output == {"response": "resultado da A"}
    assert goal.id == recarregada.goal_id


# --------------------------------------------------------------------------- #
# Retomada efetiva
# --------------------------------------------------------------------------- #


async def test_retoma_da_pendente_sem_repetir_a_concluida(
    goal_store: InMemoryGoalStore,
    tool_executor: RecordingToolExecutor,
) -> None:
    goal, a, b = await _goal_meio_caminho(goal_store)
    llm = FakeLLMProvider().queue_text("resultado da B")
    gm, _ = _montar(goal_store, llm, tool_executor)

    await gm.resume_active_goals()
    await gm.process_goal(goal.id)

    # Uma única execução: a task B. A task A não foi reexecutada.
    assert llm.complete_calls == 1
    assert llm.received[0][-1].content == "B pendente"

    recarregada_a = await goal_store.get_task(a.id)
    recarregada_b = await goal_store.get_task(b.id)
    assert recarregada_a is not None and recarregada_b is not None
    assert recarregada_a.attempts == 1
    assert recarregada_a.output == {"response": "resultado da A"}
    assert recarregada_b.status == TaskStatus.DONE
    assert recarregada_b.output == {"response": "resultado da B"}


async def test_goal_vai_para_done_quando_a_ultima_task_termina(
    goal_store: InMemoryGoalStore,
    tool_executor: RecordingToolExecutor,
) -> None:
    goal, _a, _b = await _goal_meio_caminho(goal_store)
    llm = FakeLLMProvider().queue_text("resultado da B")
    gm, _ = _montar(goal_store, llm, tool_executor)

    final = await gm.process_goal(goal.id)

    assert final is not None
    assert final.status == GoalStatus.DONE
    assert final.completed_at is not None


async def test_process_goal_nao_redecompoe_goal_que_ja_tem_tasks(
    goal_store: InMemoryGoalStore,
    tool_executor: RecordingToolExecutor,
) -> None:
    """Decompor de novo duplicaria a fila a cada restart."""
    goal, _a, _b = await _goal_meio_caminho(goal_store)
    llm = FakeLLMProvider().queue_text("resultado da B")
    gm, _ = _montar(goal_store, llm, tool_executor)

    await gm.process_goal(goal.id)

    assert len(await goal_store.list_tasks(goal.id)) == 2


async def test_task_com_tool_declarada_vai_ao_tool_executor(
    goal_store: InMemoryGoalStore,
    fake_llm: FakeLLMProvider,
    tool_executor: RecordingToolExecutor,
) -> None:
    """Quem executa é a porta, nunca o LLM (`plan.md` §4)."""
    goal = await goal_store.create_goal(Goal(title="com tool", status=GoalStatus.ACTIVE))
    await goal_store.create_tasks(
        [
            Task(
                goal_id=goal.id,
                title="buscar na web",
                tool="web_search",
                input={"q": "jarvis"},
            )
        ]
    )
    gm, _ = _montar(goal_store, fake_llm, tool_executor)

    await gm.process_goal(goal.id)

    assert tool_executor.calls == [("web_search", {"q": "jarvis"}, False)]
    assert fake_llm.complete_calls == 0


# --------------------------------------------------------------------------- #
# Boot da Executive
# --------------------------------------------------------------------------- #


async def test_start_enfileira_os_goals_retomados(
    goal_store: InMemoryGoalStore,
    fake_llm: FakeLLMProvider,
    tool_executor: RecordingToolExecutor,
) -> None:
    """`Executive` só expõe a fila em atributo privado; é ela que provou o boot."""
    await _goal_meio_caminho(goal_store)
    _, executive = _montar(goal_store, fake_llm, tool_executor)

    await executive.start()

    assert executive._goal_queue.qsize() == 1


async def test_start_sem_goal_ativo_deixa_a_fila_vazia(
    goal_store: InMemoryGoalStore,
    fake_llm: FakeLLMProvider,
    tool_executor: RecordingToolExecutor,
) -> None:
    _, executive = _montar(goal_store, fake_llm, tool_executor)

    await executive.start()

    assert executive._goal_queue.qsize() == 0


async def test_enqueue_goal_aceita_id_em_texto(
    goal_store: InMemoryGoalStore,
    fake_llm: FakeLLMProvider,
    tool_executor: RecordingToolExecutor,
) -> None:
    goal, _a, _b = await _goal_meio_caminho(goal_store)
    _, executive = _montar(goal_store, fake_llm, tool_executor)

    await executive.enqueue_goal(str(goal.id))

    assert executive._goal_queue.qsize() == 1
