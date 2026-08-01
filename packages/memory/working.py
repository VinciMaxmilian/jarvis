"""Nível `working` — estado vivo da task, gravado no checkpoint.

`plan.md` §10: "estado da tarefa em execução: plano, resultados parciais, o que
já foi tentado; duração da tarefa; **persistido no checkpoint**".

O checkpoint já existe: é o `update_task` que `GoalManager.execute_next_task`
faz em cada transição. O que faltava era gravar, no mesmo ponto, o que não cabe
em `Task` — as tentativas com o motivo de cada falha e os parciais produzidos
antes da interrupção. Sem isso, o resume de hoje retoma a task certa e recomeça
do zero: ele sabe *que* faltava fazer, não sabe *o que já foi tentado*.

Escrever em disco a cada checkpoint, e não ao final: o modo de falha que este
nível existe para cobrir é `kill -9`, e um `kill -9` não executa nenhum bloco de
saída.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID, uuid4

import structlog

from packages.memory.models import (
    Attempt,
    AttemptOutcome,
    MemoryLevel,
    MemoryUpdate,
    PartialResult,
    WorkingMemoryState,
)
from packages.memory.ports import WorkingMemoryStore
from packages.shared.contracts import Event, EventType, Task, utcnow
from packages.shared.ports import EventBus

logger = structlog.get_logger(__name__)

#: Teto de itens guardados por estado. O working memory vai para dentro de um
#: prompt: sem teto, uma task que falha em laço cresce até estourar a janela de
#: contexto — e o modelo local desta máquina tem janela curta.
MAX_ATTEMPTS = 20
MAX_PARTIALS = 20
MAX_ERROR_CHARS = 400


class WorkingMemory:
    """Estado vivo da task, com persistência a cada checkpoint."""

    def __init__(
        self,
        store: WorkingMemoryStore,
        *,
        event_bus: EventBus | None = None,
        max_attempts: int = MAX_ATTEMPTS,
        max_partials: int = MAX_PARTIALS,
    ) -> None:
        self._store = store
        self._bus = event_bus
        self._max_attempts = max_attempts
        self._max_partials = max_partials

    # -- leitura ---------------------------------------------------------- #

    async def restore(self, task_id: UUID) -> WorkingMemoryState | None:
        """Estado gravado no último checkpoint, ou `None` se a task é nova."""
        return await self._store.load(task_id)

    # -- escrita ---------------------------------------------------------- #

    async def begin_attempt(self, task: Task) -> WorkingMemoryState:
        """Registra o início de uma tentativa e faz checkpoint.

        Devolve o estado **já com** a tentativa nova. Quem quer saber o que havia
        antes chama `restore()` primeiro — é a diferença entre "o que já foi
        tentado" e "o que estou tentando agora".
        """
        estado = await self._store.load(task.id) or WorkingMemoryState(
            task_id=task.id, goal_id=task.goal_id, title=task.title
        )
        estado.attempts.append(
            Attempt(
                number=task.attempts,
                outcome=AttemptOutcome.STARTED,
                capability=task.capability,
                tool=task.tool,
            )
        )
        return await self.checkpoint(estado)

    async def record_plan(self, task_id: UUID, plan: Sequence[str]) -> None:
        """Grava o plano da task. Sobrescreve: plano é um, não histórico."""
        estado = await self._store.load(task_id)
        if estado is None:
            return
        estado.plan = list(plan)
        await self.checkpoint(estado)

    async def record_partial(self, task_id: UUID, label: str, content: str) -> None:
        """Resultado parcial: o que a task já produziu e não quer refazer."""
        estado = await self._store.load(task_id)
        if estado is None:
            return
        estado.partials.append(PartialResult(label=label, content=content))
        await self.checkpoint(estado)

    async def finish_attempt(
        self, task: Task, *, outcome: AttemptOutcome, error: str | None = None
    ) -> WorkingMemoryState | None:
        """Fecha a tentativa aberta com o desfecho, e faz checkpoint.

        Fechar a tentativa é o que distingue "falhou" de "morreu no meio": uma
        tentativa que ficou `STARTED` sem par é a que o kill pegou, e o resume
        precisa dessa distinção para não contar interrupção como falha da
        capability.
        """
        estado = await self._store.load(task.id)
        if estado is None:
            return None
        aberta = estado.interrupted_attempt
        if aberta is None:
            aberta = Attempt(number=task.attempts, capability=task.capability)
            estado.attempts.append(aberta)
        aberta.outcome = outcome
        aberta.at = utcnow()
        if error:
            aberta.error = error[:MAX_ERROR_CHARS]
        return await self.checkpoint(estado)

    async def checkpoint(self, state: WorkingMemoryState) -> WorkingMemoryState:
        """Persiste o estado. É o mesmo instante do `update_task` do GoalManager."""
        state.attempts = state.attempts[-self._max_attempts :]
        state.partials = state.partials[-self._max_partials :]
        state.revision += 1
        state.updated_at = utcnow()
        await self._store.save(state)
        await self._publicar(state)
        return state

    async def clear(self, task_id: UUID) -> bool:
        """Descarta o estado. A vida útil do nível é a da task (`plan.md` §10)."""
        apagado = await self._store.delete(task_id)
        if apagado:
            logger.debug("memory.working.limpo", task_id=str(task_id))
        return apagado

    # -- interno ---------------------------------------------------------- #

    async def _publicar(self, state: WorkingMemoryState) -> None:
        if self._bus is None:
            return
        update = MemoryUpdate(
            level=MemoryLevel.WORKING,
            subject=str(state.task_id),
            detail=f"revisão {state.revision}",
            count=len(state.attempts),
        )
        await self._bus.publish(
            Event(
                type=EventType.MEMORY_UPDATED,
                source="packages.memory.working",
                payload=update.model_dump(mode="json"),
                goal_id=state.goal_id,
                task_id=state.task_id,
                trace_id=uuid4().hex,
            )
        )


def render_working_context(state: WorkingMemoryState, *, max_chars: int = 1200) -> str:
    """Formata o estado recuperado para entrar no prompt da retomada.

    Texto, e não JSON, porque o destino é a janela de contexto de um modelo de 2B
    — JSON gasta token em pontuação que o modelo não precisa ler.
    """
    linhas: list[str] = []
    if state.plan:
        linhas.append("Plano registrado antes da interrupção:")
        linhas.extend(f"- {passo}" for passo in state.plan)
    if state.partials:
        linhas.append("Resultados parciais já obtidos (não refaça):")
        linhas.extend(f"- {p.label}: {p.content}" for p in state.partials)

    fechadas = [a for a in state.attempts if a.outcome is not AttemptOutcome.STARTED]
    if fechadas:
        linhas.append("O que já foi tentado:")
        for attempt in fechadas:
            alvo = attempt.capability or attempt.tool or "execução direta"
            motivo = f" — {attempt.error}" if attempt.error else ""
            linhas.append(
                f"- tentativa {attempt.number} ({alvo}): {attempt.outcome}{motivo}"
            )

    interrompida = state.interrupted_attempt
    if interrompida is not None:
        linhas.append(
            f"A tentativa {interrompida.number} foi interrompida antes de terminar "
            "(o processo morreu); ela não conta como falha da capability."
        )

    if not linhas:
        return ""
    texto = "\n".join(linhas)
    return texto[:max_chars]


__all__ = ["WorkingMemory", "render_working_context"]
