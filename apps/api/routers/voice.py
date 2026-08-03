import asyncio
import base64
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from google import genai
from google.genai import types

from packages.shared.settings import get_settings, Settings

logger = logging.getLogger("jarvis.voice")
router = APIRouter()

@router.websocket("/call")
async def voice_call_endpoint(websocket: WebSocket, settings: Settings = Depends(get_settings)):
    await websocket.accept()
    
    if not settings.gemini_api_key:
        logger.error("Gemini API key is not configured.")
        await websocket.close(code=1011, reason="Gemini API Key missing")
        return

    client = genai.Client(api_key=settings.gemini_api_key)
    model = "gemini-3.1-flash-live-preview" 
    
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(parts=[types.Part.from_text(text="Você é o Jarvis. Responda de forma muito concisa, natural e conversacional, pois estamos em uma chamada de voz em tempo real. Se o usuário pedir para desligar, encerrar chamada, tchau, ou similar, despeça-se brevemente e chame a ferramenta end_call.")]),
        tools=[types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="end_call",
                    description="Encerra a chamada de voz atual.",
                )
            ]
        )]
    )

    try:
        async with client.aio.live.connect(model=model, config=config) as session:
            
            async def receive_from_frontend():
                try:
                    while True:
                        data = await websocket.receive_text()
                        payload = json.loads(data)
                        
                        if payload.get("type") == "realtime_input" and "media_chunks" in payload:
                            for chunk in payload["media_chunks"]:
                                b64_data = chunk.get("data")
                                mime = chunk.get("mime_type", "audio/pcm;rate=16000")
                                if b64_data:
                                    decoded_audio = base64.b64decode(b64_data)
                                    logger.info(f"Sending audio chunk to Gemini, size {len(decoded_audio)}")
                                    await session.send(input=types.LiveClientRealtimeInput(audio=types.Blob(data=decoded_audio, mime_type=mime)))
                        elif payload.get("type") == "client_content":
                            turns = payload.get("turns", [])
                            for turn in turns:
                                await session.send(input=turn)
                except WebSocketDisconnect:
                    logger.info("Frontend websocket disconnected")
                except Exception as e:
                    logger.error(f"Error reading from frontend: {e}")
            
            async def receive_from_gemini():
                try:
                    async for response in session.receive():
                        server_content = response.server_content
                        if server_content is not None:
                            model_turn = server_content.model_turn
                            if model_turn is not None:
                                logger.info(f"Gemini replied with parts: {len(model_turn.parts)}")
                                for part in model_turn.parts:
                                    if part.inline_data:
                                        b64_audio = base64.b64encode(part.inline_data.data).decode('utf-8')
                                        await websocket.send_json({
                                            "type": "audio",
                                            "data": b64_audio,
                                            "mime_type": part.inline_data.mime_type
                                        })
                                    if part.text:
                                        logger.info(f"Gemini text: {part.text}")
                                        await websocket.send_json({
                                            "type": "text",
                                            "text": part.text
                                        })
                                    if part.function_call:
                                        if part.function_call.name == "end_call":
                                            await websocket.send_json({
                                                "type": "call_ended_by_agent"
                                            })
                                            # We can't close here directly easily without cancelling, 
                                            # the client will close the connection when receiving this.
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"Error receiving from Gemini: {e}")

            task1 = asyncio.create_task(receive_from_frontend())
            task2 = asyncio.create_task(receive_from_gemini())
            
            done, pending = await asyncio.wait(
                [task1, task2],
                return_when=asyncio.FIRST_COMPLETED
            )
            for p in pending:
                p.cancel()
                
    except WebSocketDisconnect:
        logger.info("Websocket disconnected cleanly.")
    except Exception as e:
        logger.error(f"Voice call error: {e}")
        try:
            await websocket.close(code=1011, reason="Internal error")
        except:
            pass
