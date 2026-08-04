"""O que a capability `shell` faz: roda um programa externo e devolve o que saiu.

Esta é a capability mais perigosa do sistema, e o desenho inteiro existe para
limitar o estrago. Quatro decisões, nesta ordem de importância:

1. **Nunca `shell=True`, nem por acidente.** O schema separa `programa` de
   `argumentos` e `argumentos` é uma **lista**. Não existe um ponto no código onde
   uma string de comando seja montada, então não existe onde `;`, `|`, `&&`, `>`
   ou `*` sejam interpretados por alguém. `subprocess.run` recebe o vetor pronto.
2. **Allowlist.** `programa` tem de ser um nome simples e estar na lista de
   permitidos. Fora dela, `PermissaoNaoDeclarada("process", programa)` — o mesmo
   erro que o SDK usa quando o manifest não concede um alvo, porque é o mesmo tipo
   de negação: o dono não autorizou este alvo. A lista é configurável em
   `allowlist.yaml` ao lado do manifest, sem tocar em código.
3. **Timeout obrigatório, com teto.** `timeout` tem default de 30 s e máximo de
   300 s no próprio schema. Processo que estoura é morto e o resultado volta com
   `expirou: true`, não como exceção: "o comando travou" é resposta, e o kernel já
   tem supervisor e job agendado para trabalho longo.
4. **`cwd` dentro da concessão.** O diretório de trabalho é conferido contra
   `permissions.filesystem` com `concedido()`, a mesma função do harness.

**O que isto não protege.** A allowlist restringe *qual* programa roda, não o que
ele faz: `python` na lista é execução de código arbitrário, e `git` na lista é
`git config core.pager` apontando para o que o atacante quiser. O processo herda o
ambiente e as credenciais do kernel. A allowlist padrão é conservadora por isso, e
a decisão de aumentá-la é do dono no Gate 1 — está documentada em `docs/README.md`
com esse nome: risco, não configuração.

`exit_code` diferente de zero **não** é falha da tool. Ver `ExecutarSaida`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn, Protocol

import yaml
from pydantic import BaseModel, ConfigDict

from capabilities.shell.schemas import (
    MAX_SAIDA,
    ExecutarEntrada,
    ExecutarSaida,
    PermitidosEntrada,
    PermitidosSaida,
)
from packages.capabilities import (
    Capability,
    EntradaInvalida,
    PermissaoNaoDeclarada,
    Problema,
    ToolRequirements,
    concedido,
    entrypoint,
    permissoes_declaradas,
    tool,
)
from packages.shared.contracts import CapabilityPermissions

#: Diretório da capability. Derivado de `__file__` e não do `cwd`: o `cwd` é o do
#: kernel no subprocesso e o do pytest no teste.
DIRETORIO = Path(__file__).resolve().parents[1]

#: Onde a allowlist mora quando o dono quer uma diferente da padrão.
NOME_ALLOWLIST = "allowlist.yaml"

#: A allowlist de fábrica. Curta de propósito: cada nome acrescentado aqui é uma
#: superfície de execução a mais, e a lista certa é a do dono, não a do autor.
#: `python` já está nela porque sem ele a capability não serve para nada dentro
#: deste repositório — e é justamente ele que faz a allowlist não ser uma sandbox.
PERMITIDOS_PADRAO: tuple[str, ...] = (
    "git",
    "python",
    "pytest",
    "ruff",
    "black",
    "mypy",
)


class Resultado(BaseModel):
    """O que um executor devolve. Fronteira entre o `subprocess` e a tool."""

    model_config = ConfigDict(frozen=True)

    exit_code: int | None
    stdout: str
    stderr: str
    expirou: bool = False


class Executor(Protocol):
    """Roda o vetor de comando. Injetável para o teste não depender do `PATH`."""

    def __call__(
        self, comando: Sequence[str], *, cwd: str, timeout: float
    ) -> Resultado: ...


def executor_subprocess(
    comando: Sequence[str], *, cwd: str, timeout: float
) -> Resultado:
    """O executor real. `shell=False` é o default e está explícito aqui de propósito.

    Explícito porque este é o único lugar do repositório onde a linha
    `shell=True` poderia ser escrita sem parecer errada, e um leitor tem de poder
    confirmar que ela não está aqui sem ler o resto do arquivo.
    """
    try:
        concluido = subprocess.run(  # noqa: S603 — vetor, nunca string; shell=False
            list(comando),
            shell=False,
            cwd=cwd,
            timeout=timeout,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as expirado:
        return Resultado(
            exit_code=None,
            stdout=_texto(expirado.stdout),
            stderr=_texto(expirado.stderr),
            expirou=True,
        )
    return Resultado(
        exit_code=concluido.returncode,
        stdout=concluido.stdout or "",
        stderr=concluido.stderr or "",
        expirou=False,
    )


def _texto(bruto: object) -> str:
    """O que o `TimeoutExpired` traz pode ser `bytes`, `str` ou `None`."""
    if bruto is None:
        return ""
    if isinstance(bruto, bytes):
        return bruto.decode("utf-8", errors="replace")
    return str(bruto)


def carregar_allowlist(directory: Path) -> tuple[str, ...]:
    """A allowlist do disco, ou a padrão se o arquivo não existir.

    Arquivo ausente **não** é erro: a capability funciona com a lista de fábrica.
    Arquivo presente e torto é erro, porque uma allowlist que não carrega e cai
    silenciosamente na padrão é uma restrição que o dono acha que aplicou.
    """
    caminho = directory / NOME_ALLOWLIST
    if not caminho.is_file():
        return PERMITIDOS_PADRAO

    bruto = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    if bruto is None:
        return ()
    if isinstance(bruto, dict):
        bruto = bruto.get("permitidos", [])
    if not isinstance(bruto, list):
        raise ValueError(
            f"{caminho}: a allowlist tem de ser uma lista de nomes de programa, "
            f"veio {type(bruto).__name__}"
        )
    return tuple(dict.fromkeys(str(item).strip() for item in bruto if str(item).strip()))


class Shell(Capability):
    """Executa um programa da allowlist e devolve stdout, stderr e código de saída."""

    name = "shell"
    version = "0.1.0"
    description = (
        "Executa um programa da allowlist com timeout e devolve stdout, stderr e "
        "código de saída, sem passar por shell."
    )
    trigger_intents = (
        "executar um comando",
        "rodar um programa no terminal",
        "rodar os testes do projeto",
        "ver quais comandos são permitidos",
    )
    runtime = "python"

    def __init__(
        self,
        permissions: CapabilityPermissions | None = None,
        *,
        permitidos: Sequence[str] | None = None,
        executor: Executor | None = None,
    ) -> None:
        """`permitidos` e `executor` são injeção, no mesmo molde da sonda do NAS.

        O default de `permitidos` é a lista de fábrica, e não a do disco: ler o
        disco no construtor faria construir a capability depender de arquivo, e
        quem lê o disco é `construir()`, que é o caminho do kernel.
        """
        super().__init__(permissions)
        self._permitidos = tuple(
            permitidos if permitidos is not None else PERMITIDOS_PADRAO
        )
        self._executor: Executor = executor or executor_subprocess

    # ------------------------------------------------------------------ #
    # fronteira
    # ------------------------------------------------------------------ #

    @property
    def permitidos(self) -> tuple[str, ...]:
        """A allowlist sob a qual esta instância roda."""
        return self._permitidos

    @property
    def raiz(self) -> Path:
        """A primeira pasta concedida. É o `cwd` default de todo comando."""
        if not self.permissions.filesystem:
            raise PermissaoNaoDeclarada(
                "filesystem", "<raiz de trabalho>", self.name
            )
        return Path(self.permissions.filesystem[0])

    def _recusar(self, tool_name: str, campo: str, mensagem: str) -> NoReturn:
        """Falha de execução em erro do SDK, nomeando o campo. Nunca `OSError` cru."""
        raise EntradaInvalida(
            self.name, tool_name, [Problema(campo=campo, mensagem=mensagem)]
        )

    def _conferir_allowlist(self, programa: str) -> None:
        """Fora da allowlist é negação de escopo, não erro de argumento.

        Por isso `PermissaoNaoDeclarada` e não `EntradaInvalida`: o argumento está
        bem formado, o que falta é autorização — e é `kind`/`target` que vão para
        o log da task, não o texto da mensagem.
        """
        alvo = programa.casefold()
        if alvo not in {p.casefold() for p in self._permitidos}:
            raise PermissaoNaoDeclarada(
                "process", programa, self.name, "shell_executar"
            )

    def _resolver_cwd(self, cwd: str) -> Path:
        """O diretório de trabalho, conferido contra `permissions.filesystem`."""
        pedido = Path(cwd) if cwd else self.raiz
        alvo = pedido if pedido.is_absolute() else self.raiz / pedido
        alvo = Path(os.path.normpath(os.path.abspath(alvo)))

        if not concedido("filesystem", str(alvo), self.permissions):
            raise PermissaoNaoDeclarada(
                "filesystem", str(alvo), self.name, "shell_executar"
            )
        if not alvo.is_dir():
            self._recusar(
                "shell_executar", "cwd", f"não existe ou não é uma pasta: {alvo}"
            )
        return alvo

    # ------------------------------------------------------------------ #
    # tools
    # ------------------------------------------------------------------ #

    @tool(
        description=(
            "Executa um programa da allowlist com os argumentos dados e devolve "
            "stdout, stderr e código de saída. Não passa por shell."
        ),
        entrada=ExecutarEntrada,
        saida=ExecutarSaida,
        requires=ToolRequirements(process=True),
        #: Iniciar processo externo é o efeito que o dono mais precisa ver antes
        #: de acontecer: o que o programa faz está fora do alcance deste código.
        requires_approval=True,
    )
    def shell_executar(self, entrada: ExecutarEntrada) -> ExecutarSaida:
        self._conferir_allowlist(entrada.programa)
        cwd = self._resolver_cwd(entrada.cwd)

        caminho = shutil.which(entrada.programa)
        if caminho is None:
            self._recusar(
                "shell_executar",
                "programa",
                (
                    f"{entrada.programa!r} está na allowlist mas não foi achado no "
                    "PATH deste processo"
                ),
            )

        comando = [caminho, *entrada.argumentos]
        try:
            resultado = self._executor(comando, cwd=str(cwd), timeout=entrada.timeout)
        except OSError as exc:
            self._recusar(
                "shell_executar",
                "programa",
                f"não deu para executar {entrada.programa!r}: {exc}",
            )

        stdout, cortou_saida = _cortar(resultado.stdout)
        stderr, cortou_erro = _cortar(resultado.stderr)
        return ExecutarSaida(
            programa=entrada.programa,
            argumentos=list(entrada.argumentos),
            exit_code=resultado.exit_code,
            stdout=stdout,
            stderr=stderr,
            truncado=cortou_saida or cortou_erro,
            expirou=resultado.expirou,
            cwd=str(cwd),
        )

    @tool(
        description=(
            "Lista os programas que esta capability tem autorização para executar."
        ),
        entrada=PermitidosEntrada,
        saida=PermitidosSaida,
        idempotent=True,
    )
    def shell_listar_permitidos(self, entrada: PermitidosEntrada) -> PermitidosSaida:
        """Existe para o Chief AI perguntar antes de tentar.

        Sem ela, descobrir que `curl` não é permitido custa uma task falhada; com
        ela custa uma chamada idempotente que não inicia processo nenhum — e por
        isso esta tool **não** declara `process`.
        """
        return PermitidosSaida(
            permitidos=list(self._permitidos), total=len(self._permitidos)
        )


def _cortar(texto: str) -> tuple[str, bool]:
    """Corta o fluxo no teto e diz se cortou. O aviso vai no corpo, não só na flag."""
    if len(texto) <= MAX_SAIDA:
        return texto, False
    return texto[:MAX_SAIDA] + "\n[...saída cortada em MAX_SAIDA...]", True


def construir() -> Shell:
    """A capability sob a concessão e a allowlist que estão em disco.

    É a fábrica que o kernel usa. Lê o `manifest.yaml` e o `allowlist.yaml` —
    leitura, que o guarda de permissões não restringe — e monta a instância com o
    que o dono aprovou, nunca com uma lista inventada aqui.
    """
    return Shell(
        permissoes_declaradas(DIRETORIO), permitidos=carregar_allowlist(DIRETORIO)
    )


#: O que `manifest.entrypoint` aponta: `atributo(tool, arguments) -> dict`.
main = entrypoint(construir)

__all__ = [
    "DIRETORIO",
    "NOME_ALLOWLIST",
    "PERMITIDOS_PADRAO",
    "Executor",
    "Resultado",
    "Shell",
    "carregar_allowlist",
    "construir",
    "executor_subprocess",
    "main",
]
