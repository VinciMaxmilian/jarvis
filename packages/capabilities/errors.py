"""Erros do Capability SDK.

Todos derivam de `CapabilitySDKError` para que quem chama distinga "a capability
está mal declarada" de "a chamada está errada" sem `except Exception`.

Nenhum destes erros é enforcement de runtime. O SDK **declara** e recusa o que
contradiz a declaração; quem intercepta `open()` e `connect()` de verdade é
`packages/kernel/permissions` (`plan.md` §9). A diferença aparece em
`PermissaoNaoDeclarada`: ela nasce *antes* de o handler rodar, porque a tool diz
estaticamente de que precisa e o manifest diz o que foi concedido — comparar os
dois é aritmética de declaração, não interceptação de chamada.

Todo erro que aponta defeito de autoria carrega `Problema`, e não uma string: o
aceite é "erro nomeando o campo", e campo extraído de mensagem por regex some no
primeiro reword da mensagem.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict


class Problema(BaseModel):
    """Um defeito localizado: onde está e o que há de errado.

    `campo` usa o caminho pontuado do YAML (`permissions.network`, `tools.0.name`)
    para que a mensagem aponte a linha do arquivo, e não o arquivo inteiro.
    """

    model_config = ConfigDict(frozen=True)

    campo: str
    mensagem: str

    def __str__(self) -> str:
        return f"{self.campo}: {self.mensagem}"


def formatar(problemas: Sequence[Problema]) -> str:
    """Lista de problemas em bloco legível de mensagem de exceção."""
    return "\n".join(f"  - {p}" for p in problemas)


class CapabilitySDKError(Exception):
    """Base dos erros do SDK."""


class DeclaracaoInvalida(CapabilitySDKError):
    """A classe da capability está mal declarada.

    Levanta na **criação da classe**, ou seja, no import do módulo. É agressivo de
    propósito: uma capability sem nome, sem tool ou com duas tools de mesmo nome
    não tem execução correta possível, e descobrir isso na primeira chamada é
    descobrir tarde. Para a v3, que gera a classe, o erro no import é o feedback
    mais barato que existe.
    """

    def __init__(self, capability: str, problemas: Sequence[Problema]) -> None:
        self.capability = capability
        self.problemas = tuple(problemas)
        super().__init__(
            f"capability {capability or '<sem nome>'} mal declarada:\n"
            f"{formatar(self.problemas)}"
        )


class ManifestInvalido(CapabilitySDKError):
    """`manifest.yaml` ou `permissions.yaml` fora do contrato.

    Traz **todos** os problemas de uma vez, não o primeiro: consertar um campo
    por execução transforma revisão de manifest em laço, e é o tipo de laço que
    a v3 pagaria em token a cada volta.
    """

    def __init__(self, origem: object, problemas: Sequence[Problema]) -> None:
        self.origem = str(origem)
        self.problemas = tuple(problemas)
        super().__init__(f"manifest inválido em {self.origem}:\n{formatar(problemas)}")


class ToolDesconhecida(CapabilitySDKError):
    """A tool pedida não existe na capability. Nomear as que existem é o conserto."""

    def __init__(self, capability: str, tool: str, disponiveis: Sequence[str]) -> None:
        self.capability = capability
        self.tool = tool
        self.disponiveis = tuple(disponiveis)
        super().__init__(
            f"{capability} não declara a tool {tool!r}. "
            f"Declaradas: {', '.join(self.disponiveis) or 'nenhuma'}"
        )


class EntradaInvalida(CapabilitySDKError):
    """Os argumentos não casam com o `input_schema` declarado pela tool."""

    def __init__(self, capability: str, tool: str, problemas: Sequence[Problema]) -> None:
        self.capability = capability
        self.tool = tool
        self.problemas = tuple(problemas)
        super().__init__(
            f"entrada inválida para {capability}.{tool}:\n{formatar(problemas)}"
        )


class SaidaInvalida(CapabilitySDKError):
    """O handler devolveu algo diferente do que a tool declarou devolver.

    Existe porque o retorno da capability vira `Task.output` e é lido pelo Chief
    AI: saída fora do schema declarado é o mesmo que mentir no catálogo.
    """

    def __init__(self, capability: str, tool: str, detalhe: str) -> None:
        self.capability = capability
        self.tool = tool
        self.detalhe = detalhe
        super().__init__(f"saída inválida de {capability}.{tool}: {detalhe}")


class PermissaoNaoDeclarada(CapabilitySDKError):
    """A tool exige um alvo que o manifest não concedeu.

    `kind` e `target` vêm separados da mensagem pelo mesmo motivo do
    `PermissionDenied` do kernel: o alvo negado é o que vai para o log da task, e
    ele não pode depender do texto da mensagem.

    Isto **não** substitui o guarda do kernel. Aqui a negação é estática — a tool
    declarou `network: ["api.x"]`, o manifest não declarou, e nenhuma chamada
    chega a acontecer. O alvo dinâmico (o caminho que veio no argumento) é do
    kernel, que é quem vê a chamada de verdade.
    """

    def __init__(
        self, kind: str, target: str, capability: str = "", tool: str = ""
    ) -> None:
        self.kind = kind  # "filesystem", "network" ou "process"
        self.target = target
        self.capability = capability
        self.tool = tool
        origem = ".".join(p for p in (capability, tool) if p)
        prefixo = f"{origem}: " if origem else ""
        super().__init__(
            f"{prefixo}permissão {kind} não declarada para {target!r} — "
            f"a tool exige, o manifest não concede. "
            f"Declare em permissions.{kind} ou tire a exigência da tool"
        )


__all__ = [
    "CapabilitySDKError",
    "DeclaracaoInvalida",
    "EntradaInvalida",
    "ManifestInvalido",
    "PermissaoNaoDeclarada",
    "Problema",
    "SaidaInvalida",
    "ToolDesconhecida",
    "formatar",
]
