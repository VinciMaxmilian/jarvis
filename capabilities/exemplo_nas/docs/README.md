# exemplo_nas — capability de exemplo do SDK

Molde completo de uma capability escrita contra o `packages/capabilities`. Existe
para ser **copiada** quando as capabilities reais da v2 forem escritas
(`plan-execution.md` §4, v2.1), não para ser usada.

## O que faz

| Tool | O que faz | Exige |
|---|---|---|
| `nas_listar` | Lista os arquivos de uma pasta da raiz concedida, sem recursão. | nada além da concessão |
| `nas_gravar` | Grava um arquivo de texto na raiz concedida. | nada além da concessão |
| `nas_status` | Confere se o NAS aceita conexão na porta 445. | `network: 192.168.1.50` |

Exemplo de chamada, como o kernel a faz:

```python
from capabilities.exemplo_nas.backend.handlers import main

main("nas_gravar", {"nome": "relatorio.txt", "conteudo": "linha 1\n"})
# {"caminho": "/mnt/nas/documentos/relatorio.txt", "bytes": 8}
```

## Estado

`status: pending_approval`, `approved_commit: null`. É o estado honesto de uma
capability que nenhum Gate 2 aprovou, e é o que impede o registry de oferecê-la a
`resolve()`: ele só carrega `active` (`plan.md` §6). Um exemplo que se declarasse
`active` seria escolhido para atender "listar arquivos do NAS" numa máquina onde
`/mnt/nas/documentos` não existe.

## Credenciais e ambiente

Nenhuma credencial. A pasta do NAS precisa estar **montada** no caminho concedido
em `permissions.filesystem` antes da primeira execução — a capability não monta
nada, e `nas_listar` numa raiz inexistente devolve lista vazia em vez de levantar,
porque "a pasta não está montada" é estado do ambiente, não falha da tool.

`nas_status` é a única tool que usa rede, e usa um `socket.create_connection` para
`192.168.1.50:445`. No teste a sonda é injetada; a suíte não toca a rede.

## O que copiar daqui

1. `permissions.filesystem` do manifest é a **raiz de trabalho**, lida em
   `NasArquivos.raiz`. A capability não escolhe onde escreve.
2. Toda tool tem modelo Pydantic de entrada e de saída. O JSON Schema do manifest
   sai deles — não se digita `input_schema` à mão.
3. Dependência externa (a rede) entra por injeção no construtor e é declarada em
   `requires=ToolRequirements(...)`. Sem a concessão no manifest, o SDK nega a
   chamada antes de o handler rodar.
4. `manifest.yaml` e `permissions.yaml` são **gerados** por `manifest_de()` +
   `escrever_arquivos()`. Editar um dos dois à mão faz o harness reclamar.
5. `tests/test_exemplo_nas.py` é o contrato de teste: monte a concessão de teste,
   liste os `CasoDeTool` e mande `CapabilityHarness.rodar()`.
