"""Nível `working` — aceite 1 da v1.3 (`plan-execution.md` §3).

> "Matar o processo com task em andamento e retomar recupera o working memory
> do checkpoint."

O teste central deste arquivo mata um processo **de verdade**, com `SIGKILL`, no
meio de uma task, e prova que o processo seguinte lê do disco o plano, os
parciais e a tentativa que ficou aberta. Não é simulação: `kill -9` não executa
`finally`, não fecha arquivo e não roda `atexit` — é exatamente o modo de falha
que o nível `working` existe para cobrir, e o único jeito honesto de provar que a
escrita aconteceu **no checkpoint** e não na saída do processo é matando o
processo antes de qualquer saída.

O restante do arquivo cobre a semântica de que o aceite depende: uma tentativa
`STARTED` sem par é interrupção, não falha da capability, e o contexto devolvido
na retomada tem de dizer isso ao modelo.

Nada aqui toca rede: o nível `working` não usa embedding.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from packages.memory.models import AttemptOutcome, WorkingMemoryState
from packages.memory.stores import (
    InMemoryWorkingMemoryStore,
    JsonFileWorkingMemoryStore,
)
from packages.memory.system import MemorySystem
from packages.memory.working import WorkingMemory, render_working_context
from packages.shared.contracts import EventType, Task
from tests.conftest import InMemoryEventBus

REPO_ROOT = Path(__file__).resolve().parents[2]

#: O filho roda em processo separado, é morto no meio e nunca chega ao fim. Tudo
#: que ele escreve passa por `WorkingMemory.checkpoint`, que é o ponto em teste.
FILHO = """
import asyncio
import sys
from pathlib import Path
from uuid import UUID

from packages.memory.stores import JsonFileWorkingMemoryStore
from packages.memory.working import WorkingMemory
from packages.shared.contracts import Task


async def main() -> None:
    raiz = Path(sys.argv[1])
    task = Task(
        id=UUID(sys.argv[2]),
        goal_id=UUID(sys.argv[3]),
        title="restaurar o backup do NAS",
        capability="nas_backup",
        attempts=1,
    )
    memoria = WorkingMemory(JsonFileWorkingMemoryStore(raiz / "working"))
    await memoria.begin_attempt(task)
    await memoria.record_plan(
        task.id, ["acordar o NAS", "montar o share", "copiar os arquivos"]
    )
    await memoria.record_partial(task.id, "share montado", "/mnt/nas respondendo")

    # O checkpoint já está em disco neste ponto. O pai mata DEPOIS de ver isto,
    # então o kill cai com a task em andamento e sem nenhum bloco de saída.
    (raiz / "pronto").write_text("1", encoding="utf-8")
    while True:
        await asyncio.sleep(0.05)


asyncio.run(main())
"""


async def _matar_no_meio_da_task(raiz: Path, task_id: UUID, goal_id: UUID) -> int:
    """Sobe o filho, espera o checkpoint e o mata com `SIGKILL`. Devolve o código."""
    processo = subprocess.Popen(  # noqa: S603 — argv fixo, sem shell
        [sys.executable, "-c", FILHO, str(raiz), str(task_id), str(goal_id)],
        cwd=os.fspath(REPO_ROOT),
        env={**os.environ, "PYTHONPATH": os.fspath(REPO_ROOT)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    sinal = raiz / "pronto"
    try:
        for _ in range(600):  # 30s de teto: o filho só importa e escreve um JSON
            if sinal.exists():
                break
            if processo.poll() is not None:
                _, erro = processo.communicate()
                pytest.fail(
                    "o filho morreu antes do checkpoint "
                    f"(rc={processo.returncode}): {erro.decode(errors='replace')}"
                )
            await asyncio.sleep(0.05)
        else:  # pragma: no cover — só em máquina patologicamente lenta
            processo.kill()
            _, erro = processo.communicate()
            detalhe = erro.decode(errors="replace")
            pytest.fail(f"checkpoint não apareceu em 30s: {detalhe}")

        processo.kill()  # SIGKILL: nenhum finally, nenhum atexit, nenhum flush
        processo.communicate(timeout=30)
    finally:
        if processo.poll() is None:  # pragma: no cover — defesa contra teste pendurado
            processo.kill()
            processo.communicate(timeout=30)
    return processo.returncode


# --------------------------------------------------------------------------- #
# Aceite 1 — matar o processo e retomar
# --------------------------------------------------------------------------- #


async def test_kill_no_meio_da_task_e_retomada_recupera_o_checkpoint(
    tmp_path: Path,
) -> None:
    """ACEITE v1.3 (1): `kill -9` com task em andamento, e a retomada lê o disco.

    A asserção sobre `returncode` não é decoração: se o processo tivesse saído
    normalmente, o teste estaria provando que o dado sobrevive a um encerramento
    limpo — que é justamente o caso fácil, e não o requisito.
    """
    task_id, goal_id = uuid4(), uuid4()

    codigo = await _matar_no_meio_da_task(tmp_path, task_id, goal_id)

    if os.name == "posix":
        assert codigo == -signal.SIGKILL, (
            f"o filho saiu com {codigo}, não por SIGKILL — o teste não provou nada"
        )

    # O processo novo: outro objeto, outro store, o mesmo diretório.
    memoria = WorkingMemory(JsonFileWorkingMemoryStore(tmp_path / "working"))
    recuperado = await memoria.restore(task_id)

    assert recuperado is not None, "o checkpoint não sobreviveu ao kill"
    assert recuperado.task_id == task_id
    assert recuperado.goal_id == goal_id
    assert recuperado.plan == ["acordar o NAS", "montar o share", "copiar os arquivos"]
    assert [p.label for p in recuperado.partials] == ["share montado"]
    assert recuperado.partials[0].content == "/mnt/nas respondendo"

    # A tentativa que o kill pegou continua aberta — é o que distingue
    # "interrompida" de "falhou", e é o que a retomada precisa saber.
    interrompida = recuperado.interrupted_attempt
    assert interrompida is not None
    assert interrompida.capability == "nas_backup"
    assert recuperado.failures == []


async def test_retomada_devolve_o_contexto_do_que_ja_foi_tentado(
    tmp_path: Path,
) -> None:
    """A retomada não é só ler o arquivo: o estado tem de chegar ao prompt.

    Recuperar o checkpoint e não usá-lo seria o resume de antes da v1.3 — ele
    sabia *que* faltava fazer, não *o que já foi tentado*.
    """
    task_id, goal_id = uuid4(), uuid4()
    await _matar_no_meio_da_task(tmp_path, task_id, goal_id)

    memoria = MemorySystem(
        working=WorkingMemory(JsonFileWorkingMemoryStore(tmp_path / "working"))
    )
    task = Task(
        id=task_id,
        goal_id=goal_id,
        title="restaurar o backup do NAS",
        capability="nas_backup",
        attempts=2,
    )

    contexto = await memoria.on_task_started(task)

    assert "acordar o NAS" in contexto
    assert "share montado" in contexto
    assert "interrompida" in contexto
    assert "não conta como falha da capability" in contexto


async def test_checkpoint_do_kill_nao_conta_como_tentativa_nova(
    tmp_path: Path,
) -> None:
    """Retomar acrescenta uma tentativa; a interrompida continua lá, distinta."""
    task_id, goal_id = uuid4(), uuid4()
    await _matar_no_meio_da_task(tmp_path, task_id, goal_id)

    memoria = WorkingMemory(JsonFileWorkingMemoryStore(tmp_path / "working"))
    task = Task(
        id=task_id,
        goal_id=goal_id,
        title="restaurar",
        capability="nas_backup",
        attempts=2,
    )

    estado = await memoria.begin_attempt(task)

    assert [a.number for a in estado.attempts] == [1, 2]
    assert all(a.outcome is AttemptOutcome.STARTED for a in estado.attempts)
    assert estado.revision > 1, "o checkpoint da retomada não incrementou a revisão"


# --------------------------------------------------------------------------- #
# Durabilidade do adapter de disco
# --------------------------------------------------------------------------- #


async def test_escrita_e_atomica_e_nao_deixa_tmp_para_tras(tmp_path: Path) -> None:
    """`tmp` + `os.replace`: kill no meio da escrita não pode deixar JSON partido."""
    store = JsonFileWorkingMemoryStore(tmp_path)
    task_id, goal_id = uuid4(), uuid4()

    for i in range(5):
        await store.save(
            WorkingMemoryState(task_id=task_id, goal_id=goal_id, revision=i)
        )

    arquivos = sorted(p.name for p in tmp_path.iterdir())
    assert arquivos == [f"{task_id}.json"], f"lixo de escrita ficou para trás: {arquivos}"


async def test_arquivo_corrompido_devolve_none_em_vez_de_derrubar(
    tmp_path: Path,
) -> None:
    """Ler lixo é pior do que ler nada: a task recomeça sem contexto, mas sobe."""
    store = JsonFileWorkingMemoryStore(tmp_path)
    task_id = uuid4()
    (tmp_path / f"{task_id}.json").write_text("{isto não é json", encoding="utf-8")

    assert await store.load(task_id) is None


async def test_uma_task_nao_pisa_no_checkpoint_da_outra(tmp_path: Path) -> None:
    """Um arquivo por task: duas em paralelo no mesmo arquivo perderiam uma da outra."""
    store = JsonFileWorkingMemoryStore(tmp_path)
    goal_id = uuid4()
    a = WorkingMemoryState(task_id=uuid4(), goal_id=goal_id, title="task A")
    b = WorkingMemoryState(task_id=uuid4(), goal_id=goal_id, title="task B")

    await store.save(a)
    await store.save(b)

    assert (await store.load(a.task_id)) is not None
    assert (await store.load(a.task_id)).title == "task A"  # type: ignore[union-attr]
    assert (await store.load(b.task_id)).title == "task B"  # type: ignore[union-attr]


async def test_delete_diz_se_havia_algo(tmp_path: Path) -> None:
    store = JsonFileWorkingMemoryStore(tmp_path)
    estado = WorkingMemoryState(task_id=uuid4(), goal_id=uuid4())
    await store.save(estado)

    assert await store.delete(estado.task_id) is True
    assert await store.delete(estado.task_id) is False


# --------------------------------------------------------------------------- #
# Semântica do nível
# --------------------------------------------------------------------------- #


def _task(**kwargs: object) -> Task:
    base: dict[str, object] = {
        "goal_id": uuid4(),
        "title": "tarefa de teste",
        "capability": "nas_backup",
        "attempts": 1,
    }
    base.update(kwargs)
    return Task(**base)  # type: ignore[arg-type]


async def test_finish_attempt_fecha_a_tentativa_aberta() -> None:
    memoria = WorkingMemory(InMemoryWorkingMemoryStore())
    task = _task()
    await memoria.begin_attempt(task)

    estado = await memoria.finish_attempt(
        task, outcome=AttemptOutcome.FAILED, error="NAS em standby"
    )

    assert estado is not None
    assert estado.interrupted_attempt is None, "a tentativa continuou aberta"
    assert [a.outcome for a in estado.attempts] == [AttemptOutcome.FAILED]
    assert estado.attempts[0].error == "NAS em standby"


async def test_erro_gigante_e_truncado_antes_de_ir_para_o_prompt() -> None:
    """O estado inteiro entra na janela de contexto; um stacktrace de 1MB não cabe."""
    memoria = WorkingMemory(InMemoryWorkingMemoryStore())
    task = _task()
    await memoria.begin_attempt(task)

    estado = await memoria.finish_attempt(
        task, outcome=AttemptOutcome.FAILED, error="x" * 5000
    )

    assert estado is not None
    assert len(estado.attempts[0].error or "") == 400


async def test_historico_tem_teto() -> None:
    """Task que falha em laço não pode crescer até estourar a janela do modelo."""
    memoria = WorkingMemory(InMemoryWorkingMemoryStore(), max_attempts=3, max_partials=2)
    task = _task()

    for numero in range(1, 8):
        await memoria.begin_attempt(
            _task(id=task.id, goal_id=task.goal_id, attempts=numero)
        )
        await memoria.record_partial(task.id, f"parcial {numero}", "conteúdo")

    estado = await memoria.restore(task.id)

    assert estado is not None
    assert len(estado.attempts) == 3
    assert [p.label for p in estado.partials] == ["parcial 6", "parcial 7"]


async def test_record_plan_em_task_desconhecida_e_no_op() -> None:
    """Sem estado gravado não há o que atualizar — e memória não levanta."""
    memoria = WorkingMemory(InMemoryWorkingMemoryStore())

    await memoria.record_plan(uuid4(), ["passo"])  # não levanta

    assert await memoria.restore(uuid4()) is None


async def test_checkpoint_publica_memory_updated(event_bus: InMemoryEventBus) -> None:
    memoria = WorkingMemory(InMemoryWorkingMemoryStore(), event_bus=event_bus)
    task = _task()

    await memoria.begin_attempt(task)

    eventos = event_bus.of_type(EventType.MEMORY_UPDATED)
    assert len(eventos) == 1
    assert eventos[0].payload["level"] == "working"
    assert eventos[0].task_id == task.id
    assert eventos[0].goal_id == task.goal_id


async def test_clear_descarta_o_estado() -> None:
    """A vida útil do nível é a da task (`plan.md` §10)."""
    memoria = WorkingMemory(InMemoryWorkingMemoryStore())
    task = _task()
    await memoria.begin_attempt(task)

    assert await memoria.clear(task.id) is True
    assert await memoria.restore(task.id) is None


# --------------------------------------------------------------------------- #
# Renderização para o prompt
# --------------------------------------------------------------------------- #


def test_contexto_vazio_para_estado_vazio() -> None:
    """Sem nada a dizer, o bloco não existe — string vazia não polui o prompt."""
    estado = WorkingMemoryState(task_id=uuid4(), goal_id=uuid4())

    assert render_working_context(estado) == ""


async def test_contexto_separa_falha_de_interrupcao() -> None:
    """A distinção é o ponto do nível: interrupção não é falha da capability."""
    memoria = WorkingMemory(InMemoryWorkingMemoryStore())
    task = _task()
    await memoria.begin_attempt(task)
    await memoria.finish_attempt(task, outcome=AttemptOutcome.FAILED, error="sem rota")
    await memoria.begin_attempt(_task(id=task.id, goal_id=task.goal_id, attempts=2))

    estado = await memoria.restore(task.id)
    assert estado is not None
    texto = render_working_context(estado)

    assert "sem rota" in texto
    assert "não conta como falha da capability" in texto


def test_contexto_respeita_o_teto_de_caracteres() -> None:
    estado = WorkingMemoryState(
        task_id=uuid4(), goal_id=uuid4(), plan=[f"passo {i}" for i in range(500)]
    )

    assert len(render_working_context(estado, max_chars=200)) == 200
