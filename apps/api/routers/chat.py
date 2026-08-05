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
import structlog

from apps.api.db.repository import PgConversationStore
from apps.api.deps import get_chief_ai, get_db, get_llm_provider, get_chat_history_store
from packages.memory.indexer import index_conversation_message

router = APIRouter()

# Até esta versão o módulo não tinha logger nenhum, e as DUAS formas de uma
# mensagem falhar mandavam o texto do erro só para o navegador. O servidor não
# guardava cópia: no log, a mensagem simplesmente parava depois da indexação e
# do RAG, sem erro e sem traceback — indistinguível de uma mensagem que nunca
# chegou. Diagnosticar dependia de o dono ter lido o balão vermelho na tela.
logger = structlog.get_logger(__name__)


def _texto_do_erro(exc: BaseException) -> str:
    """Exceção → mensagem que serve num log e na tela do dono.

    `str()` de `WebSocketDisconnect` e de boa parte dos erros de transporte é
    VAZIO: o log saía `error=` e o balão de erro do PWA vinha em branco. O nome
    da classe sempre existe e já diz de que família é a falha.
    """
    texto = str(exc).strip()
    return f"{type(exc).__name__}: {texto}" if texto else type(exc).__name__


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
            images = data.get("images")
            files = data.get("files")
            
            if files:
                user_msg += "\n\n"
                for file_obj in files:
                    user_msg += f"=== Conteúdo do arquivo anexado: {file_obj.get('name', 'arquivo')} ===\n"
                    user_msg += f"{file_obj.get('content', '')}\n"

            # Nova session por mensagem. `get_db` é dependência do FastAPI e não
            # serve aqui: puxar dela com `anext()` abria um async generator que
            # ninguém fechava, vazando uma session por mensagem recebida.
            from apps.api.db.engine import get_session_factory
            async with get_session_factory()() as session:
                try:
                    chief = await get_chief_ai(session)
                    store = PgConversationStore(session)
                    await store.ensure_conversation(conv_id, title=data.get("message", "Nova Conversa"))

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
                    async for chunk in chief.respond(user_msg, conv_id, current_user_email=email, images=images):
                        payload: dict = {"type": chunk.type}
                        if chunk.type == "text":
                            payload["text"] = chunk.text
                        elif chunk.type == "tool_call" and chunk.tool_call:
                            if chunk.tool_call.name == "analyze_image":
                                img_url = chunk.tool_call.arguments.get("image_url")
                                # Só abre o visualizador para algo que o navegador
                                # consegue carregar. O modelo não recebe a imagem
                                # como URL (ela vai por `inlineData`), então
                                # quando resolve chamar esta tool ele INVENTA um
                                # nome — observado: `input_file_0.png`. O modal
                                # abria com src quebrado e virava um painel torto
                                # no canto da tela, sem imagem e sem explicação.
                                if isinstance(img_url, str) and img_url.startswith(
                                    ("http://", "https://", "data:", "/media/")
                                ):
                                    await websocket.send_text(json.dumps({"type": "image_analysis_started", "image_url": img_url}, default=str))
                                elif img_url:
                                    logger.info(
                                        "chat.ws.image_url_invalida",
                                        valor=str(img_url)[:120],
                                    )
                                    
                            payload["tool_call"] = {
                                "name": chunk.tool_call.name,
                                "arguments": chunk.tool_call.arguments,
                            }
                        elif chunk.type == "error":
                            # Caminho silencioso nº2, e o mais fácil de perder:
                            # isto NÃO passa pelo `except` abaixo. O provider
                            # devolve falha esperada como chunk, não como
                            # exceção — o timeout do Gemini
                            # (gemini_provider.py, read=180s) chega exatamente
                            # por aqui. Sem esta linha, um modelo que estourou o
                            # tempo é indistinguível no log de um que respondeu.
                            logger.error(
                                "chat.ws.stream_error",
                                conv_id=str(conv_id),
                                error=chunk.error,
                            )
                            payload["error"] = chunk.error
                        elif chunk.type == "done":
                            payload["conversation_id"] = str(conv_id)

                        await websocket.send_text(json.dumps(payload, default=str))

                    await session.commit()
                except WebSocketDisconnect:
                    # O navegador foi embora no meio do turno (aba fechada,
                    # recarregada, rede caiu). NÃO é falha do agente, e tentar
                    # responder num socket morto — que é o que o `except`
                    # genérico abaixo fazia — levanta uma SEGUNDA exceção que
                    # enterra a primeira. Sai como aviso, sem traceback.
                    await session.rollback()
                    logger.warning("chat.ws.cliente_desconectou", conv_id=str(conv_id))
                    return
                except Exception as exc:
                    await session.rollback()
                    # exc_info=True é o ponto todo: `str(exc)` de um
                    # ExceptionGroup rende "unhandled errors in a TaskGroup
                    # (1 sub-exception)", que é o mesmo texto inútil que o
                    # loader de MCP já produz. O traceback traz a sub-exceção.
                    #
                    # `_texto_do_erro` e não `str(exc)`: várias exceções de
                    # transporte (WebSocketDisconnect, RemoteProtocolError) têm
                    # `str()` VAZIO, e o log saía `error=` — um erro sem
                    # mensagem nenhuma, que foi o que escondeu a queda do
                    # WebSocket por dois testes seguidos.
                    detalhe = _texto_do_erro(exc)
                    logger.error(
                        "chat.ws.failed",
                        conv_id=str(conv_id),
                        error=detalhe,
                        exc_info=True,
                    )
                    # Avisar o dono é melhor esforço: se o socket já morreu, a
                    # tentativa falha e não há mais nada a fazer por este turno.
                    with contextlib.suppress(Exception):
                        await websocket.send_text(
                            json.dumps({"type": "error", "error": detalhe})
                        )

    except WebSocketDisconnect:
        pass
    except Exception:
        # O socket já pode estar morto: fechar de novo levanta e não há nada a
        # fazer com o erro — o handler está encerrando de qualquer forma.
        with contextlib.suppress(Exception):
            await websocket.close()
