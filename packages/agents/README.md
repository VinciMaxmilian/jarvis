# packages/agents

A camada cognitiva: quem decide, quem planeja e quem age. Nada aqui executa
diretamente — a execução mora atrás de `ToolExecutor`/`Kernel`
(`packages/shared/ports.py`), e `tests/test_architecture.py` reprova
mecanicamente um `chief.py` que importe `registry`, `kernel` ou `runtime`.

## Perfis de agente

Um perfil é um PAPEL. Cada um traz quatro coisas próprias, e as quatro são
independentes de propósito:

| papel | prompt | tools | temperatura | modelo (`task_profile`) |
|------------|-----------------|------------------------|------|--------|
| `chief` | `chief.md` | catálogo inteiro | default do provider | `chief` |
| `planner` | `planner.md` | só leitura | 0.2 | `chief` |
| `researcher` | `researcher.md` | só leitura | 0.3 | `cheap` |
| `executor` | `executor.md` | leitura + ação + MCP | 0.0 | `code` |
| `reviewer` | `reviewer.md` | só leitura | 0.1 | `chief` |

O prompt vem de `prompts/*.md`, nunca de constante no código: prompt é conteúdo,
e diff de prompt dentro de um `.py` some no meio da lógica.

`name` é o papel; `task_profile` é o tipo de trabalho que o papel dá ao modelo e é
resolvido por `packages/llm/profiles.py`, com toda a cadeia de degradação. Os dois
eixos são separados porque coincidem sem serem a mesma coisa: planner e reviewer
compartilham modelo e política de tools, e ainda assim são papéis diferentes.

`provider=None` significa "use o provider default do sistema". Preenchido, PRENDE
o papel a um provider — é o gancho para rodar um papel local e outro remoto.

## A restrição de tools é allowlist

O catálogo é dinâmico: um servidor MCP novo aparece em runtime com um nome que
ninguém escreveu no código. Uma denylist liberaria toda tool futura por omissão
para todo papel. Por isso `allow_unlisted` é `False` por default, e o único papel
que o inverte é o `executor`, que existe para agir.

Declarar não basta. `tool_guard.py` envelopa o `ToolExecutor` na política do
papel, e `execute()` recusa ANTES de tocar no executor de baixo — filtrar o
catálogo é ergonomia (o modelo não pede o que não vê), a recusa em `execute` é a
garantia, porque modelo alucina nome de tool e histórico carrega chamadas de
outro papel.

## Arquivos

- `profiles.py` — dado puro: perfis, política de tools, carregamento de prompt.
- `tool_guard.py` — aplica a política sobre um `ToolExecutor`.
- `chief.py` — o loop de tool calling. O papel é parâmetro; sem perfil explícito
  recebe o `CHIEF_PROFILE`, que preserva o comportamento da v0 byte a byte.
- `goal_manager.py` — goal → tasks, com checkpoint por task.
- `executive.py` — loop assíncrono sobre goals ativos.
- `prompts/` — um `.md` por papel.
