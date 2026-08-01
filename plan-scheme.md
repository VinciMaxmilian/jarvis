# Mapa do Repositório e Política de Documentação

O esquema anterior (60 arquivos `.md` numerados em `AI-Operating-System/`) está **congelado**: era burocracia de documentação antes de existir código, e num projeto de dono solo isso só produz manutenção de texto morto. Nenhum daqueles arquivos foi escrito; nenhum será. Este documento define onde o código mora e quando um documento novo pode nascer.

Visão, arquitetura e roadmap ficam em `plan.md`. Stack, contratos de dados e decisões técnicas ficam em `tools.md`. Aqui há apenas: layout de diretórios, documentos permitidos, ADRs, git e o ritual de sincronização entre máquinas.

---

## Estrutura do monorepo

Estado verificado em disco. `existe` = arquivo/pasta presente e rastreado pelo git; `esqueleto` = presente mas placeholder não executável; `alvo` = ainda não criado.

```text
jarvis/
├── apps/
│   ├── api/                      esqueleto  — só Dockerfile (python:3.12-slim + uvicorn)
│   │   ├── Dockerfile            existe
│   │   ├── main.py               alvo       — FastAPI, entrypoint do v0
│   │   ├── routers/              alvo
│   │   └── alembic/versions/     alvo       — migrations, versionadas
│   ├── web/                      esqueleto  — Dockerfile atual é cópia do de Python
│   │   └── Dockerfile            existe     — precisa virar Node/Vite (React 19 + PWA)
│   └── worker/                   alvo       — consumidor do event bus (v2)
│
├── packages/
│   ├── agents/                   esqueleto  — só README.md de uma linha
│   ├── capabilities/             esqueleto  — só README.md; vira o Capability SDK
│   ├── llm/                      alvo       — abstração de provider (API forte + Qwen3 8B local)
│   ├── memory/                   alvo       — short/long term, LanceDB (v1)
│   ├── scheduler/                alvo       — APScheduler (v1)
│   └── shared/                   alvo       — modelos Pydantic de Goal, Task, Event, manifest
│
├── infrastructure/
│   ├── docker/
│   │   └── docker-compose.yml    existe     — postgres:14-alpine + redis:6-alpine, sem healthcheck
│   ├── cloudflare/               alvo       — config do Tunnel + Access (v1)
│   └── backup/                   alvo       — pg_dump + snapshot LanceDB (v1)
│
├── orchestrator/
│   ├── Dockerfile                existe
│   └── main.py                   esqueleto  — importa packages.memory, packages.goal_manager
│                                              e infrastructure.message_bus, que não existem;
│                                              não roda. Referencia NATS: obsoleto, o bus é
│                                              Redis Streams
│
├── capabilities/                 alvo       — uma pasta por capability instalada
├── docs/decisions/               alvo       — ADRs curtos, sob demanda
├── graphify/                     existe, IGNORADO — clone do fonte upstream, não é código do projeto
├── .claude/                      existe, versionado (exceto settings.local.json)
├── .gitignore                    existe
├── CLAUDE.md                     existe
├── README.md                     alvo
├── plan.md                       existe
├── tools.md                      existe
└── plan-scheme.md                existe (este)
```

Os três arquivos marcados como `esqueleto` foram gerados antes das decisões atuais e serão substituídos, não corrigidos. Nada em `packages/` importa de outro pacote hoje; a regra ao criar de verdade é que `apps/` depende de `packages/`, nunca o contrário, e `packages/shared` não importa ninguém.

---

## Documentos permitidos

Cinco arquivos fixos mais uma pasta de ADRs. Qualquer `.md` fora desta lista precisa de justificativa.

| Arquivo | Responsabilidade | Quando muda |
|---|---|---|
| `plan.md` | Visão do produto, arquitetura, roadmap por milestone e definição de "pronto" | Ao mudar escopo ou ordem das fases |
| `tools.md` | Stack, contratos de dados (Goal, Task, Event, CapabilityManifest), decisões técnicas e seus motivos | Ao trocar tecnologia ou alterar um contrato |
| `plan-scheme.md` | Mapa de diretórios, política de doc, git, sincronização, layout de capability | Ao criar/mover diretório de topo ou mudar fluxo de trabalho |
| `README.md` | Subir o sistema em 3 comandos: clonar, `cp .env.example .env`, `docker compose up`. Mais como rodar `pytest` | Ao mudar o passo a passo de setup |
| `CLAUDE.md` | Instruções operacionais do agente sobre este repo | Ao mudar convenções que o agente precisa respeitar |
| `docs/decisions/` | ADRs numerados, um por decisão que doeu | Só por adição; ADR não se edita, se supersede |

Sem `CONTRIBUTING.md`, sem `DEVELOPMENT.md`, sem `RFC_TEMPLATE.md`: não há colaboradores externos. Sem `docs/` de API escrita à mão: o FastAPI gera `/docs` a partir dos modelos Pydantic.

---

## Documentação sob demanda

Regra: **doc nasce quando a decisão dói, não antes.** Dói quando você já trocou de ideia duas vezes, quando a escolha vai custar caro para reverter, ou quando daqui a três meses você não vai lembrar por que descartou a alternativa óbvia.

Crie um ADR quando: uma tecnologia foi escolhida contra uma alternativa razoável; um contrato de dados ficou estranho por um motivo específico; uma restrição externa (GPU, custo de API, limite do Cloudflare) forçou o desenho. Não crie ADR para: nome de variável, escolha de biblioteca sem alternativa disputada, nada que o `git log` já explique.

Formato — `docs/decisions/NNNN-titulo-curto.md`, quatro seções, uma tela:

```markdown
# 0007 — Redis Streams como event bus

Status: aceito | superseded por 00NN

## Contexto
O que era verdade quando a decisão foi tomada. Restrições reais.

## Decisão
O que foi escolhido, em uma frase, na voz ativa.

## Consequência
O que passa a ser fácil, o que passa a ser difícil, e qual é o sinal
de que a decisão precisa ser revisitada.
```

Numeração sequencial, nunca reaproveitada. Um ADR errado não é apagado: cria-se um novo com `Status: aceito` e marca-se o antigo como `superseded`.

---

## Git

Branch principal: `main`. Sem develop, sem release branches, sem GitFlow.

| Namespace | Uso |
|---|---|
| `feat/<slug>` | Funcionalidade do sistema em si (API, memória, scheduler) |
| `fix/<slug>` | Correção |
| `chore/<slug>` | Infra, CI, dependências, documentação |
| `capability/<name>` | **Exclusivo** para código de capability, gerado ou escrito à mão |

Uma branch `capability/<name>` só entra em `main` depois do Gate 2 (semântica dos gates em `plan.md`). Merge com `--no-ff`, sempre: o merge commit é a fronteira da capability no histórico. Consequência prática: **`git revert` do merge commit é a desinstalação**. Não há uninstaller, não há script de limpeza — reverte-se o commit, o código some da árvore, o registry deixa de encontrar o manifest, e o histórico preserva o que existiu.

Commits: uma linha imperativa no presente, prefixo do tipo (`feat:`, `fix:`, `chore:`), sem escopo obrigatório. Corpo só quando o "porquê" não cabe no título — e se o porquê for grande, vira ADR e o commit referencia o número.

CI roda `ruff`, `pytest` e as migrations Alembic contra um Postgres efêmero. Branch com CI vermelho não faz merge, inclusive as de capability.

---

## Sincronização casa ↔ trabalho

Duas máquinas, um dono, nenhuma sincronia automática. O git é o único canal: **antes de sair de uma máquina, commite e faça push, mesmo com o trabalho pela metade.** Commit incompleto em branch de feature é aceitável; trabalho preso em uma máquina não é.

Versionado vs ignorado (conforme o `.gitignore` atual):

| Item | Estado | Motivo |
|---|---|---|
| `.env.example` | versionado (negação explícita no `.gitignore`) | Contrato de configuração; toda variável nova entra aqui no mesmo commit |
| `.env`, `*.pem`, `*.key`, `secrets/` | ignorado | Segredo vive só na máquina; cada máquina tem o seu |
| `alembic/versions/*.py` | versionado | Migration é código; há aviso explícito no `.gitignore` para não ignorar |
| `graphify-out/` | versionado, exceto `cost.json` e `cache/` | O grafo viaja junto e a outra máquina já abre com o mapa pronto |
| `/graphify/` | ignorado | Clone do fonte upstream, repo git aninhado; a instalação funcional veio do PyPI |
| `.claude/` | versionado, exceto `settings.local.json` | Skills e regras são compartilhadas; config de máquina não |
| `models/`, `*.gguf`, `lancedb/`, `pgdata/` | ignorado | Pesos e dados locais; reconstruídos por download ou backup, nunca pelo git |

Ritual de retomada na outra máquina: `git pull` → conferir se `.env.example` ganhou variáveis novas e replicar no `.env` local → `docker compose up` → `pytest`. Se o `pytest` já vem vermelho antes de você escrever qualquer linha, o problema é ambiente (segredo faltando, migration não aplicada), não código. Rodar `graphify update .` depois de mudanças estruturais para o grafo não chegar defasado do outro lado.

Dados não viajam pelo git. Postgres e LanceDB da máquina de casa são a fonte da verdade; a máquina de trabalho é ambiente de desenvolvimento com banco descartável.

---

## Layout de uma capability em disco

Uma capability instalada é uma pasta autocontida em `capabilities/`. Este é o layout no sistema de arquivos; o significado dos campos do manifest, o modelo de permissões e os gates de aprovação estão em `plan.md` e `tools.md`.

```text
capabilities/<name>/
├── manifest.yaml        identidade, versão, status, approved_commit, tools expostas via MCP
├── permissions.yaml     FS e rede declarados; lido em runtime pelo wrapper, não é documentação
├── backend/
│   ├── __init__.py
│   └── handlers.py      o que roda; executado em subprocesso próprio
├── schemas/             modelos Pydantic de entrada e saída de cada tool
├── tests/
│   └── test_<name>.py   pytest; o resultado é anexo obrigatório do Gate 2
└── docs/
    └── README.md        o que faz, exemplo de chamada, o que exige de credencial
```

Regras de disco: o nome da pasta é igual ao `name` do manifest e igual ao sufixo da branch `capability/<name>`. Nada fora da pasta é tocado por uma capability — sem editar `apps/`, sem migration própria, sem escrever em `packages/`. Uma capability sem `tests/` não passa do Gate 2. `frontend/`, `config.yaml` e `examples/` do esquema antigo saíram: só voltam quando uma capability real precisar deles.
