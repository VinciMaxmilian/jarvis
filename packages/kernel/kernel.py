"""O `Kernel`: escolhe o adapter, executa, e conta o que aconteceu.

É a peça que faltava entre `registry/` (que sabe *qual* capability atende uma
intenção) e `runtime/` (que sabe *como* rodar cada tipo). Três responsabilidades,
e nenhuma a mais:

1. **Despachar por `runtime`.** O manifest diz `python`, `mcp` ou `http`; o mapa
   de adapters é desta instalação. Runtime desconhecido falha nomeando os que
   existem *aqui* — não os que existiam quando o contrato foi escrito.
2. **Recusar antes de gastar processo.** Tool que não está no manifest não chega
   a virar `fork`. É a checagem barata, feita antes da cara.
3. **Publicar o que houve.** `tool.called` antes, `tool.finished` depois, e
   `task.failed` quando o desfecho não é OK e a execução veio de uma task.

Sobre a 3: é o que fecha o aceite "capability em laço infinito é morta pelo
timeout e o Executive recebe `TaskFailed`, não trava". O Executive não fica
esperando o processo — ele escuta o bus. Quem mata é o supervisor do sandbox,
quem avisa é este módulo, e os dois são independentes de propósito: um supervisor
que também precisasse avisar teria de sobreviver ao próprio timeout.

**Nada aqui levanta por falha da capability.** `run()` devolve `ExecutionResult`
com `status`, sempre. Exceção (`KernelError`) fica para o que é erro de
instalação ou de chamada — runtime inexistente, tool fora do manifest —, porque
essas o chamador *pode* corrigir, e falhar em silêncio nelas esconde bug de
configuração atrás de "a capability não funcionou".
"""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

import structlog

from packages.kernel.errors import RuntimeNotSupported, ToolNotInCapability
from packages.kernel.runtime.base import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    RuntimeAdapter,
)
from packages.shared.contracts import Event, EventType
from packages.shared.ports import EventBus

logger = structlog.get_logger(__name__)


class Kernel:
    """Despacha execuções para o adapter do `runtime` declarado no manifest."""

    def __init__(
        self,
        adapters: tuple[RuntimeAdapter, ...] | list[RuntimeAdapter],
        *,
        event_bus: EventBus | None = None,
    ) -> None:
        self._adapters: dict[str, RuntimeAdapter] = {a.runtime: a for a in adapters}
        self._bus = event_bus

    @property
    def runtimes(self) -> tuple[str, ...]:
        """Runtimes atendíveis nesta instalação, em ordem estável."""
        return tuple(sorted(self._adapters))

    def adapter_de(self, runtime: str) -> RuntimeAdapter:
        """Adapter do runtime, ou `RuntimeNotSupported` dizendo quais existem."""
        adapter = self._adapters.get(runtime)
        if adapter is None:
            raise RuntimeNotSupported(runtime, self.runtimes)
        return adapter

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        """Executa uma tool. Devolve o desfecho; não levanta por falha dela.

        Levanta `RuntimeNotSupported` ou `ToolNotInCapability` — as duas coisas
        que o chamador escreveu errado e pode consertar.
        """
        adapter = self.adapter_de(request.manifest.runtime)

        # Barato antes de caro: `fork` + interpretador custam ~100 ms, e uma tool
        # que não existe no manifest não precisa de nenhum dos dois para falhar.
        if request.tool_spec is None:
            raise ToolNotInCapability(request.capability, request.tool)

        await self._publicar(EventType.TOOL_CALLED, request)
        comeco = time.monotonic()

        resultado = await adapter.execute(request)

        logger.info(
            "kernel.tool_finished",
            capability=request.capability,
            tool=request.tool,
            runtime=resultado.runtime,
            status=resultado.status.value,
            dry_run=request.dry_run,
            duration_ms=resultado.duration_ms or int((time.monotonic() - comeco) * 1000),
            denied=list(resultado.denied),
        )

        await self._publicar(EventType.TOOL_FINISHED, request, resultado)
        if resultado.status is not ExecutionStatus.OK:
            await self._publicar(EventType.TASK_FAILED, request, resultado)
        return resultado

    # ------------------------------------------------------------------ #
    # eventos
    # ------------------------------------------------------------------ #

    async def _publicar(
        self,
        tipo: str,
        request: ExecutionRequest,
        resultado: ExecutionResult | None = None,
    ) -> None:
        """Publica no bus, se houver bus.

        Sem bus configurado o kernel executa igual: um teste de adapter não deve
        precisar montar infraestrutura de evento para provar que o subprocesso
        rodou. Quem quer os eventos, injeta.
        """
        if self._bus is None:
            return

        payload: dict[str, Any] = {
            "capability": request.capability,
            "tool": request.tool,
            "runtime": request.manifest.runtime,
            "dry_run": request.dry_run,
        }
        if resultado is not None:
            payload.update(
                status=resultado.status.value,
                error=resultado.error,
                denied=list(resultado.denied),
                duration_ms=resultado.duration_ms,
                exit_code=resultado.exit_code,
            )

        await self._bus.publish(
            Event(
                type=tipo,
                source="packages.kernel",
                payload=payload,
                goal_id=request.goal_id,
                task_id=request.task_id,
                # `trace_id` é obrigatório no contrato: execução sem proveniência
                # (um teste, o CLI do dono) ganha um id próprio em vez de string
                # vazia, senão dois eventos não relacionados colidem no log.
                trace_id=request.trace_id or f"kernel-{uuid4().hex[:12]}",
            )
        )


__all__ = ["Kernel"]
