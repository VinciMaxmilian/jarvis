"""Barramento de eventos em processo, sobre `asyncio.Queue`.

Primeiro uso real da porta `EventBus` (D-12): até aqui ela existia em
`packages/shared/ports.py` sem um publisher e sem um consumidor. O transporte da
v2.2 é Redis Streams; o que faz dessa troca *uma classe*, e não um refactor, é
ninguém depender deste módulo além da porta.

Três decisões que o código sozinho não explica:

- **Fila cheia descarta e loga; não bloqueia.** `publish()` é chamado de dentro
  do caminho de decisão (o miss do registry, `resolve()`). Bloquear o publisher
  à espera de um consumidor que já está parado troca "perdi um evento" por
  "o sistema inteiro travou", que é pior e muito mais caro de diagnosticar. O
  contador `dropped` e o log em `error` mantêm a perda visível — perda silenciosa
  é que seria inaceitável.
- **Handler que levanta não derruba o laço.** Um consumidor quebrado vira log e
  o próximo consumidor recebe o mesmo evento. Sem isso, um `except` esquecido em
  um assinante para o barramento inteiro, e o sistema morre em silêncio.
- **`drain()` existe.** Despacho determinístico do que já está na fila, sem
  `sleep` no teste e sem tarefa de fundo. É também o passo de desligamento
  ordenado: parar o laço com evento na fila é perder trabalho já aceito.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

import structlog

from packages.shared.contracts import Event

logger = structlog.get_logger(__name__)

#: Assinatura de consumidor. Corrotina porque todo consumidor real faz I/O
#: (gravar goal, escrever memória, chamar capability).
EventHandler = Callable[[Event], Awaitable[None]]

#: Capacidade default da fila. Grande o bastante para um pico de decomposição de
#: goal, pequena o bastante para a fila cheia aparecer antes da memória acabar.
FILA_MAXIMA = 1024


@dataclass(frozen=True)
class Subscription:
    """Um consumidor e os tipos de evento que ele quer.

    `types=None` é "tudo" — usado por gravador de log e por teste; consumidor de
    produção declara os tipos, para não acordar a cada evento do sistema.
    """

    handler: EventHandler
    types: frozenset[str] | None = None

    def wants(self, event: Event) -> bool:
        return self.types is None or event.type in self.types

    @property
    def nome(self) -> str:
        """Nome legível do consumidor, para o log de falha dizer quem quebrou."""
        rotulo = getattr(self.handler, "__qualname__", None)
        return rotulo if isinstance(rotulo, str) else type(self.handler).__name__


class InProcEventBus:
    """`EventBus` em processo. Implementa a porta de `packages/shared/ports.py`."""

    def __init__(self, *, maxsize: int = FILA_MAXIMA) -> None:
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self._subs: list[Subscription] = []
        self._task: asyncio.Task[None] | None = None
        #: Eventos perdidos por fila cheia. Zero é o valor esperado; qualquer
        #: outro é consumidor parado, e o dono precisa saber disso.
        self.dropped: int = 0

    # -- porta EventBus ---------------------------------------------------- #

    async def publish(self, event: Event) -> None:
        """Aceita o evento e devolve o controle. Não espera consumidor."""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self.dropped += 1
            logger.error(
                "event_bus.fila_cheia",
                event_type=event.type,
                event_id=str(event.id),
                descartados=self.dropped,
                maxsize=self._queue.maxsize,
            )

    # -- assinatura -------------------------------------------------------- #

    def subscribe(
        self, handler: EventHandler, *, types: Iterable[str] | None = None
    ) -> Subscription:
        """Registra um consumidor. Devolve a assinatura, para poder cancelá-la."""
        sub = Subscription(
            handler=handler,
            types=frozenset(types) if types is not None else None,
        )
        self._subs.append(sub)
        return sub

    def unsubscribe(self, subscription: Subscription) -> None:
        with contextlib.suppress(ValueError):
            self._subs.remove(subscription)

    @property
    def subscriptions(self) -> list[Subscription]:
        return list(self._subs)

    # -- despacho ---------------------------------------------------------- #

    @property
    def pending(self) -> int:
        """Eventos aceitos e ainda não entregues."""
        return self._queue.qsize()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def drain(self) -> int:
        """Entrega tudo que já está na fila e devolve quantos foram entregues.

        Determinístico de propósito: teste que afirma "o evento chegou" não pode
        depender de `sleep`, e desligamento que descarta fila não é desligamento.
        """
        entregues = 0
        while True:
            try:
                event = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return entregues
            try:
                await self._dispatch(event)
            finally:
                self._queue.task_done()
            entregues += 1

    async def start(self) -> None:
        """Sobe o laço de despacho em segundo plano. Idempotente."""
        if self.running:
            return
        self._task = asyncio.create_task(self._run(), name="event_bus")

    async def stop(self) -> None:
        """Drena o que sobrou e encerra o laço. Idempotente."""
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self.drain()

    async def _run(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                await self._dispatch(event)
            finally:
                self._queue.task_done()

    async def _dispatch(self, event: Event) -> None:
        for sub in list(self._subs):
            if not sub.wants(event):
                continue
            try:
                await sub.handler(event)
            except Exception:
                # Consumidor quebrado é log, nunca parada do barramento: o
                # próximo assinante ainda tem direito de ver o evento.
                logger.exception(
                    "event_bus.handler_falhou",
                    event_type=event.type,
                    event_id=str(event.id),
                    handler=sub.nome,
                )


__all__ = ["FILA_MAXIMA", "EventHandler", "InProcEventBus", "Subscription"]
