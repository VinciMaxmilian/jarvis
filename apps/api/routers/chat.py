"""Rota de chat com streaming via WebSocket.

O fluxo real: WebSocket → Chief AI → LLM → tool calls → streaming de volta.
Fallback HTTP POST para clientes sem WS.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.repository import PgConversationStore
from apps.api.deps import get_chief_ai, get_db, get_llm_provider, get_chat_history_store
from packages.memory.indexer import index_conversation_message

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    conversation_id: UUID | None = None


class ChatResponse(BaseModel):
    reply: str
    conversation_id: UUID


@router.post("/", response_model=ChatResponse)
async def chat_post(
    request: Request,
    body: ChatRequest,
    session: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """Chat síncrono (sem streaming). Útil para testes rápidos."""
    conv_id = body.conversation_id or uuid4()
    chief = await get_chief_ai(session)
    
    email = request.scope.get("cf_access_claims", {}).get("email", "Usuário Local")

    if body.message.strip():
        history_store = get_chat_history_store()
        asyncio.create_task(
            index_conversation_message(
                message_text=body.message,
                conversation_id=conv_id,
                message_id=uuid4().hex,
                provider=chief._embed_llm,
                vector_store=history_store,
                source=email
            )
        )

    full_text = ""
    async for chunk in chief.respond(body.message, conv_id, current_user_email=email):
        if chunk.type == "text":
            full_text += chunk.text

    await session.commit()
    return ChatResponse(reply=full_text, conversation_id=conv_id)


@router.websocket("/ws")
async def chat_ws(websocket: WebSocket) -> None:
    """WebSocket streaming. Protocolo:
    
    Client → JSON: {"message": "...", "conversation_id": "..."}
    Server → JSON chunks: {"type": "text", "text": "..."} | {"type": "done"}
                          | {"type": "error", ...}
    """
    await websocket.accept()

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            user_msg = data.get("message", "")
            conv_id = (
                UUID(data["conversation_id"]) if data.get("conversation_id") else uuid4()
            )

            # Nova session por mensagem. `get_db` é dependência do FastAPI e não
            # serve aqui: puxar dela com `anext()` abria um async generator que
            # ninguém fechava, vazando uma session por mensagem recebida.
            from apps.api.db.engine import get_session_factory
            async with get_session_factory()() as session:
                try:
                    chief = await get_chief_ai(session)
                    store = PgConversationStore(session)
                    await store.ensure_conversation(conv_id, title=user_msg)

                    email = websocket.scope.get("cf_access_claims", {}).get("email", "Usuário Local")
                    
                    # Indexação assíncrona (fogo e esquece) do user_msg
                    if user_msg.strip():
                        history_store = get_chat_history_store()
                        asyncio.create_task(
                            index_conversation_message(
                                message_text=user_msg,
                                conversation_id=conv_id,
                                message_id=uuid4().hex,
                                provider=chief._embed_llm,
                                vector_store=history_store,
                                source=email
                            )
                        )
                    async for chunk in chief.respond(user_msg, conv_id, current_user_email=email):
                        payload: dict = {"type": chunk.type}
                        if chunk.type == "text":
                            payload["text"] = chunk.text
                        elif chunk.type == "tool_call" and chunk.tool_call:
                            payload["tool_call"] = {
                                "name": chunk.tool_call.name,
                                "arguments": chunk.tool_call.arguments,
                            }
                        elif chunk.type == "error":
                            payload["error"] = chunk.error
                        elif chunk.type == "done":
                            payload["conversation_id"] = str(conv_id)

                        await websocket.send_text(json.dumps(payload, default=str))

                    await session.commit()
                except Exception as exc:
                    await session.rollback()
                    await websocket.send_text(
                        json.dumps({"type": "error", "error": str(exc)})
                    )

    except WebSocketDisconnect:
        pass
    except Exception:
        # O socket já pode estar morto: fechar de novo levanta e não há nada a
        # fazer com o erro — o handler está encerrando de qualquer forma.
        with contextlib.suppress(Exception):
            await websocket.close()
