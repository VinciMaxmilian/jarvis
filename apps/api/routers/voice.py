import asyncio
import base64
import contextlib
import json
import logging
import io
from uuid import uuid4
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
import webrtcvad
from faster_whisper import WhisperModel
from pydub import AudioSegment

from apps.api.deps import get_voice_ai
from packages.shared.settings import get_settings, Settings
from packages.voice import fillers
from packages.voice.sentences import SentenceBuffer
from packages.voice.speaker import Locutor
from packages.voice.tts import make_tts

logger = logging.getLogger("jarvis.voice")
router = APIRouter()

# Initialize whisper model once. "tiny" or "base" is good for speed vs accuracy.
# Note: In a production app, this should be initialized at startup.
try:
    logger.info("Loading Whisper model (tiny)...")
    # "base" e não "tiny": o `tiny` transcrevia mal demais em português — num
    # teste real ele produziu "o que é baba do youtube premium 4" para uma
    # pergunta sobre o YouTube Premium, e o agente foi buscar exatamente isso na
    # web. Erro de STT não degrada elegantemente: ele vira uma pergunta DIFERENTE,
    # respondida com confiança. `base` custa mais CPU por fala (a transcrição
    # roda uma vez por turno, não em streaming) e é o próximo degrau sensato num
    # i5-3470 — `small` já pesaria demais nesta máquina.
    whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
except Exception as e:
    logger.error(f"Failed to load Whisper model: {e}")
    whisper_model = None


def pcm16_to_audio_segment(pcm_data: bytes, sample_rate: int = 16000) -> AudioSegment:
    """Converts raw PCM16 bytes into a Pydub AudioSegment."""
    return AudioSegment(
        data=pcm_data,
        sample_width=2,
        frame_rate=sample_rate,
        channels=1
    )


@router.websocket("/call")
async def voice_call_endpoint(websocket: WebSocket, settings: Settings = Depends(get_settings)):
    await websocket.accept()
    
    if not whisper_model:
        await websocket.close(code=1011, reason="Whisper STT model failed to load")
        return

    # Setup VAD (Voice Activity Detection) - 3 is the most aggressive filtering
    vad = webrtcvad.Vad(3)

    # Síntese. O provider vem do .env e SEMPRE tem o edge-tts como rede — ver
    # packages/voice/tts.py. Construído uma vez por chamada, não por frase.
    tts = make_tts(
        settings.tts_provider,
        gemini_api_key=settings.gemini_api_key,
        **({"gemini_model": settings.tts_gemini_model} if settings.tts_gemini_model else {}),
        **({"gemini_voice": settings.tts_gemini_voice} if settings.tts_gemini_voice else {}),
        edge_voice=settings.tts_edge_voice,
    )

    async def _enviar_audio(pcm: bytes) -> None:
        await websocket.send_json(
            {"type": "audio", "data": base64.b64encode(pcm).decode("utf-8")}
        )

    locutor = Locutor(tts, _enviar_audio)
    await locutor.iniciar()

    # Uma conversa por chamada. Como o `ChiefAI` persiste pelo ConversationStore,
    # o que for falado aqui aparece no histórico do chat de texto — antes desta
    # versão os dois eram universos separados.
    conv_id = uuid4()

    utterance_buffer = bytearray()
    frame_buffer = bytearray()
    silence_frames = 0
    is_speaking = False
    
    # We use a lock to ensure we don't process multiple TTS streams simultaneously
    processing_lock = asyncio.Lock()
    
    async def _falar_preenchimento(tool_name: str) -> None:
        """Fala "deixa eu procurar" se a ferramenta demorar — responder, agir,
        responder de novo.

        O atraso é o ponto todo: `ChiefAI` emite o chunk de `tool_call` ANTES de
        executar, então aqui não se sabe quanto a ferramenta vai levar. Esperar
        `ATRASO_ANTES_DE_FALAR` e só então falar resolve isso sem adivinhação —
        se a ferramenta responder rápido, quem chama cancela esta tarefa e nada é
        dito. Falar por cima de uma tool de 200 ms ADICIONARIA latência em vez de
        escondê-la.
        """
        try:
            await asyncio.sleep(fillers.ATRASO_ANTES_DE_FALAR)
        except asyncio.CancelledError:
            return
        frase = fillers.escolher(tool_name)
        logger.info("voice.filler", tool=tool_name, frase=frase)
        # Vai para o locutor, mas NUNCA para o histórico: é artefato de
        # interface, não fala do assistente. No histórico, envenenaria o contexto
        # das próximas respostas.
        await websocket.send_json({"type": "text", "text": frase + " "})
        locutor.dizer(frase)

    async def process_user_speech(audio_data: bytes):
        if processing_lock.locked():
            logger.info("Already processing speech, ignoring overlapping utterance.")
            return

        async with processing_lock:
            logger.info(f"Processing audio utterance of size {len(audio_data)} bytes...")
            try:
                # 1. Speech to Text (Faster Whisper)
                # Convert PCM to WAV for whisper
                segment = pcm16_to_audio_segment(audio_data, 16000)
                wav_io = io.BytesIO()
                segment.export(wav_io, format="wav")
                wav_io.seek(0)
                
                # Transcribe
                segments, _ = whisper_model.transcribe(wav_io, beam_size=1, language="pt")
                text = "".join(s.text for s in segments).strip()
                
                if not text:
                    logger.info("Whisper returned empty text.")
                    return

                logger.info(f"STT Output: {text}")
                
                # Notify frontend of what we heard
                await websocket.send_json({"type": "text", "text": f"\n**Você:** {text}\n"})
                
                # 2. O JARVIS DE VERDADE.
                #
                # Até esta versão, aqui havia uma chamada crua ao LM Studio com
                # uma lista de mensagens local e SEM o parâmetro `tools` — a
                # conversa falada não tinha web_search, search_memory, MCP,
                # memória nem histórico. Era um assistente à parte que se
                # apresentava como Jarvis. Agora é o mesmo agente do chat, sob o
                # perfil `voice` (prompt sem markdown, frases curtas).
                #
                # Sessão própria por fala, e não uma de vida longa: o `ChiefAI`
                # escreve no banco, e segurar uma sessão aberta pela duração da
                # chamada inteira prenderia uma conexão do pool por todo o tempo
                # em que o dono estiver ao telefone.
                from apps.api.db.engine import get_session_factory

                await websocket.send_json({"type": "text", "text": "**Jarvis:** "})

                # 3. Pipeline por frase.
                #
                # O buffer entrega frases fechadas conforme os tokens chegam, e o
                # locutor sintetiza e envia NA ORDEM enquanto o modelo ainda
                # escreve o resto. É daqui que vem o ganho de latência: o
                # primeiro som sai depois da primeira frase, não depois da
                # resposta inteira.
                buffer = SentenceBuffer()
                filler_task: asyncio.Task | None = None

                async with get_session_factory()() as session:
                    chief = await get_voice_ai(session)

                    async for chunk in chief.respond(text, conv_id):
                        if chunk.type == "text" and chunk.text:
                            # Chegou texto: a ferramenta (se havia) já respondeu.
                            # Cancelar o preenchimento pendente — falar "deixa eu
                            # procurar" agora seria falar por cima da resposta.
                            if filler_task and not filler_task.done():
                                filler_task.cancel()
                                filler_task = None

                            await websocket.send_json(
                                {"type": "text", "text": chunk.text}
                            )
                            for frase in buffer.feed(chunk.text):
                                locutor.dizer(frase)

                        elif chunk.type == "tool_call" and chunk.tool_call:
                            logger.info("voice.tool_call: %s", chunk.tool_call.name)
                            # O que estiver pendente no buffer vai para o áudio
                            # ANTES do preenchimento, senão a ordem inverte.
                            for frase in buffer.flush():
                                locutor.dizer(frase)
                            if filler_task and not filler_task.done():
                                filler_task.cancel()
                            filler_task = asyncio.create_task(
                                _falar_preenchimento(chunk.tool_call.name)
                            )

                        elif chunk.type == "error" and chunk.error:
                            logger.error("voice.chief.error: %s", chunk.error)
                            await websocket.send_json(
                                {"type": "error", "error": chunk.error}
                            )

                    await session.commit()

                if filler_task and not filler_task.done():
                    filler_task.cancel()

                # `flush()` é obrigatório: a última frase costuma não ter
                # pontuação terminal e, sem isto, seria descartada em silêncio —
                # o assistente pareceria engolir o final de toda resposta.
                for frase in buffer.flush():
                    locutor.dizer(frase)

                await websocket.send_json({"type": "text", "text": "\n"})
                await locutor.drenar()
                logger.info("TTS transmission complete.")
                
            except Exception as e:
                logger.error(f"Error processing speech/TTS: {e}", exc_info=True)

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            
            if payload.get("type") == "realtime_input" and "media_chunks" in payload:
                for chunk in payload["media_chunks"]:
                    b64_data = chunk.get("data")
                    if b64_data:
                        decoded_audio = base64.b64decode(b64_data)
                        frame_buffer.extend(decoded_audio)
                        
                        # Process 30ms frames (16000Hz * 2 bytes * 0.03 = 960 bytes)
                        frame_size = 960
                        while len(frame_buffer) >= frame_size:
                            frame = bytes(frame_buffer[:frame_size])
                            frame_buffer = frame_buffer[frame_size:]
                            
                            try:
                                is_speech = vad.is_speech(frame, 16000)
                            except Exception as e:
                                is_speech = False
                                
                            if is_speech:
                                silence_frames = 0
                                is_speaking = True
                                utterance_buffer.extend(frame)
                            else:
                                if is_speaking:
                                    silence_frames += 1
                                    utterance_buffer.extend(frame)
                                    
                                    # ~1.2 seconds of silence = 40 frames of 30ms
                                    if silence_frames > 40:
                                        is_speaking = False
                                        silence_frames = 0
                                        # Only process if we have at least 0.5s of audio (16000 bytes)
                                        if len(utterance_buffer) > 16000: 
                                            audio_to_process = bytes(utterance_buffer)
                                            asyncio.create_task(process_user_speech(audio_to_process))
                                            
                                        utterance_buffer.clear()
                                        
            elif payload.get("type") == "client_content":
                # Handle text messages coming from the UI just like voice
                turns = payload.get("turns", [])
                for turn in turns:
                    if hasattr(turn, "parts") and turn.parts:
                        for part in turn.parts:
                            if hasattr(part, "text") and part.text:
                                asyncio.create_task(process_user_speech(b"")) # we need a text overload or just log it
                                # To keep it simple, we ignore text input during voice calls, 
                                # since the voice UI expects only voice.
                pass
                
    except WebSocketDisconnect:
        logger.info("Websocket disconnected cleanly.")
    except Exception as e:
        logger.error(f"Voice call error: {e}", exc_info=True)
        try:
            await websocket.close(code=1011, reason="Internal error")
        except Exception:
            pass
    finally:
        # O locutor é uma tarefa de fundo com fila própria: sem isto ela ficaria
        # viva depois que o dono desligar, sintetizando e tentando enviar por um
        # WebSocket fechado. `finally` porque vale para saída limpa e para erro.
        with contextlib.suppress(Exception):
            await locutor.parar()
