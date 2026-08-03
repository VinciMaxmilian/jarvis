import asyncio
import base64
import json
import logging
import io
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
import webrtcvad
import edge_tts
from faster_whisper import WhisperModel
import openai
from pydub import AudioSegment

from packages.shared.settings import get_settings, Settings

logger = logging.getLogger("jarvis.voice")
router = APIRouter()

# Initialize whisper model once. "tiny" or "base" is good for speed vs accuracy.
# Note: In a production app, this should be initialized at startup.
try:
    logger.info("Loading Whisper model (tiny)...")
    whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
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
    
    if not settings.lmstudio_base_url:
        logger.error("LM Studio Base URL is not configured.")
        await websocket.close(code=1011, reason="LM Studio Base URL missing")
        return

    if not whisper_model:
        await websocket.close(code=1011, reason="Whisper STT model failed to load")
        return

    # Setup OpenAI Client for LM Studio
    client = openai.AsyncOpenAI(
        base_url=settings.lmstudio_base_url,
        api_key=settings.lmstudio_api_key or "lm-studio",
    )
    
    # Setup VAD (Voice Activity Detection) - 3 is the most aggressive filtering
    vad = webrtcvad.Vad(3)
    
    # Context (History)
    messages = [
        {"role": "system", "content": "Você é o Jarvis. Responda de forma concisa, direta, natural e conversacional em Português do Brasil, pois estamos em uma chamada de voz. Não use markdown (asteriscos, negritos, listas longas) pois sua resposta será lida por um sintetizador de voz (TTS). Mantenha as respostas curtas para não demorar a falar."}
    ]

    utterance_buffer = bytearray()
    frame_buffer = bytearray()
    silence_frames = 0
    is_speaking = False
    
    # We use a lock to ensure we don't process multiple TTS streams simultaneously
    processing_lock = asyncio.Lock()
    
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
                
                # 2. LLM Inference (LM Studio)
                messages.append({"role": "user", "content": text})
                logger.info("Sending prompt to LM Studio...")
                
                await websocket.send_json({"type": "text", "text": "**Jarvis:** "})
                response_text = ""
                
                stream = await client.chat.completions.create(
                    model=settings.lmstudio_model,
                    messages=messages,
                    stream=True,
                    max_tokens=200 # Keep it short for voice
                )
                
                async for chunk in stream:
                    content = chunk.choices[0].delta.content
                    if content:
                        response_text += content
                        # Send text tokens to UI
                        await websocket.send_json({"type": "text", "text": content})
                
                await websocket.send_json({"type": "text", "text": "\n"})
                messages.append({"role": "assistant", "content": response_text})
                
                logger.info(f"LLM Reply: {response_text}")
                
                # 3. Text to Speech (Edge-TTS)
                logger.info("Generating TTS with edge-tts...")
                communicate = edge_tts.Communicate(response_text, "pt-BR-AntonioNeural")
                
                mp3_io = io.BytesIO()
                async for tts_chunk in communicate.stream():
                    if tts_chunk["type"] == "audio":
                        mp3_io.write(tts_chunk["data"])
                
                mp3_io.seek(0)
                if mp3_io.getbuffer().nbytes > 0:
                    tts_segment = AudioSegment.from_file(mp3_io, format="mp3")
                    
                    # Convert to 24000Hz 16-bit mono to match frontend expectations
                    tts_segment = tts_segment.set_frame_rate(24000).set_channels(1).set_sample_width(2)
                    raw_data = tts_segment.raw_data
                    
                    # Stream chunks back to frontend
                    chunk_size = 4096 * 4
                    for i in range(0, len(raw_data), chunk_size):
                        chunk = raw_data[i:i+chunk_size]
                        b64_audio = base64.b64encode(chunk).decode('utf-8')
                        await websocket.send_json({
                            "type": "audio",
                            "data": b64_audio
                        })
                        await asyncio.sleep(0.005) # Yield to event loop
                        
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
        logger.error(f"Voice call error: {e}")
        try:
            await websocket.close(code=1011, reason="Internal error")
        except:
            pass
