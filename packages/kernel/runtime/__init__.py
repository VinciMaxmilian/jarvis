"""Runtimes de execução: o contrato, o supervisor e os adapters.

`plan-execution.md` §2 chamou a abstração de runtime de "maior lacuna real": o
manifest tinha `transport: Literal["mcp_stdio", "python"]`, dois valores fechados
dentro do contrato. Somar Docker, CLI ou HTTP editava `contracts.py` e todo
consumidor junto. Agora o contrato tem `runtime: str` e o conjunto de executores é
deste pacote — somar um adapter é criar uma classe e registrá-la no `Kernel`.

`_child` não é reexportado: ele é o *outro lado* da fronteira de processo, roda
como `python -m` dentro do subprocesso da capability e importá-lo daqui não faz
sentido nenhum para quem consome o pacote.
"""

from packages.kernel.runtime.base import (
    RUNTIME_HTTP,
    RUNTIME_MCP,
    RUNTIME_PYTHON,
    ExecutionLimits,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    RuntimeAdapter,
    truncar,
)
from packages.kernel.runtime.python_runtime import PythonRuntime
from packages.kernel.runtime.sandbox import (
    SandboxOutcome,
    python_argv,
    run_sandboxed,
)

__all__ = [
    "RUNTIME_HTTP",
    "RUNTIME_MCP",
    "RUNTIME_PYTHON",
    "ExecutionLimits",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionStatus",
    "PythonRuntime",
    "RuntimeAdapter",
    "SandboxOutcome",
    "python_argv",
    "run_sandboxed",
    "truncar",
]
