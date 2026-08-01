"""Erros do kernel de execução.

Todos derivam de `KernelError` para que quem chama possa distinguir "a
capability falhou" de "o kernel falhou" sem `except Exception`.

`PermissionDenied` é o único destes erros que nasce **dentro** do subprocesso da
capability: o guarda de permissões (`packages/kernel/permissions/guard.py`) o
levanta no lugar do `open()` ou do `connect()` que ia acontecer. Ele volta ao
processo pai serializado no envelope de resultado, não como exceção — processo
não propaga stack trace por pipe — e o kernel o reconstrói para quem chamou.
"""

from __future__ import annotations


class KernelError(Exception):
    """Base dos erros do kernel."""


class RuntimeNotSupported(KernelError):
    """`manifest.runtime` não tem adapter registrado.

    Erro de configuração, não de execução: o manifest declara um executor que
    esta instalação não conhece. Nomear os disponíveis é o que transforma isso
    em conserto de uma linha de YAML.
    """

    def __init__(self, runtime: str, disponiveis: tuple[str, ...]) -> None:
        self.runtime = runtime
        self.disponiveis = disponiveis
        super().__init__(
            f"runtime sem adapter: {runtime!r}. "
            f"Disponíveis: {', '.join(sorted(disponiveis)) or 'nenhum'}"
        )


class ToolNotInCapability(KernelError):
    """A tool pedida não está declarada no manifest da capability."""

    def __init__(self, capability: str, tool: str) -> None:
        self.capability = capability
        self.tool = tool
        super().__init__(f"a capability {capability!r} não declara a tool {tool!r}")


class ExecutionTimeout(KernelError):
    """Tempo de parede estourado. O processo já foi morto quando isto sobe."""

    def __init__(self, capability: str, tool: str, seconds: float) -> None:
        self.capability = capability
        self.tool = tool
        self.seconds = seconds
        super().__init__(
            f"{capability}.{tool} excedeu {seconds:g}s de tempo de parede e foi morta"
        )


class ExecutionFailed(KernelError):
    """A capability rodou e falhou. `detail` é o erro dela, não o do kernel."""

    def __init__(self, capability: str, tool: str, detail: str) -> None:
        self.capability = capability
        self.tool = tool
        self.detail = detail
        super().__init__(f"{capability}.{tool} falhou: {detail}")


class PermissionDenied(KernelError):
    """Acesso fora do escopo declarado em `permissions` do manifest.

    `target` é o que foi negado — caminho absoluto ou `host:porta`. Ele existe
    separado da mensagem porque o aceite da v1.2 é o **alvo negado no log da
    task**, e alvo extraído de string por regex é alvo que some no primeiro
    reword da mensagem.
    """

    def __init__(self, kind: str, target: str, capability: str = "") -> None:
        self.kind = kind  # "filesystem", "network" ou "process"
        self.target = target
        self.capability = capability
        prefixo = f"{capability}: " if capability else ""
        super().__init__(
            f"{prefixo}permissão {kind} negada para {target!r} — "
            f"declare em permissions.{kind} do manifest"
        )


__all__ = [
    "ExecutionFailed",
    "ExecutionTimeout",
    "KernelError",
    "PermissionDenied",
    "RuntimeNotSupported",
    "ToolNotInCapability",
]
