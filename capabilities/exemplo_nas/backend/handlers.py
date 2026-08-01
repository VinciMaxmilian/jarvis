"""O que a capability `exemplo_nas` faz. Molde das capabilities reais da v2.

Esta é a capability de exemplo do SDK: ela existe para ser copiada. O domínio
(uma pasta de NAS) é o mesmo que `plan.md` §8 e `tools.md` usam nos exemplos, e é
o menor domínio que exercita as três coisas que uma capability real tem:

1. **Uma raiz de trabalho que vem da concessão, não do código.** `raiz` sai de
   `permissions.filesystem` do manifest. A capability não escolhe onde escreve —
   quem escolheu foi o dono no Gate 1, e é isso que faz o gate valer alguma coisa.
2. **Uma dependência externa declarada.** `nas_status` fala com o NAS pela rede e
   por isso declara `requires=ToolRequirements(network=(HOST_NAS,))`. Se o
   manifest não conceder esse host, o SDK nega **antes** de chamar o handler, com
   o host na mensagem. A sonda é injetada no construtor: o teste passa uma função
   determinística e a suíte não toca a rede.
3. **Argumento validado no schema.** Nome de arquivo com `..` é recusado pelo
   modelo de entrada, não pelo `open()`. O guarda do kernel continua embaixo, mas
   ele produz falha de task, e falha de task não diz "você digitou o caminho
   errado".

`status: pending_approval` no manifest é de propósito: nenhum Gate 2 aprovou esta
capability, o registry só carrega `active`, e um exemplo que se declarasse `active`
seria oferecido a `resolve()` numa máquina onde `/mnt/nas` não existe.
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Protocol

from capabilities.exemplo_nas.schemas import (
    ArquivoInfo,
    GravarEntrada,
    GravarSaida,
    ListarEntrada,
    ListarSaida,
    StatusEntrada,
    StatusSaida,
)
from packages.capabilities import (
    Capability,
    PermissaoNaoDeclarada,
    ToolRequirements,
    entrypoint,
    permissoes_declaradas,
    tool,
)
from packages.shared.contracts import CapabilityPermissions

#: Diretório da capability: `<repo>/capabilities/exemplo_nas`. Derivado de
#: `__file__` e não do `cwd` porque o `cwd` é do kernel no subprocesso e do pytest
#: no teste, e o manifest tem de ser achado nos dois.
DIRETORIO = Path(__file__).resolve().parents[1]

#: O NAS. Constante da implementação: é ele que a tool de status contata, e é ele
#: que o manifest tem de conceder.
HOST_NAS = "192.168.1.50"
PORTA_SMB = 445

#: Tempo de espera da sonda. Curto: "o NAS está de pé?" respondida em 30 s é uma
#: pergunta que já não interessa.
TIMEOUT_SONDA = 2.0


class Sonda(Protocol):
    """Diz se `host:porta` aceita conexão. Injetável para o teste não usar rede."""

    def __call__(self, host: str, porta: int) -> bool: ...


def sonda_tcp(host: str, porta: int) -> bool:  # pragma: no cover — exige rede
    """Sonda real. Fora do teste por construção: a suíte roda sem rede."""
    try:
        with socket.create_connection((host, porta), timeout=TIMEOUT_SONDA):
            return True
    except OSError:
        return False


class NasArquivos(Capability):
    """Lista, grava e confere uma pasta do NAS de casa."""

    name = "exemplo_nas"
    version = "0.1.0"
    description = "Lista e grava arquivos numa pasta do NAS de casa."
    trigger_intents = (
        "listar arquivos do NAS",
        "gravar arquivo no NAS",
        "conferir se o NAS responde",
    )
    #: `python` é o adapter que chama `entrypoint(tool, arguments)` em subprocesso
    #: (`packages/kernel/runtime/_child.py`). Uma capability que expusesse as tools
    #: por um servidor MCP declararia `mcp` e nada mais mudaria aqui.
    runtime = "python"

    def __init__(
        self,
        permissions: CapabilityPermissions | None = None,
        *,
        sonda: Sonda | None = None,
    ) -> None:
        super().__init__(permissions)
        self._sonda: Sonda = sonda or sonda_tcp

    @property
    def raiz(self) -> Path:
        """A pasta concedida. Sem concessão não há onde trabalhar.

        Levantar `PermissaoNaoDeclarada` aqui — e não `IndexError` — é o que faz a
        mensagem dizer o conserto: declare `permissions.filesystem` no manifest.
        """
        if not self.permissions.filesystem:
            raise PermissaoNaoDeclarada(
                "filesystem", "<raiz de trabalho>", self.name
            )
        return Path(self.permissions.filesystem[0])

    @tool(
        description="Lista os arquivos de uma pasta do NAS, sem entrar em subpastas.",
        entrada=ListarEntrada,
        saida=ListarSaida,
        idempotent=True,
    )
    def nas_listar(self, entrada: ListarEntrada) -> ListarSaida:
        alvo = self.raiz / entrada.subcaminho if entrada.subcaminho else self.raiz
        if not alvo.is_dir():
            return ListarSaida(arquivos=[], total=0)
        arquivos = [
            ArquivoInfo(nome=p.name, bytes=p.stat().st_size)
            for p in sorted(alvo.iterdir(), key=lambda p: p.name)
            if p.is_file()
        ]
        return ListarSaida(arquivos=arquivos, total=len(arquivos))

    @tool(
        description="Grava um arquivo de texto na pasta do NAS.",
        entrada=GravarEntrada,
        saida=GravarSaida,
    )
    def nas_gravar(self, entrada: GravarEntrada) -> GravarSaida:
        destino = self.raiz / entrada.nome
        destino.parent.mkdir(parents=True, exist_ok=True)
        gravados = destino.write_text(entrada.conteudo, encoding="utf-8")
        return GravarSaida(caminho=str(destino), bytes=gravados)

    @tool(
        description="Confere se o NAS responde na porta de compartilhamento.",
        entrada=StatusEntrada,
        saida=StatusSaida,
        requires=ToolRequirements(network=(HOST_NAS,)),
        idempotent=True,
    )
    def nas_status(self, entrada: StatusEntrada) -> StatusSaida:
        return StatusSaida(
            host=HOST_NAS,
            porta=PORTA_SMB,
            online=self._sonda(HOST_NAS, PORTA_SMB),
        )


def construir() -> NasArquivos:
    """A capability sob a concessão que está no manifest em disco.

    É a fábrica que o kernel usa. Ela lê o `manifest.yaml` — leitura, que o guarda
    de permissões não restringe (`packages/kernel/permissions/policy.py`) — e monta
    a instância com a concessão que o dono aprovou, nunca com uma inventada aqui.
    """
    return NasArquivos(permissoes_declaradas(DIRETORIO))


#: O que `manifest.entrypoint` aponta: `atributo(tool, arguments) -> dict`.
main = entrypoint(construir)

__all__ = [
    "DIRETORIO",
    "HOST_NAS",
    "PORTA_SMB",
    "NasArquivos",
    "Sonda",
    "construir",
    "main",
    "sonda_tcp",
]
