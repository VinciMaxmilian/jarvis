"""Orchestrator v0.5 — Executive Function + GoalManager.

Instancia o loop de processamento de goals. Resume interrupted goals on boot.
Sem imports quebrados.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

# Garante que a raiz do monorepo está no path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
)
logger = logging.getLogger("jarvis.orchestrator")


async def main() -> None:
    """Boot: cria deps, resume goals, entra no loop."""
    from apps.api.db.engine import dispose_engine, get_session_factory
    from apps.api.db.repository import PgGoalStore
    from apps.api.deps import get_llm_provider, get_tool_executor
    from packages.agents.executive import Executive
    from packages.agents.goal_manager import GoalManager

    from packages.memory.factory import build_memory_system
    
    from packages.kernel.event_bus.in_proc import InProcEventBus
    from packages.kernel.event_bus.redis_bus import RedisEventBus
    from packages.registry.registry import CapabilityRegistry
    from apps.api.db.repository import PgCapabilityStore
    from packages.registry.gap import GoalBlocker
    from packages.kernel.kernel import Kernel
    from packages.kernel.runtime.python_runtime import PythonRuntime
    from packages.scheduler.jobs import SchedulerManager
    from packages.shared.settings import Settings

    logger.info("Orchestrator v0.5 starting...")

    settings = Settings()
    factory = get_session_factory()
    
    if settings.redis_url:
        bus = RedisEventBus(redis_url=str(settings.redis_url), consumer_name="orchestrator_1")
        logger.info("Usando RedisEventBus")
    else:
        bus = InProcEventBus()
        logger.info("Usando InProcEventBus")
        
    cap_dir = os.path.join(os.path.dirname(__file__), "..", "capabilities")
    registry = CapabilityRegistry(base_dir=cap_dir, event_bus=bus)
    registry.discover()
    
    async with factory() as session:
        store = PgGoalStore(session)
        cap_store = PgCapabilityStore(session)
        
        await registry.hydrate(cap_store)
        
        llm = await get_llm_provider(session)
        memory = build_memory_system(llm)

        kernel = Kernel(adapters=[PythonRuntime()], event_bus=bus)

        blocker = GoalBlocker(store)
        bus.subscribe(blocker, types=["capability.gap_detected"])
        
        scheduler = SchedulerManager.from_database_url(
            settings.database_url,
            event_bus=bus,
        )

        gm = GoalManager(goal_store=store, tool_executor=kernel, llm=llm, memory=memory, registry=registry)
        executive = Executive(goal_manager=gm, goal_store=store)

        await bus.start()
        scheduler.start()

        try:
            await executive.run()
        finally:
            scheduler.stop()
            await bus.stop()
            await session.commit()

    await dispose_engine()
    logger.info("Orchestrator stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Orchestrator interrupted")