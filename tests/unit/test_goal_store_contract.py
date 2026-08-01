"""Contrato de `GoalStore.next_pending_task`.

A porta documenta uma frase: "primeira tarefa `pending` cujas dependências já
estão `done`". Toda a fila serial da Executive Function depende disso — se a
ordem vazar, a task B roda com o resultado da A ainda inexistente. Os testes
valem para qualquer implementação da porta; aqui rodam sobre o dublê em memória.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from packages.shared.contracts import Goal, GoalStatus, Task, TaskStatus
from tests.conftest import InMemoryGoalStore


async def _goal_com_cadeia(
    store: InMemoryGoalStore,
) -> tuple[Goal, Task, Task, Task]:
    """Cria A → B → C: B depende de A, C depende de B."""
    goal = await store.create_goal(Goal(title="cadeia", status=GoalStatus.ACTIVE))
    a = Task(goal_id=goal.id, title="A")
    b = Task(goal_id=goal.id, title="B", depends_on=[a.id])
    c = Task(goal_id=goal.id, title="C", depends_on=[b.id])
    await store.create_tasks([a, b, c])
    return goal, a, b, c


async def _concluir(store: InMemoryGoalStore, task: Task) -> None:
    task.status = TaskStatus.DONE
    await store.update_task(task)


# --------------------------------------------------------------------------- #
# Ordem por dependência
# --------------------------------------------------------------------------- #


async def test_cadeia_a_b_c_libera_uma_por_vez_na_ordem(
    goal_store: InMemoryGoalStore,
) -> None:
    goal, a, b, c = await _goal_com_cadeia(goal_store)

    primeira = await goal_store.next_pending_task(goal.id)
    assert primeira is not None and primeira.id == a.id

    await _concluir(goal_store, a)
    segunda = await goal_store.next_pending_task(goal.id)
    assert segunda is not None and segunda.id == b.id

    await _concluir(goal_store, b)
    terceira = await goal_store.next_pending_task(goal.id)
    assert terceira is not None and terceira.id == c.id

    await _concluir(goal_store, c)
    assert await goal_store.next_pending_task(goal.id) is None


async def test_dependencia_pendente_nao_libera_a_dependente(
    goal_store: InMemoryGoalStore,
) -> None:
    """C nunca aparece antes de B, mesmo com A concluída."""
    goal, a, b, c = await _goal_com_cadeia(goal_store)
    await _concluir(goal_store, a)

    for _ in range(3):
        proxima = await goal_store.next_pending_task(goal.id)
        assert proxima is not None and proxima.id != c.id


async def test_dependencia_failed_nao_conta_como_satisfeita(
    goal_store: InMemoryGoalStore,
) -> None:
    """Só `done` libera. `failed` travando a fila é o comportamento correto."""
    goal, a, b, _c = await _goal_com_cadeia(goal_store)
    a.status = TaskStatus.FAILED
    a.attempts = 3
    await goal_store.update_task(a)

    assert await goal_store.next_pending_task(goal.id) is None


async def test_dependencia_running_nao_conta_como_satisfeita(
    goal_store: InMemoryGoalStore,
) -> None:
    goal, a, _b, _c = await _goal_com_cadeia(goal_store)
    a.status = TaskStatus.RUNNING
    await goal_store.update_task(a)

    assert await goal_store.next_pending_task(goal.id) is None


async def test_task_com_multiplas_dependencias_espera_todas(
    goal_store: InMemoryGoalStore,
) -> None:
    goal = await goal_store.create_goal(Goal(title="fan-in", status=GoalStatus.ACTIVE))
    a = Task(goal_id=goal.id, title="A")
    b = Task(goal_id=goal.id, title="B")
    c = Task(goal_id=goal.id, title="C", depends_on=[a.id, b.id])
    await goal_store.create_tasks([a, b, c])

    await _concluir(goal_store, a)
    proxima = await goal_store.next_pending_task(goal.id)
    assert proxima is not None and proxima.id == b.id  # C ainda espera B

    await _concluir(goal_store, b)
    proxima = await goal_store.next_pending_task(goal.id)
    assert proxima is not None and proxima.id == c.id


# --------------------------------------------------------------------------- #
# Casos de borda
# --------------------------------------------------------------------------- #


async def test_goal_sem_tasks_retorna_none(goal_store: InMemoryGoalStore) -> None:
    goal = await goal_store.create_goal(Goal(title="vazio"))
    assert await goal_store.list_tasks(goal.id) == []
    assert await goal_store.next_pending_task(goal.id) is None


async def test_goal_inexistente_retorna_none(
    goal_store: InMemoryGoalStore, goal_id: UUID
) -> None:
    assert await goal_store.next_pending_task(goal_id) is None


async def test_tasks_independentes_saem_em_ordem_de_criacao(
    goal_store: InMemoryGoalStore,
) -> None:
    """Sem dependência, a fila é serial e estável — não arbitrária."""
    goal = await goal_store.create_goal(Goal(title="paralelas"))
    tasks = [Task(goal_id=goal.id, title=f"T{i}") for i in range(3)]
    await goal_store.create_tasks(tasks)

    for esperada in tasks:
        proxima = await goal_store.next_pending_task(goal.id)
        assert proxima is not None and proxima.id == esperada.id
        await _concluir(goal_store, proxima)


async def test_dependencia_para_task_inexistente_nunca_libera(
    goal_store: InMemoryGoalStore,
) -> None:
    """Dependência órfã bloqueia em vez de rodar sem o pré-requisito."""
    goal = await goal_store.create_goal(Goal(title="órfã"))
    await goal_store.create_tasks(
        [Task(goal_id=goal.id, title="A", depends_on=[uuid4()])]
    )

    assert await goal_store.next_pending_task(goal.id) is None


async def test_tasks_de_outro_goal_nao_vazam(goal_store: InMemoryGoalStore) -> None:
    outro = await goal_store.create_goal(Goal(title="outro"))
    alvo = await goal_store.create_goal(Goal(title="alvo"))
    await goal_store.create_tasks([Task(goal_id=outro.id, title="do outro goal")])

    assert await goal_store.next_pending_task(alvo.id) is None


# --------------------------------------------------------------------------- #
# Isolamento de escrita
# --------------------------------------------------------------------------- #


async def test_mutacao_sem_update_nao_persiste(goal_store: InMemoryGoalStore) -> None:
    """Igual ao adaptador Postgres: sem `update_task` nada foi commitado."""
    goal = await goal_store.create_goal(Goal(title="checkpoint"))
    task = Task(goal_id=goal.id, title="A")
    await goal_store.create_tasks([task])

    task.status = TaskStatus.DONE  # só na instância em memória do chamador
    recarregada = await goal_store.get_task(task.id)
    assert recarregada is not None and recarregada.status == TaskStatus.PENDING


async def test_update_task_desconhecida_falha_alto(
    goal_store: InMemoryGoalStore, goal_id: UUID
) -> None:
    with pytest.raises(ValueError):
        await goal_store.update_task(Task(goal_id=goal_id, title="fantasma"))


async def test_list_goals_filtra_por_status(goal_store: InMemoryGoalStore) -> None:
    await goal_store.create_goal(Goal(title="ativo", status=GoalStatus.ACTIVE))
    await goal_store.create_goal(Goal(title="rascunho", status=GoalStatus.DRAFT))

    ativos = await goal_store.list_goals(status=GoalStatus.ACTIVE)
    assert [g.title for g in ativos] == ["ativo"]
    assert len(await goal_store.list_goals()) == 2


async def test_update_goal_status_marca_completed_at_em_done(
    goal_store: InMemoryGoalStore,
) -> None:
    goal = await goal_store.create_goal(Goal(title="g", status=GoalStatus.ACTIVE))
    atualizado = await goal_store.update_goal_status(goal.id, GoalStatus.DONE)

    assert atualizado is not None
    assert atualizado.status == GoalStatus.DONE
    assert atualizado.completed_at is not None
