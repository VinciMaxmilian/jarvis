"""Rota de tools — lista tools registradas."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_tool_executor, get_db

router = APIRouter()


@router.get("")
async def list_tools(session: AsyncSession = Depends(get_db)) -> list[dict]:
    """Retorna lista de tools disponíveis."""
    executor = await get_tool_executor(session)
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "idempotent": spec.idempotent,
            "requires_approval": spec.requires_approval,
        }
        for spec in executor.specs()
    ]
