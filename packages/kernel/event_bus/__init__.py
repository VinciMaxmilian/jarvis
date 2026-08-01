"""Barramento de eventos do kernel.

`InProcEventBus` é o adaptador da v1 para a porta `EventBus`
(`packages/shared/ports.py`). Redis Streams é v2.2 e entra como outro adaptador
atrás da mesma porta — nada aqui vaza para quem publica.
"""

from packages.kernel.event_bus.in_proc import (
    FILA_MAXIMA,
    EventHandler,
    InProcEventBus,
    Subscription,
)

__all__ = ["FILA_MAXIMA", "EventHandler", "InProcEventBus", "Subscription"]
