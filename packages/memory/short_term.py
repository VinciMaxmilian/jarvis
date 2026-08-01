"""Nível `short` — turnos recentes da conversa corrente (`plan.md` §10).

Vida útil: a sessão. Redis com TTL é exatamente isso.

O docstring anterior chamava este nível de "working memory", o que passou a ser
enganoso na v1.3: `working` é um nível **distinto**, com outra vida útil e outra
durabilidade — ele mora em `working.py` e é persistido no checkpoint da task,
porque precisa sobreviver a um `kill -9`. Aqui, sobreviver não é requisito: se o
Redis some, o que se perde é o fim de uma conversa.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class ShortTermMemory:
    """Working memory for active tasks and goals using Redis."""

    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self._redis = None

    async def connect(self) -> None:
        """Connects to Redis."""
        try:
            import redis.asyncio as redis
            self._redis = redis.from_url(self.redis_url, decode_responses=True)
            logger.info("memory.short_term.connected", url=self.redis_url)
        except ImportError:
            logger.error("memory.short_term.missing_dependency", dep="redis")
            self._redis = None

    async def set_state(
        self, key: str, state: dict[str, Any], ttl_seconds: int = 86400
    ) -> None:
        """Stores arbitrary state with a TTL."""
        if not self._redis:
            return
        await self._redis.set(key, json.dumps(state), ex=ttl_seconds)

    async def get_state(self, key: str) -> dict[str, Any] | None:
        """Retrieves stored state."""
        if not self._redis:
            return None
        data = await self._redis.get(key)
        if data:
            return json.loads(data)
        return None

    async def clear_state(self, key: str) -> None:
        """Deletes stored state."""
        if not self._redis:
            return
        await self._redis.delete(key)
