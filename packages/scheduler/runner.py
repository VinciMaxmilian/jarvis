"""Implementação real de `CommandRunner`: `asyncio.create_subprocess_exec`.

Sem `shell=True` em lugar nenhum. O único argumento que vem de configuração é o
caminho do binário; tudo o mais é montado por código. Passar isso por um shell
transformaria um nome de banco com aspas em execução de comando, e o backup roda
sozinho de madrugada — é o pior lugar do sistema para uma injeção silenciosa.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping, Sequence

import structlog

from packages.scheduler.models import CommandResult

logger = structlog.get_logger(__name__)

#: Código de saída que o shell usa para "comando não encontrado". Reaproveitado
#: aqui para que binário ausente e binário que falhou cheguem ao chamador pelo
#: mesmo caminho — um `CommandResult` com `ok=False` e stderr explicando.
EXIT_NOT_FOUND = 127

#: Código de saída sintético para timeout (`128 + SIGKILL`), a convenção do shell.
EXIT_TIMEOUT = 137


class AsyncSubprocessRunner:
    """`CommandRunner` sobre `asyncio`. Herda o ambiente e acrescenta o que veio.

    Herdar `os.environ` não é detalhe: `pg_dump` lê `PGSSLMODE`, `PGCONNECT_TIMEOUT`
    e amigos de lá, e um filho com ambiente vazio falharia em qualquer instalação
    que dependa desses ajustes — com uma mensagem que não aponta para a causa.
    """

    def __init__(self, *, inherit_env: bool = True) -> None:
        self._inherit_env = inherit_env

    async def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        if not argv:
            raise ValueError("argv vazio")

        ambiente = dict(os.environ) if self._inherit_env else {}
        ambiente.update(env or {})
        comando = tuple(argv)

        try:
            processo = await asyncio.create_subprocess_exec(
                *comando,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=ambiente,
            )
        except FileNotFoundError:
            logger.error("scheduler.command.not_found", binary=comando[0])
            return CommandResult(
                argv=comando,
                returncode=EXIT_NOT_FOUND,
                stderr=(
                    f"binário não encontrado: {comando[0]!r}. "
                    "A imagem precisa do postgresql-client para o backup rodar."
                ),
            )

        try:
            bruto_out, bruto_err = await asyncio.wait_for(
                processo.communicate(), timeout=timeout_seconds
            )
        except TimeoutError:
            processo.kill()
            await processo.wait()
            logger.error(
                "scheduler.command.timeout",
                binary=comando[0],
                timeout_seconds=timeout_seconds,
            )
            return CommandResult(
                argv=comando,
                returncode=EXIT_TIMEOUT,
                stderr=f"tempo esgotado após {timeout_seconds}s",
            )

        return CommandResult(
            argv=comando,
            returncode=processo.returncode or 0,
            stdout=bruto_out.decode("utf-8", errors="replace"),
            stderr=bruto_err.decode("utf-8", errors="replace"),
        )


__all__ = ["EXIT_NOT_FOUND", "EXIT_TIMEOUT", "AsyncSubprocessRunner"]
