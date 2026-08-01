"""Subprocesso com limites e supervisor que mata.

`plan-execution.md` §v1.2: "cada capability em subprocesso; supervisor mata em
timeout/OOM e marca a task `failed`". Docker por capability é v2 — e esta é a
razão de o módulo existir agora: um `asyncio.wait_for` em volta de uma corrotina
**não** mata laço infinito nenhum. `while True: pass` dentro do processo do
orchestrator ignora o cancelamento do asyncio, porque o laço nunca devolve o
controle ao event loop. Só um processo separado pode ser morto.

Quatro decisões que o código sozinho não explica:

- **Grupo de processos, não processo.** `os.setsid()` no filho e `killpg` no
  supervisor. Sem isso, uma capability que já tinha aberto um neto deixa o neto
  vivo segurando o pipe, e a leitura de `stdout` fica bloqueada para sempre —
  o timeout "funciona" e o supervisor trava mesmo assim.
- **SIGKILL, não SIGTERM.** Quem chegou ao timeout já passou do prazo; dar mais
  uma chance de rodar `finally` é dar mais uma chance de não morrer. O aceite é
  "morta pelo timeout", não "convidada a sair".
- **`RLIMIT_AS` e `RLIMIT_CPU` no `preexec_fn`.** É o único ponto entre o `fork`
  e o `exec` onde dá para limitar o filho sem limitar quem o criou. A função
  roda no processo filho recém-forkado; ela não pode alocar nem logar.
- **Limite só onde existe.** `resource` e `setsid` são POSIX. O container de
  teste e o de produção são Linux; a máquina do dono é Windows, e lá o módulo
  degrada para "sem rlimit, com timeout" em vez de quebrar o import.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import structlog
from pydantic import BaseModel, ConfigDict

from packages.kernel.runtime.base import ExecutionLimits, truncar

logger = structlog.get_logger(__name__)

#: POSIX tem `resource`/`setsid`; Windows não. Ver docstring do módulo.
POSIX = os.name == "posix"

if POSIX:  # pragma: no branch — decidido no import, por plataforma
    import resource
else:  # pragma: no cover — só no host Windows do dono
    resource = None  # type: ignore[assignment]

#: Tempo dado ao filho já morto para os pipes fecharem. Não é espera pelo
#: processo (ele levou SIGKILL): é a leitura do que ele já tinha escrito.
DRENO_SEGUNDOS = 5.0


class SandboxOutcome(BaseModel):
    """O que o supervisor observou. Sem interpretação: só o fato."""

    model_config = ConfigDict(frozen=True)

    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    duration_ms: int

    @property
    def killed_by_signal(self) -> int | None:
        """Sinal que matou o processo, se foi morto por um.

        `asyncio` devolve o código negado (`-9` para SIGKILL), que é como o
        POSIX distingue "saiu com 9" de "morreu de SIGKILL".
        """
        if self.exit_code is not None and self.exit_code < 0:
            return -self.exit_code
        return None


def _limitador(limits: ExecutionLimits) -> Callable[[], None] | None:
    """Função `preexec_fn` que aplica os limites no filho, ou `None` no Windows.

    Roda entre `fork` e `exec`, no processo filho: nada de alocar, nada de log,
    nada que possa levantar em cima de um interpretador pela metade.
    """
    if not POSIX:  # pragma: no cover — só no host Windows do dono
        return None

    memoria = limits.memory_mb
    cpu = limits.cpu_limite

    def aplicar() -> None:  # pragma: no cover — roda no processo filho
        os.setsid()
        if memoria is not None:
            bytes_ = memoria * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (bytes_, bytes_))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        # Sem core dump: capability que estoura memória não precisa despejar
        # centenas de MB no disco do dono para provar isso.
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    return aplicar


def _matar(proc: asyncio.subprocess.Process) -> None:
    """SIGKILL no grupo do filho; no processo, se o grupo já não existir."""
    if proc.returncode is not None:
        return
    if POSIX:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
    with contextlib.suppress(ProcessLookupError):
        proc.kill()


async def run_sandboxed(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    limits: ExecutionLimits,
    stdin_data: bytes | None = None,
) -> SandboxOutcome:
    """Roda `argv` isolado e volta com o que ele produziu — ou com `timed_out`.

    Nunca levanta por causa do processo filho: falha do filho é dado de saída.
    Levanta só se o `exec` em si for impossível (binário inexistente), que é
    erro de configuração do kernel e não da capability.
    """
    inicio = asyncio.get_running_loop().time()

    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd),
        env=dict(env),
        stdin=asyncio.subprocess.PIPE if stdin_data else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        preexec_fn=_limitador(limits),  # noqa: PLW1509 — ver docstring do módulo
        start_new_session=False,  # o `setsid` é feito pelo próprio limitador
    )

    if stdin_data is not None and proc.stdin is not None:
        proc.stdin.write(stdin_data)
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            await proc.stdin.drain()
        proc.stdin.close()

    # Leitura em tarefas próprias: `communicate()` cancelado no timeout deixa a
    # leitura pela metade, e o que a capability escreveu antes de travar é
    # exatamente o que se quer ler para descobrir onde ela travou.
    saida = asyncio.create_task(_ler(proc.stdout))
    erro = asyncio.create_task(_ler(proc.stderr))

    timed_out = False
    try:
        await asyncio.wait_for(proc.wait(), timeout=limits.timeout_seconds)
    except TimeoutError:
        timed_out = True
        _matar(proc)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=DRENO_SEGUNDOS)
        logger.warning(
            "kernel.sandbox_timeout",
            argv=list(argv),
            timeout_s=limits.timeout_seconds,
            pid=proc.pid,
        )
    finally:
        # O processo acabou (ou levou SIGKILL): os pipes fecham e a leitura
        # termina sozinha. O `wait_for` é só para o caso de um neto sobrevivente
        # segurar o descritor, e aí a saída dele é perda aceitável.
        for tarefa in (saida, erro):
            if not tarefa.done():
                with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                    await asyncio.wait_for(asyncio.shield(tarefa), DRENO_SEGUNDOS)
            if not tarefa.done():
                tarefa.cancel()

    decorrido = int((asyncio.get_running_loop().time() - inicio) * 1000)
    return SandboxOutcome(
        exit_code=proc.returncode,
        stdout=truncar(_resultado(saida), limits.max_output_bytes),
        stderr=truncar(_resultado(erro), limits.max_output_bytes),
        timed_out=timed_out,
        duration_ms=decorrido,
    )


async def _ler(stream: asyncio.StreamReader | None) -> bytes:
    if stream is None:  # pragma: no cover — os pipes são sempre criados aqui
        return b""
    return await stream.read()


def _resultado(tarefa: asyncio.Task[bytes]) -> bytes:
    """O que a tarefa de leitura conseguiu ler, mesmo que tenha sido cancelada."""
    if tarefa.done() and not tarefa.cancelled() and tarefa.exception() is None:
        return tarefa.result()
    return b""


def python_argv(modulo: str, *args: str) -> list[str]:
    """Linha de comando do interpretador atual, em modo seguro.

    - `-P` não põe o diretório de trabalho no `sys.path`: o `cwd` é o diretório
      da capability, e sem isso um arquivo `packages/` dentro dela sequestraria
      o import do próprio kernel no bootstrap.
    - `-B` não escreve `__pycache__`: escrever dentro do diretório da capability
      mudaria o digest que o `discover()` confere contra `approved_commit`.
    """
    return [sys.executable, "-P", "-B", "-m", modulo, *args]


__all__ = [
    "DRENO_SEGUNDOS",
    "POSIX",
    "SandboxOutcome",
    "python_argv",
    "run_sandboxed",
]
