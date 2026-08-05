"""Fila de fala: sintetiza e envia áudio na ordem, enquanto o modelo ainda gera.

**O ganho.** O produtor (o stream do LLM) empurra frases e segue em frente; o
consumidor sintetiza e envia. A frase 1 vira áudio enquanto o modelo escreve a
frase 3. É daqui que sai a maior parte da redução de latência percebida — antes
disto o laço acumulava a resposta inteira, sintetizava tudo de uma vez e só então
tocava.

**A armadilha que este módulo existe para fechar: ORDEM.** A tentação óbvia é
disparar as sínteses concorrentes com `create_task`, uma por frase. Só que elas
terminam fora de ordem — uma frase curta sintetiza antes de uma longa que veio
antes — e o dono ouve a resposta embaralhada. Áudio fora de ordem é PIOR que
áudio lento: lento é incômodo, embaralhado é ininteligível.

Um consumidor só, sequencial, resolve isso por construção. O paralelismo que
importa (gerar enquanto fala) continua existindo, porque produtor e consumidor
são tarefas diferentes; o que não se paraleliza é a síntese entre si, e essa é
justamente a que precisa de ordem.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import structlog

from packages.voice.tts import TTSProvider

logger = structlog.get_logger(__name__)

#: Tamanho do pedaço enviado ao cliente. Mantido do valor que já estava em uso no
#: roteador de voz (4096 * 4): grande o bastante para não inundar o WebSocket de
#: mensagens, pequeno o bastante para o áudio começar a tocar sem esperar a frase
#: inteira atravessar a rede.
CHUNK_BYTES = 16_384


class Locutor:
    """Fala o que for enfileirado, na ordem, sem bloquear quem enfileira."""

    def __init__(
        self,
        tts: TTSProvider,
        enviar: Callable[[bytes], Awaitable[None]],
        *,
        chunk_bytes: int = CHUNK_BYTES,
    ) -> None:
        self._tts = tts
        self._enviar = enviar
        self._chunk = chunk_bytes
        self._fila: asyncio.Queue[str | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    async def iniciar(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._consumir())

    def dizer(self, texto: str) -> None:
        """Enfileira. NÃO espera a síntese — é isso que mantém o pipeline andando."""
        texto = texto.strip()
        if texto:
            self._fila.put_nowait(texto)

    async def drenar(self) -> None:
        """Espera tudo que já foi enfileirado terminar de tocar."""
        await self._fila.join()

    async def parar(self) -> None:
        """Drena e encerra o consumidor."""
        if self._task is None:
            return
        await self._fila.join()
        await self._fila.put(None)
        await self._task
        self._task = None

    async def _consumir(self) -> None:
        while True:
            item = await self._fila.get()
            if item is None:
                self._fila.task_done()
                return
            try:
                pcm = await self._tts.synthesize(item)
                for i in range(0, len(pcm), self._chunk):
                    await self._enviar(pcm[i : i + self._chunk])
                    # Devolve o controle ao loop: sem isto, uma resposta longa
                    # monopoliza a tarefa e o áudio chega em rajada.
                    await asyncio.sleep(0.005)
            except Exception as exc:
                # Uma frase que falhou não pode derrubar a conversa: o resto da
                # resposta ainda vale. Fica no log porque uma resposta com um
                # buraco no meio, sem registro, é impossível de diagnosticar
                # depois — o dono só sabe dizer "ele comeu uma parte".
                logger.error(
                    "voice.locutor.frase_falhou",
                    frase=item[:120],
                    error=str(exc)[:300],
                    exc_info=True,
                )
            finally:
                self._fila.task_done()
