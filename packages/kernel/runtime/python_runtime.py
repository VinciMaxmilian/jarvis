"""Adapter do runtime `python`: a capability roda em subprocesso próprio.

É o primeiro `RuntimeAdapter` real e o que cumpre o aceite de isolamento da v1.2
(`plan-execution.md` §3): "cada capability em subprocesso; supervisor mata em
timeout/OOM e marca a task `failed`". Este módulo é a metade que *monta* a
execução; `sandbox.py` é a que a supervisiona e `_child.py` a que roda dentro
dela.

Quatro decisões que o código sozinho não explica:

- **O pedido e o resultado são arquivos, não `argv` nem `stdout`.** Argumento de
  tool tem aspas, quebra de linha e às vezes megabytes, e nada disso sobrevive à
  linha de comando; `stdout` é da capability — o `print` de depuração dela
  atravessaria o mesmo canal do resultado e o corromperia. Um envelope JSON em
  arquivo separa "o que a capability escreveu" de "o que ela devolveu".
- **Os dois arquivos ficam em diretório temporário, nunca no da capability.** O
  `discover()` do próximo boot confere o digest do diretório contra
  `approved_commit` (D-3); escrever um `pedido.json` lá dentro faria a própria
  execução reprovar a capability na integridade.
- **O ambiente do filho é montado, não herdado.** `os.environ` do orchestrator
  tem o `.env` inteiro do dono — chave de API, senha do Postgres, segredo do
  Access. Repassá-lo daria a toda capability o que nenhuma declarou. O que passa
  é o mínimo para um interpretador rodar, mais o `PYTHONPATH` da raiz do repo, que
  é o que permite ao filho importar `packages.kernel` e o módulo da capability
  com `cwd` fora do `sys.path` (o `-P` de `python_argv`).
- **Falha nunca vira exceção aqui.** Nem a da capability, nem a do `exec`. O
  `status` do `ExecutionResult` é o canal, porque quem chama é um laço que
  processa a próxima task — e um laço que precisa de `except` para cada modo de
  falha do filho é um laço que morre no modo que ninguém previu.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import structlog

from packages.kernel.runtime.base import (
    RUNTIME_PYTHON,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
)
from packages.kernel.runtime.sandbox import SandboxOutcome, python_argv, run_sandboxed

logger = structlog.get_logger(__name__)

#: Módulo do bootstrap, rodado com `python -m` dentro do subprocesso.
MODULO_CHILD = "packages.kernel.runtime._child"

#: Nome do erro que o guarda de permissões levanta dentro do filho. Comparado
#: por string porque a exceção não atravessa processo — o que atravessa é o
#: envelope JSON, e nele o tipo é um nome.
ERRO_PERMISSAO = "PermissionDenied"

#: Variáveis do ambiente do orchestrator que fazem sentido repassar. Lista
#: fechada: ver a docstring do módulo sobre o `.env` do dono.
HERDADAS = ("PATH", "TMPDIR", "TZ", "SSL_CERT_FILE", "SSL_CERT_DIR")


def raiz_do_repo() -> Path:
    """Raiz do monorepo, deduzida da posição deste arquivo.

    `packages/kernel/runtime/python_runtime.py` → quatro níveis acima. Deduzir do
    arquivo, e não de configuração, é o que faz o adapter funcionar igual no
    container (`/app`) e num checkout qualquer da máquina do dono.
    """
    return Path(__file__).resolve().parents[3]


class PythonRuntime:
    """`RuntimeAdapter` de `runtime: python`. Um subprocesso por execução."""

    def __init__(self, *, repo_root: str | Path | None = None) -> None:
        self._repo_root = Path(repo_root) if repo_root else raiz_do_repo()

    @property
    def runtime(self) -> str:
        return RUNTIME_PYTHON

    @property
    def repo_root(self) -> Path:
        return self._repo_root

    def env(self) -> dict[str, str]:
        """Ambiente mínimo do filho. Ver a docstring do módulo."""
        base = {nome: os.environ[nome] for nome in HERDADAS if nome in os.environ}
        base["PYTHONPATH"] = str(self._repo_root)
        # O filho já roda com `-B`; a variável cobre um neto que ele venha a
        # criar, para que nada escreva `__pycache__` dentro da capability.
        base["PYTHONDONTWRITEBYTECODE"] = "1"
        # Saída de erro sem buffer: capability morta por SIGKILL não roda
        # `flush`, e o que ela imprimiu antes de travar é o que diz onde travou.
        base["PYTHONUNBUFFERED"] = "1"
        base["PYTHONIOENCODING"] = "utf-8"
        base.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
        return base

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Roda a tool em subprocesso e devolve o desfecho. Não levanta."""
        with tempfile.TemporaryDirectory(prefix="jarvis-exec-") as tmp:
            raiz = Path(tmp)
            pedido_path = raiz / "pedido.json"
            resultado_path = raiz / "resultado.json"
            pedido_path.write_text(
                json.dumps(self._pedido(request, resultado_path), ensure_ascii=False),
                encoding="utf-8",
            )

            argv = python_argv(MODULO_CHILD, str(pedido_path))
            try:
                outcome = await run_sandboxed(
                    argv,
                    cwd=request.directory,
                    env=self.env(),
                    limits=request.limits,
                )
            except OSError as exc:
                # `exec` impossível: interpretador ausente, diretório da
                # capability inexistente. É erro de instalação, não da
                # capability — e mesmo assim volta como status, não exceção.
                logger.error(
                    "kernel.exec_impossivel",
                    capability=request.capability,
                    tool=request.tool,
                    cwd=str(request.directory),
                    erro=str(exc),
                )
                return self._falha_de_kernel(request, str(exc))

            envelope = self._ler_envelope(resultado_path)

        return self._resultado(request, outcome, envelope)

    # ------------------------------------------------------------------ #
    # montagem
    # ------------------------------------------------------------------ #

    def _pedido(self, request: ExecutionRequest, destino: Path) -> dict[str, Any]:
        """O contrato de entrada de `_child.py`, em JSON."""
        return {
            "entrypoint": request.manifest.entrypoint,
            "tool": request.tool,
            "arguments": request.arguments,
            "dry_run": request.dry_run,
            "policy": request.policy().model_dump(mode="json"),
            "result_path": str(destino),
        }

    @staticmethod
    def _ler_envelope(path: Path) -> dict[str, Any] | None:
        """O envelope do filho, ou `None` se ele não chegou a escrevê-lo."""
        try:
            bruto = path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            dados = json.loads(bruto)
        except json.JSONDecodeError:
            # Envelope pela metade: o filho morreu no meio do `json.dump`. Vale
            # o mesmo que não ter envelope, e o `stderr` é que dirá o porquê.
            return None
        return dados if isinstance(dados, dict) else None

    # ------------------------------------------------------------------ #
    # tradução do desfecho
    # ------------------------------------------------------------------ #

    def _resultado(
        self,
        request: ExecutionRequest,
        outcome: SandboxOutcome,
        envelope: dict[str, Any] | None,
    ) -> ExecutionResult:
        comum: dict[str, Any] = {
            "capability": request.capability,
            "tool": request.tool,
            "runtime": self.runtime,
            "stdout": outcome.stdout,
            "stderr": outcome.stderr,
            "exit_code": outcome.exit_code,
            "duration_ms": outcome.duration_ms,
            "dry_run": request.dry_run,
        }

        if outcome.timed_out:
            # O envelope é ignorado de propósito: o que o filho escreveu antes
            # de ser morto é resultado parcial, e resultado parcial entregue
            # como completo é pior do que nenhum.
            return ExecutionResult(
                status=ExecutionStatus.TIMEOUT,
                error=(
                    f"{request.capability}.{request.tool} excedeu "
                    f"{request.limits.timeout_seconds:g}s e foi morta pelo supervisor"
                ),
                **comum,
            )

        if envelope is None:
            return ExecutionResult(
                status=ExecutionStatus.ERROR,
                error=self._sem_envelope(outcome),
                **comum,
            )

        negados = tuple(str(alvo) for alvo in envelope.get("denied") or ())

        if envelope.get("ok"):
            return ExecutionResult(
                status=ExecutionStatus.OK,
                output=envelope.get("output") or {},
                denied=negados,
                **comum,
            )

        tipo = str(envelope.get("error_type") or "")
        return ExecutionResult(
            status=(
                ExecutionStatus.DENIED
                if tipo == ERRO_PERMISSAO
                else ExecutionStatus.FAILED
            ),
            error=str(envelope.get("error") or tipo or "falha sem mensagem"),
            denied=negados,
            **comum,
        )

    @staticmethod
    def _sem_envelope(outcome: SandboxOutcome) -> str:
        """Mensagem para o caso em que o filho morreu antes de responder."""
        sinal = outcome.killed_by_signal
        if sinal is not None:
            # OOM entra aqui: `RLIMIT_AS` estourado mata o processo, e o
            # envelope nunca chega a ser escrito.
            return (
                f"o subprocesso morreu com o sinal {sinal} sem escrever resultado "
                "(limite de memória é a causa mais comum)"
            )
        return (
            f"o subprocesso saiu com {outcome.exit_code} sem escrever resultado — "
            "o bootstrap da capability falhou antes do handler"
        )

    def _falha_de_kernel(self, request: ExecutionRequest, erro: str) -> ExecutionResult:
        return ExecutionResult(
            capability=request.capability,
            tool=request.tool,
            runtime=self.runtime,
            status=ExecutionStatus.ERROR,
            error=f"não foi possível iniciar o subprocesso: {erro}",
            dry_run=request.dry_run,
        )


__all__ = ["ERRO_PERMISSAO", "HERDADAS", "MODULO_CHILD", "PythonRuntime", "raiz_do_repo"]
