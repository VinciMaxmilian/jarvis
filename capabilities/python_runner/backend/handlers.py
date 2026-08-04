from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path
from typing import NoReturn

from capabilities.python_runner.schemas import (
    MAX_SAIDA,
    RunPythonEntrada,
    RunPythonSaida,
)
from packages.capabilities import (
    Capability,
    EntradaInvalida,
    PermissaoNaoDeclarada,
    Problema,
    ToolRequirements,
    entrypoint,
    permissoes_declaradas,
    tool,
)

DIRETORIO = Path(__file__).resolve().parents[1]


class PythonRunner(Capability):
    """Executa scripts Python e devolve a saída."""

    name = "python_runner"
    version = "0.1.0"
    description = (
        "Executa um trecho de código Python passado via argumento e devolve "
        "stdout, stderr e código de saída."
    )
    trigger_intents = (
        "executar um script python",
        "rodar código python interativo",
        "avaliar expressão python",
    )
    runtime = "python"

    def _recusar(self, tool_name: str, campo: str, mensagem: str) -> NoReturn:
        raise EntradaInvalida(
            self.name, tool_name, [Problema(campo=campo, mensagem=mensagem)]
        )

    @tool(
        description="Executa código Python e retorna a saída.",
        entrada=RunPythonEntrada,
        saida=RunPythonSaida,
        requires=ToolRequirements(process=True),
        requires_approval=True,
    )
    def run_python_code(self, entrada: RunPythonEntrada) -> RunPythonSaida:
        if not self.permissions.filesystem:
            raise PermissaoNaoDeclarada(
                "filesystem", "<raiz de trabalho>", self.name, "run_python_code"
            )
        
        cwd = Path(self.permissions.filesystem[0])
        if not cwd.is_dir():
            self._recusar("run_python_code", "cwd", f"não existe ou não é uma pasta: {cwd}")

        # Grava o script num arquivo temporário e executa.
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".py", delete=False) as f:
            f.write(entrada.codigo)
            script_path = f.name
            
        comando = [sys.executable, script_path]

        try:
            concluido = subprocess.run(
                comando,
                cwd=str(cwd),
                timeout=entrada.timeout,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as expirado:
            # Apaga o script em caso de timeout
            Path(script_path).unlink(missing_ok=True)
            return RunPythonSaida(
                exit_code=None,
                stdout=_cortar(_texto(expirado.stdout))[0],
                stderr=_cortar(_texto(expirado.stderr))[0],
                expirou=True,
                truncado=False,
            )
        except OSError as exc:
            Path(script_path).unlink(missing_ok=True)
            self._recusar(
                "run_python_code",
                "codigo",
                f"não deu para executar o script: {exc}",
            )

        Path(script_path).unlink(missing_ok=True)

        stdout, cortou_saida = _cortar(concluido.stdout or "")
        stderr, cortou_erro = _cortar(concluido.stderr or "")

        return RunPythonSaida(
            exit_code=concluido.returncode,
            stdout=stdout,
            stderr=stderr,
            truncado=cortou_saida or cortou_erro,
            expirou=False,
        )


def _texto(bruto: object) -> str:
    if bruto is None:
        return ""
    if isinstance(bruto, bytes):
        return bruto.decode("utf-8", errors="replace")
    return str(bruto)


def _cortar(texto: str) -> tuple[str, bool]:
    if len(texto) <= MAX_SAIDA:
        return texto, False
    return texto[:MAX_SAIDA] + "\n[...saída cortada...]", True


def construir() -> PythonRunner:
    return PythonRunner(permissoes_declaradas(DIRETORIO))


main = entrypoint(construir)

__all__ = ["DIRETORIO", "PythonRunner", "construir", "main"]
