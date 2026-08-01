"""CRUD de Goals e Tasks + execute + SSE — v0.5.

Persistência real em Postgres. Execute dispara GoalManager.
SSE fornece estado ao vivo.
"""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.repository import PgGoalStore
from apps.api.deps import get_db, get_llm_provider, get_tool_executor
from packages.agents.goal_manager import GoalManager
from packages.shared.contracts import Goal, GoalStatus, Task

router = APIRouter()


class CreateGoalRequest(BaseModel):
    title: str
    description: str = ""
    priority: int = 50


class UpdateGoalStatusRequest(BaseModel):
    status: GoalStatus


# --- Goals ----------------------------------------------------------------- #


@router.post("/", response_model=Goal)
async def create_goal(
    request: CreateGoalRequest,
    session: AsyncSession = Depends(get_db),
) -> Goal:
    store = PgGoalStore(session)
    goal = Goal(
        title=request.title,
        description=request.description,
        priority=request.priority,
    )
    return await store.create_goal(goal)


@router.get("/", response_model=list[Goal])
async def list_goals(
    status: GoalStatus | None = None,
    session: AsyncSession = Depends(get_db),
) -> list[Goal]:
    store = PgGoalStore(session)
    return await store.list_goals(status=status)


@router.get("/{goal_id}", response_model=Goal)
async def get_goal(
    goal_id: UUID,
    session: AsyncSession = Depends(get_db),
) -> Goal:
    store = PgGoalStore(session)
    goal = await store.get_goal(goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    return goal


@router.patch("/{goal_id}/status", response_model=Goal)
async def update_goal_status(
    goal_id: UUID,
    request: UpdateGoalStatusRequest,
    session: AsyncSession = Depends(get_db),
) -> Goal:
    store = PgGoalStore(session)
    goal = await store.update_goal_status(goal_id, request.status)
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    return goal


# --- Tasks ----------------------------------------------------------------- #


@router.get("/{goal_id}/tasks", response_model=list[Task])
async def list_tasks(
    goal_id: UUID,
    session: AsyncSession = Depends(get_db),
) -> list[Task]:
    store = PgGoalStore(session)
    return await store.list_tasks(goal_id)


# --- Execute Goal ---------------------------------------------------------- #


@router.post("/{goal_id}/execute", response_model=Goal)
async def execute_goal(
    goal_id: UUID,
    session: AsyncSession = Depends(get_db),
) -> Goal:
    """Dispara execução do goal (decomposição + tasks em sequência)."""
    store = PgGoalStore(session)
    goal = await store.get_goal(goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")

    llm = await get_llm_provider(session)
    tools = get_tool_executor()
    gm = GoalManager(goal_store=store, tool_executor=tools, llm=llm)

    result = await gm.process_goal(goal_id)
    await session.commit()

    if result is None:
        raise HTTPException(status_code=500, detail="Goal processing failed")
    return result


# --- SSE (estado ao vivo) -------------------------------------------------- #


@router.get("/{goal_id}/stream")
async def stream_goal_status(
    goal_id: UUID,
    session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """SSE: emite estado do goal e tasks a cada 2s."""
    store = PgGoalStore(session)

    async def event_generator():
        for _ in range(300):  # max 10 min
            goal = await store.get_goal(goal_id)
            if goal is None:
                yield f"data: {json.dumps({'error': 'not found'})}\n\n"
                return

            tasks = await store.list_tasks(goal_id)
            payload = {
                "goal": goal.model_dump(mode="json"),
                "tasks": [t.model_dump(mode="json") for t in tasks],
            }
            yield f"data: {json.dumps(payload, default=str)}\n\n"

            if goal.is_terminal:
                return

            await asyncio.sleep(2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
