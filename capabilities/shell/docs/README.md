# shell — executar um programa externo, com coleira

> **Esta é a capability mais perigosa do Jarvis.** Leia a seção *Risco* antes de
> aprovar o manifest ou de acrescentar um nome à allowlist. Nada aqui é
> configuração de conveniência: cada linha do `allowlist.yaml` é uma decisão de
> segurança.

## Tools

| Tool | O que faz | Exige | Idempotente | Aprovação |
|---|---|---|---|---|
| `shell_executar` | Roda um programa da allowlist e devolve stdout, stderr e código de saída. | `process: true` | não | **sim** |
| `shell_listar_permitidos` | Devolve a allowlist em vigor. | nada | sim | não |

`shell_listar_permitidos` existe para o Chief AI perguntar antes de tentar: sem
ela, descobrir que `curl` não é permitido custa uma task falhada; com ela custa
uma chamada que não inicia processo nenhum.

```python
from capabilities.shell.backend.handlers import main

main("shell_executar", {"programa": "git", "argumentos": ["status", "--short"]})
# {"programa": "git", "exit_code": 0, "stdout": "...", "stderr": "",
#  "truncado": False, "expirou": False, "cwd": ".../data/workspace"}
```

## As quatro proteções

1. **Nunca `shell=True`, nem por acidente.** O schema separa `programa` de
   `argumentos`, e `argumentos` é uma **lista**. Não existe ponto no código onde
   uma string de comando seja montada, logo não existe onde `;`, `|`, `&&`, `>`
   ou `*` sejam interpretados. `subprocess.run` recebe o vetor pronto, com
   `shell=False` escrito explicitamente em `executor_subprocess` — explícito para
   que um leitor possa confirmar a ausência de `shell=True` sem ler o resto.
2. **Allowlist.** `programa` tem de ser um **nome simples** — sem barra, sem `..`,
   sem letra de unidade — e estar na lista. Fora dela, `PermissaoNaoDeclarada
   ("process", programa)`: o argumento estava bem formado, o que faltou foi
   autorização, e `kind`/`target` é o que vai para o log da task. Aceitar caminho
   faria a allowlist virar decoração, porque bastaria gravar um arquivo com nome
   permitido em qualquer lugar.
3. **Timeout com teto.** Default 30 s, máximo 300 s, fixados no schema. Processo
   que estoura é morto e volta com `expirou: true` — "o comando travou" é
   resposta, não exceção. Trabalho longo é caso de supervisor e job agendado do
   kernel, não de tool síncrona.
4. **`cwd` dentro da concessão.** O diretório de trabalho é conferido contra
   `permissions.filesystem` com `concedido()`, a mesma função do harness. Vazio
   usa a primeira raiz concedida.

Além disso: `stdin` vai para `DEVNULL` (processo não pendura esperando entrada) e
cada fluxo é cortado em 64 KiB com `truncado: true`.

## `exit_code != 0` não é falha da tool

O comando rodou e disse que falhou; essa é a resposta que quem perguntou queria.
Falha da tool é o comando que **não pôde ser executado**: fora da allowlist,
ausente do `PATH`, `cwd` fora do escopo. A distinção importa porque o Chief AI
trata `Task` falhada e `Task` bem-sucedida com saída ruim de formas diferentes.

## Risco

A allowlist restringe **qual** programa roda, não **o que ele faz**. Isto não é
uma sandbox, e tratá-la como uma é o erro que este parágrafo existe para evitar:

- `python` na lista é **execução de código arbitrário**. Ele está na lista de
  fábrica porque sem ele a capability não serve para nada dentro deste
  repositório — e é exatamente por isso que a lista de fábrica não é segura por
  si.
- `git` na lista é mais do que parece: `git config core.pager`, `git -c
  core.sshCommand=…`, hooks do repositório. Vários programas comuns têm uma porta
  para "rode este outro programa" escondida numa opção.
- O processo **herda o ambiente** do kernel: variáveis, tokens em `env`,
  credenciais em disco alcançáveis pelo usuário que roda o Jarvis.
- O guarda de permissões do kernel vale para **este** processo, não para os
  filhos que ele inicia. Um programa lançado daqui escreve onde o usuário do
  sistema puder escrever, não onde `permissions.filesystem` disser.

Consequências práticas para quem aprova:

- Conceder `process: true` a esta capability é conceder, na prática, o que o
  usuário do sistema pode fazer. Rode o Jarvis com um usuário de privilégio
  baixo.
- Acrescentar um nome à allowlist é uma decisão de Gate 1, com a mesma seriedade
  de conceder uma pasta nova.
- `requires_approval: true` em `shell_executar` não é enfeite: é a última chance
  de um humano ver o vetor de comando antes de ele existir.

## A allowlist

`allowlist.yaml`, ao lado do `manifest.yaml`. É o arquivo do **dono** — mudar o
que a capability alcança sem tocar em Python.

```yaml
permitidos:
  - git
  - python
```

Lista solta (`- git`) também é aceita. Regras de carga:

- **Arquivo ausente** → vale `PERMITIDOS_PADRAO` do módulo. Não é erro: a
  capability funciona com a lista de fábrica.
- **Arquivo presente e torto** → **erro**, e a capability não sobe. Cair na lista
  padrão em silêncio seria uma restrição que o dono acha que aplicou.
- **Arquivo vazio** → allowlist vazia, e nada executa. É um estado legítimo:
  desligar a execução sem desinstalar a capability.

A comparação ignora caixa, porque `GIT` e `git` são o mesmo programa no Windows e
uma allowlist que discordasse disso seria contornável por maiúscula.

## Credenciais e ambiente

Nenhuma credencial própria. `permissions.network: []` — a capability não fala
rede (o programa que ela lança pode falar, ver *Risco*).

O manifest gerado concede `data/workspace` deste repositório como raiz de
trabalho e `process: true`. **Os dois campos são o que o dono revisa no Gate 1.**

## Estado

`status: pending_approval`, `approved_commit: null`. Nenhum Gate 2 aprovou esta
capability; o registry só carrega `active` (`plan.md` §6).

## Manutenção

`manifest.yaml` e `permissions.yaml` são **gerados** de `manifest_de()` +
`escrever_arquivos()` a partir da classe. `allowlist.yaml` é escrito à mão, de
propósito: é o único arquivo aqui cuja autoria é do dono, não do código.
