"""Síntese de voz (TTS) como port, com adaptadores trocáveis.

**O contrato de áudio é único e não negociável: PCM 16-bit little-endian, mono,
24 kHz.** É o que o player do PWA já consome, e fixar isso no port é o que faz
trocar de fornecedor não virar mudança no cliente. Cada adaptador é responsável
por entregar nesse formato — quem não entrega nativamente, converte.

**Por que port e não uma função com `if`.** O repositório já resolveu esta mesma
escolha em `packages/llm/base.py`: `LLMProvider` é um Protocol com quatro
adaptadores e o `.env` decide. Voz tem a mesma forma de decisão (qualidade, custo
e disponibilidade variam por fornecedor e mudam com o tempo), então tem a mesma
solução. Trocar Gemini por ElevenLabs deve ser uma linha no `.env`, não um
commit.

**Por que o Gemini é o default.** Razão operacional, não técnica: a chave já
existe no `Settings` (`gemini_api_key`) e já é validada. Nenhuma conta nova,
nenhum segredo novo, uma fatura só. E o modelo de TTS do Gemini devolve
justamente PCM 24 kHz, então o áudio dele entra no contrato acima sem transcode —
sem `pydub`, sem `ffmpeg`, sem resample de CPU num i5-3470.

**Por que o `edge_tts` continua existindo.** Ele é o fallback, e o fallback é por
REQUISIÇÃO, não só no boot: cota acaba no meio do uso, não no start. Uma chave
vencida às 23h deve piorar a voz, não derrubar a conversa. Toda queda é logada
(`voice.tts.fallback`) — degradação silenciosa é como se descobre três semanas
depois que o sistema pagou caro por nada, ou que parou de pagar e ninguém viu.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any, Final, Protocol

import httpx
import structlog

logger = structlog.get_logger(__name__)

#: O contrato. Mudar qualquer um destes três números quebra o player do PWA.
SAMPLE_RATE: Final = 24_000
SAMPLE_WIDTH: Final = 2  # bytes — 16 bits
CHANNELS: Final = 1

#: CONFERIR na documentação atual do Google. O nome do modelo de TTS e o catálogo
#: de vozes mudam com frequência, e este default foi escrito com conhecimento com
#: corte em maio/2026. Sintoma de nome errado: HTTP 404 no `:generateContent`.
GEMINI_TTS_MODEL: Final = "gemini-2.5-flash-preview-tts"
GEMINI_TTS_VOICE: Final = "Kore"

_GEMINI_BASE: Final = "https://generativelanguage.googleapis.com/v1beta"

#: Teto por frase. A síntese é por frase (packages/voice/sentences.py), então uma
#: frase que demora mais que isto já estourou o orçamento de latência da conversa
#: — cair para o fallback é melhor que esperar.
_TIMEOUT: Final = httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=5.0)


class TTSError(RuntimeError):
    """Falha de síntese. Quem chama decide entre cair para o fallback ou desistir."""


class TTSProvider(Protocol):
    """Texto → PCM 16-bit mono 24 kHz."""

    name: str

    async def synthesize(self, text: str) -> bytes:
        ...


# --------------------------------------------------------------------------- #
# Gemini
# --------------------------------------------------------------------------- #


class GeminiTTS:
    """TTS do Google AI Studio.

    Devolve `inlineData` com PCM 16-bit 24 kHz (`audio/L16;codec=pcm;rate=24000`),
    que é exatamente o contrato deste módulo — nenhuma conversão no caminho.
    """

    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str = GEMINI_TTS_MODEL,
        voice: str = GEMINI_TTS_VOICE,
        *,
        base_url: str = _GEMINI_BASE,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("GeminiTTS exige api_key")
        self._api_key = api_key
        self._model = model
        self._voice = voice
        self._base_url = base_url.rstrip("/")
        self._client = client

    async def synthesize(self, text: str) -> bytes:
        payload: dict[str, Any] = {
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": self._voice}
                    }
                },
            },
        }
        url = f"{self._base_url}/models/{self._model}:generateContent"

        try:
            if self._client is not None:
                resp = await self._client.post(
                    url, json=payload, headers={"x-goog-api-key": self._api_key}
                )
            else:
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    resp = await client.post(
                        url, json=payload, headers={"x-goog-api-key": self._api_key}
                    )
        except httpx.HTTPError as exc:
            raise TTSError(f"rede falhou no TTS do Gemini: {exc}") from exc

        if resp.status_code >= 400:
            # O corpo do erro do Google diz o que está errado (modelo inexistente,
            # voz inválida, cota). Truncado porque vai para log de linha.
            raise TTSError(
                f"Gemini TTS HTTP {resp.status_code}: {resp.text[:300]}"
            )

        return _extrair_pcm(resp.json())


def _extrair_pcm(body: dict[str, Any]) -> bytes:
    """`candidates[0].content.parts[].inlineData.data` → bytes de PCM."""
    try:
        parts = body["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError) as exc:
        raise TTSError(f"resposta do Gemini TTS sem candidates: {str(body)[:300]}") from exc

    for part in parts:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            return base64.b64decode(inline["data"])

    raise TTSError(f"resposta do Gemini TTS sem áudio: {str(body)[:300]}")


# --------------------------------------------------------------------------- #
# edge-tts (fallback)
# --------------------------------------------------------------------------- #


class EdgeTTS:
    """TTS gratuito da Microsoft. Entrega MP3, então aqui há transcode.

    É o único adaptador que precisa do binário `ffmpeg` (via pydub). Enquanto ele
    for o fallback, o `ffmpeg` continua obrigatório na imagem da API — é o preço
    de ter uma voz que funciona sem chave e sem fatura.
    """

    name = "edge"

    def __init__(self, voice: str = "pt-BR-AntonioNeural") -> None:
        self._voice = voice

    async def synthesize(self, text: str) -> bytes:
        import io

        import edge_tts
        from pydub import AudioSegment

        communicate = edge_tts.Communicate(text, self._voice)
        mp3 = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3.write(chunk["data"])

        if not mp3.getbuffer().nbytes:
            raise TTSError("edge-tts devolveu áudio vazio")

        mp3.seek(0)
        seg = (
            AudioSegment.from_file(mp3, format="mp3")
            .set_frame_rate(SAMPLE_RATE)
            .set_channels(CHANNELS)
            .set_sample_width(SAMPLE_WIDTH)
        )
        return seg.raw_data


# --------------------------------------------------------------------------- #
# Fallback
# --------------------------------------------------------------------------- #


class TTSComFallback:
    """Tenta o primário; na falha, cai para o secundário e REGISTRA.

    Por requisição, de propósito — ver o docstring do módulo. Não faz retry no
    primário: numa conversa por voz, a segunda tentativa custa mais latência do
    que a voz pior custa em qualidade.
    """

    def __init__(self, primario: TTSProvider, fallback: TTSProvider) -> None:
        self._primario = primario
        self._fallback = fallback
        self.name = f"{primario.name}->{fallback.name}"

    async def synthesize(self, text: str) -> bytes:
        try:
            return await self._primario.synthesize(text)
        except (TTSError, asyncio.TimeoutError, Exception) as exc:
            logger.warning(
                "voice.tts.fallback",
                de=self._primario.name,
                para=self._fallback.name,
                error=str(exc)[:300],
            )
            return await self._fallback.synthesize(text)


def make_tts(
    provider: str,
    *,
    gemini_api_key: str = "",
    gemini_model: str = GEMINI_TTS_MODEL,
    gemini_voice: str = GEMINI_TTS_VOICE,
    edge_voice: str = "pt-BR-AntonioNeural",
) -> TTSProvider:
    """Monta o provider a partir da configuração, sempre com `edge` de rede.

    `provider="gemini"` sem chave **não** levanta: cai para o `edge` com aviso. O
    fail-fast do `Settings` existe para o que a app não roda sem, e voz gratuita
    funcionando é melhor que boot quebrado por um campo opcional.
    """
    edge = EdgeTTS(voice=edge_voice)

    if provider == "edge":
        return edge

    if provider == "gemini":
        if not gemini_api_key:
            logger.warning("voice.tts.sem_chave", provider="gemini", usando="edge")
            return edge
        return TTSComFallback(
            GeminiTTS(gemini_api_key, model=gemini_model, voice=gemini_voice), edge
        )

    logger.warning("voice.tts.provider_desconhecido", provider=provider, usando="edge")
    return edge
