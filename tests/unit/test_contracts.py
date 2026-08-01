"""Invariantes dos contratos de `packages/shared/contracts.py`.

Os contratos são a fonte única: tabela do Postgres, schema do OpenAPI e código
gerado na v3 derivam deles. Mudar um valor de enum aqui quebra base de dados e
frontend juntos, então cada string de wire é fixada por asserção explícita, não
por leitura do arquivo.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.shared.contracts import (
    TERMINAL_GOAL_STATUS,
    TERMINAL_TASK_STATUS,
    CapabilityManifest,
    CapabilityStatus,
    EventType,
    Goal,
    GoalStatus,
    Task,
    TaskStatus,
    utcnow,
)

NON_TERMINAL_GOAL = (GoalStatus.DRAFT, GoalStatus.ACTIVE, GoalStatus.BLOCKED)
NON_TERMINAL_TASK = (
    TaskStatus.PENDING,
    TaskStatus.RUNNING,
    TaskStatus.WAITING_APPROVAL,
)

# Ordenados para que o id do caso no relatório do pytest não dependa da ordem de
# iteração do frozenset.
TERMINAL_GOAL: list[GoalStatus] = sorted(TERMINAL_GOAL_STATUS, key=lambda s: s.value)
TERMINAL_TASK: list[TaskStatus] = sorted(TERMINAL_TASK_STATUS, key=lambda s: s.value)


def _task(**kwargs: object) -> Task:
    """Task válida mínima; o `goal_id` é obrigatório e irrelevante aqui."""
    goal = Goal(title="goal de teste")
    return Task(goal_id=goal.id, title="task de teste", **kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Conjuntos terminais
# --------------------------------------------------------------------------- #


def test_terminal_goal_status_e_exatamente_done_failed_cancelled() -> None:
    assert (
        frozenset({GoalStatus.DONE, GoalStatus.FAILED, GoalStatus.CANCELLED})
        == TERMINAL_GOAL_STATUS
    )


def test_terminal_task_status_e_exatamente_done_failed_cancelled() -> None:
    assert (
        frozenset({TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED})
        == TERMINAL_TASK_STATUS
    )


def test_todo_goal_status_e_terminal_ou_nao_terminal() -> None:
    """Estado novo no enum sem classificação é buraco: não sabe se prossegue."""
    classificados = TERMINAL_GOAL_STATUS | frozenset(NON_TERMINAL_GOAL)
    assert classificados == frozenset(GoalStatus)


def test_todo_task_status_e_terminal_ou_nao_terminal() -> None:
    classificados = TERMINAL_TASK_STATUS | frozenset(NON_TERMINAL_TASK)
    assert classificados == frozenset(TaskStatus)


def test_conjuntos_terminais_sao_imutaveis() -> None:
    assert isinstance(TERMINAL_GOAL_STATUS, frozenset)
    assert isinstance(TERMINAL_TASK_STATUS, frozenset)
    with pytest.raises(AttributeError):
        TERMINAL_GOAL_STATUS.add(GoalStatus.DRAFT)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# is_terminal
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("status", TERMINAL_GOAL)
def test_goal_terminal_nao_transita(status: GoalStatus) -> None:
    assert Goal(title="g", status=status).is_terminal is True


@pytest.mark.parametrize("status", NON_TERMINAL_GOAL)
def test_goal_nao_terminal_ainda_transita(status: GoalStatus) -> None:
    assert Goal(title="g", status=status).is_terminal is False


@pytest.mark.parametrize("status", TERMINAL_TASK)
def test_task_terminal_nao_transita(status: TaskStatus) -> None:
    assert _task(status=status).is_terminal is True


@pytest.mark.parametrize("status", NON_TERMINAL_TASK)
def test_task_nao_terminal_ainda_transita(status: TaskStatus) -> None:
    assert _task(status=status).is_terminal is False


# --------------------------------------------------------------------------- #
# can_retry
# --------------------------------------------------------------------------- #


def test_can_retry_exige_status_failed() -> None:
    """`can_retry` fora de FAILED reagendaria task em andamento."""
    for status in (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.DONE):
        assert _task(status=status, attempts=1, max_attempts=3).can_retry is False


def test_can_retry_verdadeiro_com_tentativa_sobrando() -> None:
    assert _task(status=TaskStatus.FAILED, attempts=1, max_attempts=3).can_retry is True


def test_can_retry_falso_no_limite_de_tentativas() -> None:
    assert _task(status=TaskStatus.FAILED, attempts=3, max_attempts=3).can_retry is False


def test_can_retry_falso_acima_do_limite() -> None:
    assert _task(status=TaskStatus.FAILED, attempts=4, max_attempts=3).can_retry is False


def test_can_retry_falso_para_task_cancelada() -> None:
    assert (
        _task(status=TaskStatus.CANCELLED, attempts=0, max_attempts=3).can_retry is False
    )


# --------------------------------------------------------------------------- #
# Defaults e validação
# --------------------------------------------------------------------------- #


def test_goal_nasce_draft_com_prioridade_media() -> None:
    goal = Goal(title="g")
    assert (goal.status, goal.priority, goal.completed_at) == (GoalStatus.DRAFT, 50, None)


@pytest.mark.parametrize("priority", [-1, 101])
def test_goal_recusa_prioridade_fora_de_0_100(priority: int) -> None:
    with pytest.raises(ValidationError):
        Goal(title="g", priority=priority)


def test_task_nasce_pending_sem_tentativa_e_sem_dry_run() -> None:
    task = _task()
    assert (task.status, task.attempts, task.max_attempts, task.dry_run) == (
        TaskStatus.PENDING,
        0,
        3,
        False,
    )


def test_utcnow_tem_tzinfo_utc() -> None:
    """Timestamp naive em base com timezone é bug silencioso de 3 horas."""
    agora = utcnow()
    assert agora.tzinfo is not None
    assert agora.utcoffset() is not None
    assert agora.utcoffset().total_seconds() == 0  # type: ignore[union-attr]


# --------------------------------------------------------------------------- #
# Valores de wire
# --------------------------------------------------------------------------- #


def test_valores_de_goal_status_sao_o_contrato_de_wire() -> None:
    assert [s.value for s in GoalStatus] == [
        "draft",
        "active",
        "blocked",
        "done",
        "failed",
        "cancelled",
    ]


def test_valores_de_task_status_sao_o_contrato_de_wire() -> None:
    assert [s.value for s in TaskStatus] == [
        "pending",
        "running",
        "waiting_approval",
        "done",
        "failed",
        "cancelled",
    ]


def test_event_type_do_gap_e_o_nome_canonico() -> None:
    """`plan.md` §6: o miss do registry publica exatamente este tipo."""
    assert EventType.CAPABILITY_GAP_DETECTED == "capability.gap_detected"
    assert EventType.GOAL_BLOCKED == "goal.blocked"


# --------------------------------------------------------------------------- #
# CapabilityManifest.is_loadable
# --------------------------------------------------------------------------- #


def _manifest(status: CapabilityStatus) -> CapabilityManifest:
    return CapabilityManifest(
        name="cap_teste",
        version="0.1.0",
        description="capability de teste",
        status=status,
        entrypoint="capabilities.cap_teste.server:main",
    )


@pytest.mark.parametrize(
    ("status", "esperado"),
    [
        (CapabilityStatus.ACTIVE, True),
        (CapabilityStatus.APPROVED, False),
        (CapabilityStatus.PENDING_APPROVAL, False),
        (CapabilityStatus.DISABLED, False),
    ],
)
def test_is_loadable_so_para_active(status: CapabilityStatus, esperado: bool) -> None:
    assert _manifest(status).is_loadable is esperado


def test_manifest_nasce_pendente_de_aprovacao_e_sem_commit() -> None:
    """Default seguro: capability recém-descoberta não é carregável."""
    manifest = CapabilityManifest(
        name="cap_nova",
        version="0.1.0",
        description="recém-descoberta",
        entrypoint="capabilities.cap_nova.server:main",
    )
    assert manifest.status == CapabilityStatus.PENDING_APPROVAL
    assert manifest.approved_commit is None
    assert manifest.is_loadable is False
