from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import NoReturn

from capabilities.git.schemas import (
    MAX_SAIDA,
    GitEntrada,
    GitSaida,
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


class Git(Capability):
    """Executa comandos git de forma segura."""

    name = "git"
    version = "0.1.0"
    description = "Integração segura para comandos git locais."
    trigger_intents = (
        "fazer commit no git",
        "verificar status do repositório",
        "puxar ou enviar código via git",
    )
    runtime = "python"

    def _recusar(self, tool_name: str, campo: str, mensagem: str) -> NoReturn:
        raise EntradaInvalida(
            self.name, tool_name, [Problema(campo=campo, mensagem=mensagem)]
        )

    def _resolver_cwd(self, cwd: str) -> Path:
        if not self.permissions.filesystem:
            raise PermissaoNaoDeclarada("filesystem", "<raiz de trabalho>", self.name, "git_exec")
        raiz = Path(self.permissions.filesystem[0])
        pedido = Path(cwd) if cwd else raiz
        alvo = pedido if pedido.is_absolute() else raiz / pedido
        alvo = Path(os.path.normpath(os.path.abspath(alvo)))

        if not str(alvo).startswith(str(raiz)):
            raise PermissaoNaoDeclarada("filesystem", str(alvo), self.name, "git_exec")
        if not alvo.is_dir():
            self._recusar("git_exec", "cwd", f"não existe ou não é uma pasta: {alvo}")
        return alvo

    @tool(
        description="Executa o comando git especificado.",
        entrada=GitEntrada,
        saida=GitSaida,
        requires=ToolRequirements(process=True),
        requires_approval=True,
    )
    def git_exec(self, entrada: GitEntrada) -> GitSaida:
        cwd = self._resolver_cwd(entrada.cwd)
        caminho_git = shutil.which("git")
        if caminho_git is None:
            self._recusar("git_exec", "git", "o executável git não foi encontrado no PATH.")

        comando = [caminho_git, *entrada.argumentos]

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
            return GitSaida(
                exit_code=None,
                stdout=_cortar(_texto(expirado.stdout))[0],
                stderr=_cortar(_texto(expirado.stderr))[0],
                expirou=True,
                truncado=False,
            )
        except OSError as exc:
            self._recusar("git_exec", "git", f"falha ao executar git: {exc}")

        stdout, cortou_saida = _cortar(concluido.stdout or "")
        stderr, cortou_erro = _cortar(concluido.stderr or "")

        return GitSaida(
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


def construir() -> Git:
    return Git(permissoes_declaradas(DIRETORIO))


main = entrypoint(construir)

__all__ = ["DIRETORIO", "Git", "construir", "main"]
