# Capability SDK

Como se declara, se valida e se testa uma capability. Especificação em `plan.md` §7;
layout em disco em `plan-scheme.md`; contrato de dados em `packages/shared/contracts.py`.

**MCP é o padrão de tools. O SDK envolve e expõe MCP, não o substitui** (`tools.md` §7).
O que sai daqui é `ToolSpec` com `input_schema` em JSON Schema — o formato de tool do
MCP. O SDK acrescenta o que o MCP não cobre neste caso: manifest com estado e aprovação,
permissão declarada e o ciclo de vida da §7.

**O SDK declara; o kernel executa e nega.** Nenhuma linha daqui intercepta `open()` ou
`connect()` — isso é `packages/kernel/permissions`, roda dentro do subprocesso da
capability e vê a chamada de verdade. O que o SDK nega é a *contradição entre
declarações*: a tool que exige um host que o manifest não concede não chega a rodar.

## Superfície

| Onde | O quê |
|---|---|
| `base.py` | `Capability`, `@tool`, `ToolRequirements`, `entrypoint()`, `Ensaio` |
| `manifest.py` | carga e validação de `manifest.yaml` + `permissions.yaml`, e a geração dos dois |
| `harness.py` | `CapabilityHarness`, `CasoDeTool`, `Relatorio` — o contrato de teste |
| `errors.py` | os erros, todos carregando `Problema(campo, mensagem)` |

Molde completo e funcionando: `capabilities/exemplo_nas/`.

## Escrever uma capability

```python
class NasArquivos(Capability):
    name = "exemplo_nas"          # slug: é o diretório e o sufixo da branch
    version = "0.1.0"
    description = "Lista e grava arquivos numa pasta do NAS de casa."
    trigger_intents = ("listar arquivos do NAS",)
    runtime = "python"

    @tool(
        description="Confere se o NAS responde.",
        entrada=StatusEntrada,     # modelo Pydantic -> input_schema
        saida=StatusSaida,         # modelo Pydantic -> output_schema
        idempotent=True,
        requires=ToolRequirements(network=("192.168.1.50",)),
    )
    def nas_status(self, entrada: StatusEntrada) -> StatusSaida: ...

main = entrypoint(lambda: NasArquivos(permissoes_declaradas(DIRETORIO)))
```

Quatro regras que o SDK impõe, e cada uma tem teste:

1. **A concessão vem do manifest, não da classe.** `permissions` chega no construtor.
   Fosse atributo de classe, o código concederia a si mesmo o que quisesse.
2. **A tool declara o que exige (`requires`); o manifest concede.** Exigir sem conceder
   é `PermissaoNaoDeclarada` antes de o handler rodar, com o alvo na mensagem.
3. **Entrada e saída são modelos.** Dicionário só nas duas pontas, que é o formato de
   `Task.input`/`Task.output`.
4. **`dry_run` não chama o handler.** Ele devolve o `Ensaio`: o que faria, com quais
   argumentos, tocando o quê.

`entrypoint()` produz o chamável que `packages/kernel/runtime/_child.py` invoca:
`atributo(tool, arguments) -> dict`.

## Gerar o manifest

Não se digita `manifest.yaml`:

```python
manifest = manifest_de(
    NasArquivos, entrypoint="capabilities.exemplo_nas.backend.handlers:main"
)
escrever_arquivos(DIRETORIO, manifest, trigger_intents=NasArquivos.trigger_intents)
```

Só três coisas não saem da classe: `entrypoint` (onde o código foi instalado), `status` e
`approved_commit` (o que o gate decidiu). `permissions.yaml` é o espelho legível do bloco
`permissions` do manifest — gerado, e conferido pelo harness contra o manifest, porque o
dono aprova lendo um arquivo e o kernel aplica o outro.

## Testar

`tests/test_<name>.py` dentro da capability. Capability sem `tests/` não passa do Gate 2.

```python
relatorio = CapabilityHarness(DIRETORIO, MinhaCapability(concessao)).rodar(CASOS)
assert relatorio.ok, relatorio.resumo()
```

A concessão do teste pode diferir da do manifest (o `tmp_path` no lugar do NAS): a
conferência estática usa a do manifest, a execução usa a da instância.

`erros` reprovam; `avisos` são o que o dono precisa ver e pode aceitar (`approved_commit`
ainda nulo, host concedido que nenhuma tool usa, `docs/README.md` ausente).
