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

    logger.info("Orchestrator v0.5 starting...")

    factory = get_session_factory()
    async with factory() as session:
        store = PgGoalStore(session)
        llm = await get_llm_provider(session)
        tools = await get_tool_executor(session)

        gm = GoalManager(goal_store=store, tool_executor=tools, llm=llm)
        executive = Executive(goal_manager=gm, goal_store=store)

        try:
            await executive.run()
        finally:
            await session.commit()

    await dispose_engine()
    logger.info("Orchestrator stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Orchestrator interrupted")