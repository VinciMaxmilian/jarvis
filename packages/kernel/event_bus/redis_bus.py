"""Barramento de eventos usando Redis Streams.

Substitui o InProcEventBus para permitir processamento distribuído de eventos.
Usa Redis Streams (XADD) para publicar e Consumer Groups (XREADGROUP) para consumir.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Iterable
from uuid import UUID

from redis.exceptions import ResponseError
import redis.asyncio as redis
import structlog
from pydantic import TypeAdapter

from packages.shared.contracts import Event
from packages.kernel.event_bus.in_proc import EventHandler, Subscription, FILA_MAXIMA

logger = structlog.get_logger(__name__)

STREAM_NAME = "jarvis:events"
GROUP_NAME = "jarvis_workers"
CONSUMER_NAME = "worker_1"  # Em um ambiente real, deve ser único por instância


class RedisEventBus:
    """Implementa EventBus sobre Redis Streams."""

    def __init__(self, redis_url: str, consumer_name: str = CONSUMER_NAME) -> None:
        self._redis = redis.from_url(redis_url, decode_responses=True)
        self._consumer_name = consumer_name
        self._subs: list[Subscription] = []
        self._task: asyncio.Task[None] | None = None
        self.dropped: int = 0
        self._event_adapter = TypeAdapter(Event)

    # -- porta EventBus ---------------------------------------------------- #

    async def publish(self, event: Event) -> None:
        """Publica um evento no Redis Stream usando XADD."""
        try:
            # Serializa o evento para JSON
            payload = self._event_adapter.dump_json(event, by_alias=True).decode("utf-8")
            
            # Adiciona ao stream
            await self._redis.xadd(STREAM_NAME, {"payload": payload}, maxlen=FILA_MAXIMA)
            logger.debug("event_bus.published", event_type=event.type, event_id=str(event.id))
        except Exception as exc:
            self.dropped += 1
            logger.error(
                "event_bus.publish_failed",
                event_type=event.type,
                event_id=str(event.id),
                error=str(exc)
            )

    # -- assinatura -------------------------------------------------------- #

    def subscribe(
        self, handler: EventHandler, *, types: Iterable[str] | None = None
    ) -> Subscription:
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
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
            
        # Cria o consumer group se não existir
        try:
            await self._redis.xgroup_create(STREAM_NAME, GROUP_NAME, mkstream=True, id="0")
        except ResponseError as e:
            if "BUSYGROUP Consumer Group name already exists" not in str(e):
                logger.error("event_bus.group_create_failed", error=str(e))
                raise

        self._task = asyncio.create_task(self._run(), name="redis_event_bus")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        
        await self._redis.aclose() # type: ignore

    async def _run(self) -> None:
        """Laço principal de consumo do Redis Stream."""
        logger.info("event_bus.redis.started", stream=STREAM_NAME, group=GROUP_NAME)
        while True:
            try:
                # Bloqueia esperando novos eventos do grupo
                # O id ">" significa "me dê mensagens não entregues a outros consumidores"
                response = await self._redis.xreadgroup(
                    GROUP_NAME, 
                    self._consumer_name, 
                    {STREAM_NAME: ">"}, 
                    count=10, 
                    block=1000
                )
                
                if not response:
                    continue
                    
                for stream, messages in response:
                    for message_id, message_data in messages:
                        payload = message_data.get("payload")
                        if not payload:
                            await self._redis.xack(STREAM_NAME, GROUP_NAME, message_id)
                            continue
                            
                        try:
                            event = self._event_adapter.validate_json(payload)
                            await self._dispatch(event)
                            
                            # Confirma recebimento apenas se dispatch teve sucesso (ou ignorado com segurança)
                            await self._redis.xack(STREAM_NAME, GROUP_NAME, message_id)
                        except Exception as exc:
                            logger.error("event_bus.redis.process_failed", msg_id=message_id, error=str(exc))
                            
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("event_bus.redis.read_error")
                await asyncio.sleep(1) # Backoff em caso de falha de conexão

    async def _dispatch(self, event: Event) -> None:
        for sub in list(self._subs):
            if not sub.wants(event):
                continue
            try:
                await sub.handler(event)
            except Exception:
                logger.exception(
                    "event_bus.handler_falhou",
                    event_type=event.type,
                    event_id=str(event.id),
                    handler=sub.nome,
                )

__all__ = ["RedisEventBus"]
