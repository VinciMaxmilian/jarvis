"""Capability SDK — como se declara, se valida e se testa uma capability.

`plan.md` §7. Uma capability é um mini software com fronteira explícita: manifest,
permissões declaradas, schema de entrada e saída, implementação, testes. O SDK é
essa fronteira em código; `capabilities/exemplo_nas/` é o molde completo.

**MCP é o padrão de tools. O SDK envolve e expõe MCP, não o substitui**
(`tools.md` §7). O que sai daqui é `ToolSpec` com `input_schema` em JSON Schema —
o formato de tool do MCP — e o transporte é do kernel. O SDK acrescenta o que o
MCP não cobre neste caso: manifest com estado e aprovação, permissão declarada, e
o ciclo de vida da §7.

**Divisão de trabalho com o kernel: o SDK declara, o kernel executa e nega.**
Nenhuma linha daqui intercepta `open()` ou `connect()` — isso é
`packages/kernel/permissions`, roda dentro do subprocesso da capability e vê a
chamada de verdade. O que o SDK nega é a *contradição entre declarações*: a tool
que exige um host que o manifest não concede não chega a rodar, e a mensagem diz
qual host e onde declará-lo. Duplicar o enforcement daria dois lugares para
consertar e um para esquecer.

Superfície estável (é contra ela que a v3 gera código — `plan.md` §8):

```python
from packages.capabilities import Capability, CapabilityHarness, tool

class Notas(Capability):
    name = "notas"
    version = "0.1.0"
    description = "Guarda e lê notas em texto."
    trigger_intents = ("guardar uma nota",)

    @tool(description="Grava uma nota.", entrada=GravarEntrada, saida=GravarSaida)
    def nota_gravar(self, entrada: GravarEntrada) -> GravarSaida: ...

main = entrypoint(lambda: Notas(permissoes_declaradas(DIRETORIO)))
```

O manifest **não** é digitado: `manifest_de()` o monta da classe e
`escrever_arquivos()` grava os dois arquivos coerentes. O que não sai da classe é
`entrypoint`, `status` e `approved_commit` — onde o código foi instalado e o que o
gate decidiu. Nenhum dos três pode ser o código dizendo de si mesmo que está
aprovado.
"""

from __future__ import annotations

from packages.capabilities.base import (
    Capability,
    Ensaio,
    Handler,
    ToolDeclaration,
    ToolRequirements,
    alvos_nao_concedidos,
    concedido,
    entrypoint,
    especificacoes,
    tool,
)
from packages.capabilities.errors import (
    CapabilitySDKError,
    DeclaracaoInvalida,
    EntradaInvalida,
    ManifestInvalido,
    PermissaoNaoDeclarada,
    Problema,
    SaidaInvalida,
    ToolDesconhecida,
)
from packages.capabilities.harness import CapabilityHarness, CasoDeTool, Relatorio
from packages.capabilities.manifest import (
    NOME_MANIFEST,
    NOME_PERMISSOES,
    ArquivosDaCapability,
    carregar_arquivos,
    escrever_arquivos,
    manifest_de,
    permissoes_declaradas,
    render_manifest_yaml,
    render_permissions_yaml,
)

__all__ = [
    "NOME_MANIFEST",
    "NOME_PERMISSOES",
    "ArquivosDaCapability",
    "Capability",
    "CapabilityHarness",
    "CapabilitySDKError",
    "CasoDeTool",
    "DeclaracaoInvalida",
    "Ensaio",
    "EntradaInvalida",
    "Handler",
    "ManifestInvalido",
    "PermissaoNaoDeclarada",
    "Problema",
    "Relatorio",
    "SaidaInvalida",
    "ToolDeclaration",
    "ToolDesconhecida",
    "ToolRequirements",
    "alvos_nao_concedidos",
    "carregar_arquivos",
    "concedido",
    "entrypoint",
    "escrever_arquivos",
    "especificacoes",
    "manifest_de",
    "permissoes_declaradas",
    "render_manifest_yaml",
    "render_permissions_yaml",
    "tool",
]
