"""Router para histórico de chats e estatísticas de uso."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.models import ChatMessageRow, ConversationRow
from apps.api.deps import get_db

router = APIRouter(tags=["history"])


class ChatPreview(BaseModel):
    id: UUID
    title: str
    created_at: str
    updated_at: str
    message_count: int
    preview_text: str


class ModelStats(BaseModel):
    model: str
    input_tokens: int
    output_tokens: int


class ToolUsage(BaseModel):
    tool: str
    count: int


class StatsResponse(BaseModel):
    models: list[ModelStats]
    tools: list[ToolUsage]


@router.get("/chats", response_model=list[ChatPreview])
async def get_chats(session: AsyncSession = Depends(get_db)) -> list[ChatPreview]:
    """Retorna os chats mais recentes com preview."""
    stmt = select(ConversationRow).order_by(desc(ConversationRow.updated_at)).limit(50)
    result = await session.execute(stmt)
    conversations = result.scalars().all()

    out = []
    for conv in conversations:
        # Pega a primeira mensagem do usuário para usar de preview
        msg_stmt = (
            select(ChatMessageRow)
            .where(ChatMessageRow.conversation_id == conv.id)
            .where(ChatMessageRow.role == "user")
            .order_by(ChatMessageRow.created_at)
            .limit(1)
        )
        msg_res = await session.execute(msg_stmt)
        first_msg = msg_res.scalar_one_or_none()

        # Conta mensagens totais
        count_stmt = select(func.count(ChatMessageRow.id)).where(
            ChatMessageRow.conversation_id == conv.id
        )
        count_res = await session.execute(count_stmt)
        msg_count = count_res.scalar() or 0

        out.append(
            ChatPreview(
                id=conv.id,
                title=conv.title or "Nova Conversa",
                created_at=conv.created_at.isoformat(),
                updated_at=conv.updated_at.isoformat(),
                message_count=msg_count,
                preview_text=first_msg.content[:100] if first_msg else "Sem mensagens",
            )
        )

    return out


class ChatMessageResponse(BaseModel):
    id: UUID
    role: str
    content: str
    created_at: str
    tool_calls: list | None = None

@router.get("/chats/{conversation_id}/messages", response_model=list[ChatMessageResponse])
async def get_chat_messages(
    conversation_id: UUID,
    session: AsyncSession = Depends(get_db)
) -> list[ChatMessageResponse]:
    """Retorna as mensagens de um chat específico."""
    stmt = (
        select(ChatMessageRow)
        .where(ChatMessageRow.conversation_id == conversation_id)
        .order_by(ChatMessageRow.created_at)
        .limit(100)
    )
    result = await session.execute(stmt)
    
    out = []
    for msg in result.scalars().all():
        out.append(ChatMessageResponse(
            id=msg.id,
            role=msg.role,
            content=msg.content,
            created_at=msg.created_at.isoformat(),
            tool_calls=msg.tool_calls
        ))
    return out


@router.get("/stats", response_model=StatsResponse)
async def get_stats(session: AsyncSession = Depends(get_db)) -> StatsResponse:
    """Estatísticas de uso de modelos e ferramentas."""
    
    # 1. Uso de tokens por modelo
    model_stmt = (
        select(
            ChatMessageRow.model,
            func.sum(ChatMessageRow.input_tokens).label("in_tokens"),
            func.sum(ChatMessageRow.output_tokens).label("out_tokens"),
        )
        .where(ChatMessageRow.model.is_not(None))
        .where(ChatMessageRow.model != "")
        .group_by(ChatMessageRow.model)
        .order_by(desc("out_tokens"))
    )
    model_res = await session.execute(model_stmt)
    models = [
        ModelStats(
            model=r.model,
            input_tokens=r.in_tokens or 0,
            output_tokens=r.out_tokens or 0,
        )
        for r in model_res.all()
    ]

    # 2. Uso de ferramentas
    tools_stmt = (
        select(ChatMessageRow.tool_calls)
        .where(ChatMessageRow.role == "assistant")
    )
    tools_res = await session.execute(tools_stmt)
    
    tool_counts: dict[str, int] = {}
    for (tool_calls,) in tools_res.all():
        if not tool_calls:
            continue
        for call in tool_calls:
            name = call.get("name")
            if name:
                tool_counts[name] = tool_counts.get(name, 0) + 1

    sorted_tools = sorted(
        [ToolUsage(tool=k, count=v) for k, v in tool_counts.items()],
        key=lambda x: x.count,
        reverse=True,
    )

    return StatsResponse(models=models, tools=sorted_tools)
