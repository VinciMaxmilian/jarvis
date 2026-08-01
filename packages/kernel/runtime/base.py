"""Contrato de execução: o que entra num runtime, o que sai, e quem executa.

`plan-execution.md` §2 chamou isto de "a maior lacuna real": até a v1.2 o
manifest tinha `transport: Literal["mcp_stdio", "python"]` — dois valores
fechados **dentro do contrato**, de modo que somar Docker, CLI ou HTTP editava
`contracts.py` e todo consumidor junto. Agora o contrato tem `runtime: str` e o
conjunto de executores é deste pacote: somar um adapter é criar uma classe e
registrá-la, sem tocar em contrato nem em chamador.

`ExecutionRequest` e `ExecutionResult` são modelos, não dicionários: o
invariante de `plan-execution.md` §7 é que nenhum dict solto atravesse fronteira
de módulo, e a fronteira kernel↔adapter é justamente uma dessas. Os campos que
carregam JSON (`arguments`, `output`) são dicionário *dentro* de um modelo, que
é a mesma forma de `Task.input` e `Event.payload`.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from packages.kernel.permissions.policy import PermissionPolicy
from packages.shared.contracts import CapabilityManifest, ToolSpec

#: Nomes canônicos de runtime. Existem como constante, e não como `Literal`,
#: porque quem valida é o mapa de adapters do kernel — um manifest com runtime
#: desconhecido tem de falhar dizendo quais existem *nesta instalação*, não
#: quais existiam quando o contrato foi escrito.
RUNTIME_PYTHON = "python"
RUNTIME_MCP = "mcp"
RUNTIME_HTTP = "http"


class ExecutionStatus(StrEnum):
    """Desfecho de uma execução. Separado do `TaskStatus` de propósito: a task
    pode ter três tentativas, e cada uma tem o seu próprio desfecho."""

    OK = "ok"
    FAILED = "failed"  # a capability rodou e levantou
    TIMEOUT = "timeout"  # morta pelo supervisor
    DENIED = "denied"  # tentou sair do escopo declarado
    ERROR = "error"  # o kernel não conseguiu nem chegar a executar


class ExecutionLimits(BaseModel):
    """Limites do isolamento. Docker por capability é v2 (`plan-execution.md`).

    Os defaults valem para capability escrita à mão nesta máquina: 30 s é mais
    do que qualquer chamada de tool razoável e menos do que a paciência de quem
    espera no celular; 512 MB é o dobro do que um interpretador com `httpx`
    carregado usa, e um décimo do que derrubaria a máquina do dono.
    """

    model_config = ConfigDict(frozen=True)

    #: Tempo de parede. Estourou, o processo é morto com SIGKILL — e o grupo
    #: inteiro junto, senão um neto sobrevive segurando o pipe.
    timeout_seconds: float = Field(default=30.0, gt=0)
    #: `RLIMIT_AS` do subprocesso. `None` desliga (útil só para depuração).
    memory_mb: int | None = Field(default=512, gt=0)
    #: `RLIMIT_CPU`. Rede de segurança para o caso de o relógio de parede ser
    #: enganado (suspensão da máquina); default é o timeout arredondado acima.
    cpu_seconds: int | None = None
    #: Corte de `stdout`/`stderr` guardados no resultado. Capability em laço
    #: imprimindo sem parar não pode encher a memória de quem a supervisiona.
    max_output_bytes: int = Field(default=64 * 1024, gt=0)

    @property
    def cpu_limite(self) -> int:
        """`cpu_seconds` explícito, ou o teto de parede + 1 s de folga."""
        if self.cpu_seconds is not None:
            return self.cpu_seconds
        return int(self.timeout_seconds) + 1


class ExecutionRequest(BaseModel):
    """Uma chamada de tool prestes a acontecer."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    manifest: CapabilityManifest
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    #: Diretório da capability em disco: `cwd` do processo e raiz de escrita.
    directory: Path
    dry_run: bool = False
    limits: ExecutionLimits = Field(default_factory=ExecutionLimits)
    #: Proveniência, para o evento publicado no bus dizer de qual task veio.
    goal_id: UUID | None = None
    task_id: UUID | None = None
    trace_id: str | None = None

    @property
    def capability(self) -> str:
        return self.manifest.name

    @property
    def tool_spec(self) -> ToolSpec | None:
        return next((t for t in self.manifest.tools if t.name == self.tool), None)

    def policy(self) -> PermissionPolicy:
        """Escopo efetivo desta execução."""
        return PermissionPolicy.from_manifest(
            self.manifest.permissions,
            capability_dir=self.directory,
            capability=self.manifest.name,
        )


class ExecutionResult(BaseModel):
    """O que volta ao Executive. Nunca levanta: falha é campo, não exceção.

    `stdout`/`stderr` vêm sempre, inclusive no sucesso: o `print` de depuração da
    capability é metade do que se quer ver quando ela erra, e descartá-lo no
    caminho feliz faz o dono rodar de novo só para vê-lo.
    """

    model_config = ConfigDict(frozen=True)

    capability: str
    tool: str
    runtime: str
    status: ExecutionStatus
    output: dict[str, Any] | None = None
    error: str | None = None
    #: Alvos negados pelo guarda de permissões (`fs:/etc/passwd`, `net:host:80`).
    denied: tuple[str, ...] = ()
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    duration_ms: int = 0
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return self.status == ExecutionStatus.OK


@runtime_checkable
class RuntimeAdapter(Protocol):
    """Quem sabe executar um `runtime`. Um adapter por forma de chamar código.

    `execute()` **não levanta** por falha da capability: o desfecho é o `status`
    do resultado. Exceção fica para o que é bug do kernel — e é o kernel quem
    decide, no `run()`, o que vira exceção para quem chamou pela porta
    `ToolExecutor`.
    """

    @property
    def runtime(self) -> str:
        """Nome canônico que este adapter atende (`python`, `mcp`, `http`)."""
        ...

    async def execute(self, request: ExecutionRequest) -> ExecutionResult: ...


def truncar(bruto: bytes, limite: int) -> str:
    """Decodifica e corta, dizendo que cortou.

    Silenciosamente cortar a saída é como se perde a linha de erro que estava no
    fim dela.
    """
    if len(bruto) <= limite:
        return bruto.decode("utf-8", errors="replace")
    cortado = bruto[:limite].decode("utf-8", errors="replace")
    return f"{cortado}\n[... {len(bruto) - limite} bytes cortados]"


__all__ = [
    "RUNTIME_HTTP",
    "RUNTIME_MCP",
    "RUNTIME_PYTHON",
    "ExecutionLimits",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionStatus",
    "RuntimeAdapter",
    "truncar",
]
