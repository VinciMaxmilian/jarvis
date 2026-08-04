# filesystem — arquivos e pastas dentro do que o dono concedeu

Primeira capability de uso geral do Jarvis. Faz o que qualquer sistema faz com
arquivos — ler, escrever, listar, mover, copiar, apagar, criar pasta — com uma
diferença: **nada acontece fora de `permissions.filesystem`**.

## Tools

| Tool | O que faz | Idempotente | Aprovação |
|---|---|---|---|
| `fs_ler` | Lê um arquivo de texto. Recusa acima de `max_bytes` em vez de truncar. | sim | não |
| `fs_escrever` | Grava texto, substituindo ou acrescentando ao fim. | não | não |
| `fs_listar` | Lista uma pasta, com ou sem recursão, com teto de entradas. | sim | não |
| `fs_mover` | Move ou renomeia arquivo ou pasta. | não | não |
| `fs_copiar` | Copia arquivo ou árvore inteira. | não | não |
| `fs_apagar` | Apaga arquivo ou pasta. | não | **sim** |
| `fs_criar_pasta` | Cria pasta com os níveis intermediários. | sim | não |

Chamada, como o kernel a faz:

```python
from capabilities.filesystem.backend.handlers import main

main("fs_escrever", {"caminho": "notas/hoje.md", "conteudo": "linha 1\n"})
# {"caminho": ".../data/workspace/notas/hoje.md", "bytes": 8, "criado": True}
```

## Fronteira: três camadas, três papéis

1. **O modelo de entrada** (`schemas/models.py`) recusa `..`, `~` e caminho vazio.
   É onde erro de digitação morre — com o nome do campo, porque é isso que
   `EntradaInvalida` carrega para quem chamou.
2. **`_resolver()`** normaliza o caminho pedido e o confere contra
   `permissions.filesystem` usando `concedido()`, a mesma função do harness.
   Fora do escopo é `PermissaoNaoDeclarada`, com o caminho em `target`.
3. **O guarda do kernel** (`packages/kernel/permissions`) intercepta o `open()`
   dentro do subprocesso. É a rede de baixo e continua valendo: a camada 2 pode
   ser burlada por um symlink criado entre a conferência e a abertura, a 3 não.

## Caminho relativo e caminho absoluto

O argumento pode ser qualquer um dos dois:

- **relativo** → resolvido contra a **primeira** raiz de `permissions.filesystem`,
  que é a raiz de trabalho;
- **absoluto** → usado como veio, e conferido igual.

As duas formas passam pela mesma conferência. O absoluto existe para que conceder
duas pastas conceda de fato duas pastas — sem ele, a segunda raiz do manifest
seria inalcançável e a concessão seria decoração.

## Nenhum `OSError` sobe cru

`FileNotFoundError`, `NotADirectoryError`, `PermissionError` do sistema e afins
viram `EntradaInvalida` nomeando o campo (`caminho`, `origem`, `destino`,
`max_bytes`, `recursivo`). A escolha merece justificativa: `EntradaInvalida` é o
erro do SDK para "o argumento não serve", e "o arquivo que você pediu não existe"
é exatamente isso do ponto de vista de quem chamou. A alternativa — devolver uma
saída com `ok: false` — obrigaria todo chamador a conferir um campo que ninguém
confere.

Duas exceções deliberadas à regra "faltou, é erro":

- `fs_listar` numa pasta inexistente devolve lista vazia. Disco externo não
  montado é estado do ambiente, não falha da tool (mesma decisão de
  `exemplo_nas.nas_listar`).
- `fs_apagar` com `ausente_ok: true` aceita o caminho que já não existe, porque
  "garanta que isto não está aqui" é um pedido legítimo e diferente de "apague
  isto".

## Riscos e tetos

- **`fs_apagar` é o único efeito sem desfazer.** Por isso `requires_approval:
  true` no catálogo, e por isso apagar pasta com conteúdo exige `recursivo`
  explícito. Gravar por cima ao menos deixa um arquivo no lugar; apagar não deixa
  nada.
- **`fs_ler` tem teto de 1 MiB** (`MAX_LEITURA`). Acima disso a leitura é
  **recusada**, não truncada: pedaço de arquivo devolvido como se fosse o arquivo
  é a forma mais barata de fazer o Chief AI raciocinar sobre dado que não existe.
- **`fs_listar` tem teto de 500 entradas** (`MAX_ENTRADAS`) e marca `truncado`
  quando bate no teto, para o chamador saber que não viu tudo.
- **Símbolos e junções não são seguidos de propósito** na conferência: o que se
  normaliza é o caminho *pedido*. Seguir link é decisão do kernel, que vê a
  chamada de verdade.

## Credenciais e ambiente

Nenhuma credencial. Nenhuma rede (`permissions.network: []`). Nenhum subprocesso
(`permissions.process: false`).

O que o ambiente precisa ter é a pasta concedida. O manifest gerado concede
`data/workspace` deste repositório — **é o campo que o dono revisa no Gate 1**,
trocando pelo que ele realmente quer expor. Conceder a raiz do disco aqui anula
todo o resto do arquivo.

## Estado

`status: pending_approval`, `approved_commit: null`. É o estado honesto de uma
capability que nenhum Gate 2 aprovou; o registry só carrega `active`
(`plan.md` §6).

## Manutenção

`manifest.yaml` e `permissions.yaml` são **gerados** de `manifest_de()` +
`escrever_arquivos()` a partir da classe. Mexer numa tool e não regerar faz
`CapabilityHarness` acusar divergência de catálogo — que é o ponto.
