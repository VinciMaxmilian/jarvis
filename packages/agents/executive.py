"""Executive Function — loop assíncrono que processa goals.

Consome goals ativos, delega ao GoalManager. Checkpoint = cada task DONE
é commit no Postgres. Kill no meio → restart lê o estado.
"""

from __future__ import annotations

import asyncio

import structlog

from packages.agents.goal_manager import GoalManager
from packages.shared.contracts import GoalStatus
from packages.shared.ports import GoalStore

logger = structlog.get_logger(__name__)


class Executive:
    """Loop de controle sobre goals ativos."""

    def __init__(
        self,
        goal_manager: GoalManager,
        goal_store: GoalStore,
        poll_interval: float = 5.0,
    ) -> None:
        self._gm = goal_manager
        self._store = goal_store
        self._poll_interval = poll_interval
        self._goal_queue: asyncio.Queue[str] = asyncio.Queue()
        self._running = False

    async def start(self) -> None:
        """Boot: resume interrupted goals, then enter poll loop."""
        self._running = True

        # Resume goals interrompidos por restart
        resumed = await self._gm.resume_active_goals()
        for gid in resumed:
            await self._goal_queue.put(str(gid))

        logger.info("executive.started", resumed_goals=len(resumed))

    async def enqueue_goal(self, goal_id: str) -> None:
        """Enfileira goal para processamento."""
        await self._goal_queue.put(goal_id)
        logger.info("executive.goal_enqueued", goal_id=goal_id)

    async def run(self) -> None:
        """Main loop: processa goals da fila + poll por novos."""
        await self.start()

        while self._running:
            try:
                # Tenta pegar da fila com timeout
                try:
                    goal_id_str = await asyncio.wait_for(
                        self._goal_queue.get(), timeout=self._poll_interval
                    )
                    from uuid import UUID
                    await self._gm.process_goal(UUID(goal_id_str))
                except TimeoutError:
                    pass

                # Poll: busca goals ACTIVE que talvez tenham tasks pendentes
                active = await self._store.list_goals(status=GoalStatus.ACTIVE)
                for goal in active:
                    tasks = await self._store.list_tasks(goal.id)
                    has_pending = any(
                        t.status.value in ("pending", "running") for t in tasks
                    )
                    if has_pending:
                        await self._gm.process_goal(goal.id)

            except asyncio.CancelledError:
                logger.info("executive.cancelled")
                break
            except Exception as exc:
                logger.error("executive.loop_error", error=str(exc))
                await asyncio.sleep(self._poll_interval)

    async def stop(self) -> None:
        self._running = False
        logger.info("executive.stopped")


__all__ = ["Executive"]
