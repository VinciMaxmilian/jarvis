"""O que acontece depois de um miss em `resolve()` (D-2).

`plan.md` §6 lista três consequências do miss, nesta ordem: a tarefa para, o
registry emite `CapabilityGapDetected` e o objetivo pai vai para `blocked`.

O registry **publica**; quem move o goal é um consumidor do evento
(`GoalBlocker`), não uma chamada direta de dentro do `resolve()`. Três razões:

1. `plan-execution.md` §7 — "módulos conversam por evento, não por chamada".
   Registry com `GoalStore` no construtor amarra o catálogo à persistência de
   objetivos, e a próxima consequência do gap (notificação no celular, SPEC da
   v3.0) viraria o terceiro parâmetro do mesmo construtor.
2. `resolve()` é síncrono — o Chief AI o chama no meio do planejamento — e
   gravar goal é I/O. Publicar é o único jeito de o miss não bloquear a decisão.
3. O bus ganha um consumidor de verdade (D-12), não só um publisher.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import structlog

from packages.shared.contracts import Event, EventType, GoalStatus
from packages.shared.ports import GoalStore

logger = structlog.get_logger(__name__)

#: Emissor do evento, gravado em `Event.source`.
FONTE = "packages.registry"


def gap_event(
    intent: str,
    *,
    context: str = "",
    goal_id: UUID | None = None,
    task_id: UUID | None = None,
    trace_id: str | None = None,
    candidatos: int = 0,
    source: str = FONTE,
) -> Event:
    """Monta o `capability.gap_detected` de um miss.

    `candidatos` é quantas capabilities `active` existiam quando o miss
    aconteceu: "não achei entre zero" é catálogo vazio, "não achei entre doze" é
    lacuna de verdade, e a v3.0 precisa dos dois separados para escrever a SPEC.
    """
    payload: dict[str, Any] = {
        "intent": intent,
        "context": context,
        "candidatos_ativos": candidatos,
    }
    return Event(
        type=EventType.CAPABILITY_GAP_DETECTED,
        source=source,
        payload=payload,
        goal_id=goal_id,
        task_id=task_id,
        trace_id=trace_id or uuid4().hex,
    )


class GoalBlocker:
    """Consumidor de `capability.gap_detected`: move o goal pai para `blocked`.

    Assine em um `EventBus` com `types=[EventType.CAPABILITY_GAP_DETECTED]`.
    """

    def __init__(self, goal_store: GoalStore) -> None:
        self._store = goal_store

    async def __call__(self, event: Event) -> None:
        if event.goal_id is None:
            # Miss sem goal é chamada de fora do ciclo de objetivos (chat solto).
            # Não há o que bloquear; o evento continua servindo à v3.0.
            logger.info(
                "capability.gap_sem_goal",
                intent=event.payload.get("intent"),
                trace_id=event.trace_id,
            )
            return

        goal = await self._store.update_goal_status(event.goal_id, GoalStatus.BLOCKED)
        if goal is None:
            logger.error(
                "capability.gap_goal_inexistente",
                goal_id=str(event.goal_id),
                trace_id=event.trace_id,
            )
            return

        logger.warning(
            "goal.blocked",
            goal_id=str(goal.id),
            motivo="capability_gap",
            intent=event.payload.get("intent"),
            trace_id=event.trace_id,
        )


__all__ = ["FONTE", "GoalBlocker", "gap_event"]
