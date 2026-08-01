# Runbook da infraestrutura

O que é infraestrutura roda em container: Postgres, Redis, as migrations, a API, o
orchestrator e o PWA. O que é **inferência** roda fora: não existe mais serviço de
LLM no Compose. O critério de aceite da v0 é `docker compose up` subir o sistema sem
intervenção manual — este arquivo é o que mantém isso verdadeiro.

Todos os comandos rodam **a partir da raiz do repositório**.

Arquivos:

| Arquivo | O que é |
|---|---|
| `infrastructure/docker/docker-compose.yml` | a stack. Único arquivo de compose — não há mais override de GPU. |
| `apps/api/Dockerfile` | imagem da `api` **e** da `migrate` (mesmo Dockerfile, comandos diferentes). |
| `orchestrator/Dockerfile` | imagem do `orchestrator`. |
| `apps/web/Dockerfile` | imagem do `web` (estágio `dev`; o estágio de produção está documentado lá dentro, não usado na v0). |
| `infrastructure/cloudflared/ingress.expected.yml` | **não é lido por nada.** É a especificação versionada das rotas que o dashboard do Cloudflare tem de conter — ver §8. |

As três imagens têm **contexto de build na raiz do monorepo** (`context: ../..`), e o
único `.dockerignore` que vale para todas é o da raiz.

---

## 1. Pré-requisito único: o `.env`

```powershell
cp .env.example .env
```

Depois **edite** o `.env`. O que é obrigatório de verdade, lido de
`packages/shared/settings.py` (só estes dois campos são `Field(...)` sem default):

| Variável | Quem exige | O que acontece se faltar |
|---|---|---|
| `DATABASE_URL` | `Settings` | app não sobe; ainda valida que o DSN começa com `postgresql+asyncpg://` |
| `TAVILY_API_KEY` | `Settings` | app não sobe |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | o **compose**, não a app | Postgres nasce com usuário/senha vazios e a autenticação falha depois |

Repare que `ANTHROPIC_API_KEY` **não** é mais obrigatória: `Settings` dá o default
`sk-ant-dummy`. Ela só importa se o provider em uso for `anthropic` — aí o dummy
falha na primeira geração, não no boot. (O comentário `# obrigatório` ainda presente
no `.env.example` está desatualizado em relação a `settings.py`.)

O `.env` nunca entra em imagem (está no `.dockerignore`, junto com `.env.*`). Ele
chega no container só por `env_file`/`environment`. Segredo em imagem vaza para quem
der `docker save`.

O `env_file` do compose usa `required: false`. Isso é para o Compose não morrer na
leitura numa clonagem nova (permite `config` e `up postgres redis` sem `.env`). O
fail-fast de configuração continua onde ele mora de verdade: em `Settings`.

---

## 2. Subir tudo

```powershell
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env up -d
```

O `--env-file .env` **não é opcional**: sem ele o Compose não enxerga o `.env` da
raiz para resolver os `${POSTGRES_USER}` e afins do próprio arquivo de compose, e
sobe um Postgres com usuário vazio. Se aparecer
`variable is not set. Defaulting to a blank string`, foi esse flag que ficou de fora.

Ordem de boot, toda ela declarada em `depends_on`:

1. `postgres` e `redis` — sobem em paralelo, cada um com healthcheck (`pg_isready`,
   `redis-cli ping`);
2. `migrate` — só quando os dois estão `service_healthy`. Roda `alembic upgrade head`
   e **morre** (`restart: "no"`);
3. `api` e `orchestrator` — só quando `migrate` termina com
   `service_completed_successfully`. Se a migration falhar, nenhum dos dois sobe;
4. `web` — só quando `api` está `service_healthy` (não `service_started`: a imagem da
   API tem `HEALTHCHECK` de verdade, um `GET /health`). Sem isso o PWA subiria e faria
   proxy para uma porta que ainda não escuta, e o primeiro carregamento falharia no
   boot frio.

Não há profiles. Tudo acima sobe no `up` default.

A API fica em <http://127.0.0.1:8000> (health em <http://127.0.0.1:8000/health>) e o
PWA em <http://127.0.0.1:5173>.

Acompanhar:

```powershell
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env ps
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env logs -f api
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env logs migrate
```

> Todo subcomando (`ps`, `logs`, `down`) quer o mesmo `--env-file .env`. Sem ele o
> comando funciona, mas cospe warnings de variável não resolvida.

`migrate` aparece no `ps` como `Exited (0)`. Isso é o estado correto dele, não falha.

---

## 3. Migrations (Alembic)

**Migrations são automáticas.** O serviço `migrate` existe exatamente para isso: um
`up` numa base nova aplica o schema antes de qualquer processo Python atender
requisição.

Por que serviço separado e não `ENTRYPOINT` da `api`: são dois processos Python
(`api` e `orchestrator`) subindo juntos. Migrar no entrypoint faria os dois correrem
`alembic upgrade` ao mesmo tempo na mesma base. Um serviço one-shot dá exatamente uma
execução, e a falha dele barra os dois em vez de deixar um subir contra schema meio
aplicado.

Ele reusa a imagem da `api` (mesmo `context` e mesmo `dockerfile`), então não há build
extra nem camada nova — muda só o `command`. O `DATABASE_URL` que ele recebe aponta
para o host `postgres`; o Alembic usa o DSN síncrono derivado dele
(`Settings.sync_database_url`, que troca `+asyncpg` por `+psycopg`).

### Cuidado: `migrate` não tem bind mount do repo

`api` e `orchestrator` montam `../..:/app`. **`migrate` não monta nada** — ele roda o
código que foi copiado para a imagem (`COPY apps/api ./apps/api`, que traz
`apps/api/alembic/versions/`).

Consequência prática: **uma migration nova criada no host não é aplicada até a imagem
ser reconstruída.**

```powershell
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env up -d --build
```

### Caminhos manuais (troubleshooting e autogenerate)

O `exec api alembic upgrade head` deixou de ser passo do runbook e virou ferramenta de
diagnóstico. O que ainda é manual de verdade é gerar migration:

```powershell
# gerar migration nova a partir dos models (roda na api, que TEM o bind mount)
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env exec api alembic revision --autogenerate -m "descricao"

# ver em que revisão a base está
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env exec api alembic current

# reaplicar à mão, se você quer ver o erro sem rebootar a stack
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env exec api alembic upgrade head

# rodar o one-shot de novo, isolado
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env run --rm migrate
```

O `revision --autogenerate` grava em `apps/api/alembic/versions/`, que é bind mount do
repo na `api` — o arquivo aparece no host e entra no commit normalmente. Depois disso,
rebuild (ver acima) para o `migrate` enxergá-lo.

Do host (fora do container) o Alembic também funciona, mas aí vale o `DATABASE_URL` do
`.env`, que aponta para `127.0.0.1:5433`.

---

## 4. Inferência: fora do Docker, de propósito

Não existe container de LLM nesta stack. O serviço `ollama`, o `ollama-pull`, o volume
`ollamamodels` e o override `docker-compose.gpu.yml` foram **removidos**.

O motivo é econômico, não ideológico: manter um modelo de vários GB dentro de volume
Docker, com passthrough de GPU dependendo de Docker Desktop no backend WSL2 mais o
NVIDIA Container Toolkit, custa muito mais do que apontar uma URL para um runtime que
já roda no host. Com a inferência fora, o `up` não tem mais nenhum passo que baixe
gigabytes nem nenhuma dependência de driver.

### Providers e ordem de preferência

`apps/api/deps.py` declara o mapa `PROVIDER_FACTORIES`, e a **ordem** das entradas é a
preferência de fallback:

```
lmstudio → gemini → anthropic → openai → ollama
```

(`local` é apelido histórico de `openai` — mesma classe, outra `base_url` — e fica ao
lado dele no mapa.)

**Nada consome essa ordem para failover automático hoje.** Ela existe para que a UI
ofereça os providers na ordem certa e para que o failover, quando entrar, não precise
inventar prioridade. Se o provider selecionado cair, o request cai junto.

Quem escolhe em runtime é a linha de `system_settings` no banco; `CHIEF_PROVIDER` do
`.env` é só o default de boot para quando não há linha persistida.

> Divergência a saber: o `.env.example` traz `CHIEF_PROVIDER=lmstudio`, mas o default
> embutido em `packages/shared/settings.py` (e em `SystemSettings.provider`, em
> `packages/shared/contracts.py`) ainda é `gemini`. Ou seja: com `.env` copiado do
> exemplo o provider é `lmstudio`; sem a variável no ambiente, é `gemini`.

### LM Studio — o caminho principal

Servidor OpenAI-compatible rodando na LAN, fora do Docker. Configurado por três
variáveis:

| Variável | Valor nesta máquina | Nota |
|---|---|---|
| `LMSTUDIO_BASE_URL` | `http://192.168.11.189:1234/v1` | verificado contra `GET /v1/models` |
| `LMSTUDIO_MODEL` | `google/gemma-4-e2b` | verificado contra `GET /v1/models` |
| `LMSTUDIO_API_KEY` | `lm-studio` | o LM Studio ignora; o SDK da OpenAI exige algum valor para construir o cliente |

O compose **não** sobrescreve `LMSTUDIO_BASE_URL`: como é IP de LAN, o endereço é o
mesmo visto do host e de dentro do container. Só precisa de tradução o que aponta para
`127.0.0.1`.

Conferir se o servidor responde e qual o nome exato do modelo:

```powershell
curl http://192.168.11.189:1234/v1/models
```

O nome do modelo tem que bater **exatamente** com o que aparece nessa resposta.

`lmstudio` tem entrada própria em vez de reaproveitar `OPENAI_BASE_URL` porque as duas
coisas coexistem: `openai` pode apontar para a OpenAI de verdade enquanto `lmstudio`
aponta para a máquina da LAN. Reusar um campo obrigaria a reescrever o `.env` a cada
troca de provider.

### Ollama — último recurso, no host

O adapter (`packages/llm/ollama_provider.py`, ligado por `_build_ollama` em
`deps.py`) continua no repositório e selecionável em runtime com
`CHIEF_PROVIDER=ollama`. O que saiu foi o container. Ele usa a API nativa do Ollama
(`/api/chat`), não a camada OpenAI-compatible — por isso é entrada separada de
`local`.

Para usá-lo, instale o Ollama nativo no Windows (o instalador oficial em
<https://ollama.com/download>), e então:

```powershell
ollama pull adelnazmy2002/Qwen3-VL-8B-Instruct
ollama list
curl http://127.0.0.1:11434/api/tags
```

`OLLAMA_MODEL` no `.env` tem o default embutido
`adelnazmy2002/Qwen3-VL-8B-Instruct` (VL: visão e texto).

**Endereço, que é onde isso costuma quebrar.** São dois pontos de vista:

| De onde | URL |
|---|---|
| host (`curl`, testes fora do container) | `http://127.0.0.1:11434` |
| de dentro de `api` / `orchestrator` | `http://host.docker.internal:11434` |

O compose passa `OLLAMA_URL: ${OLLAMA_URL:-http://host.docker.internal:11434}` para
`api` e `orchestrator`, e os dois mantêm
`extra_hosts: - "host.docker.internal:host-gateway"`. Dentro do container,
`127.0.0.1` é o próprio container — daí a tradução. O default de `Settings` é
`http://127.0.0.1:11434` (escrito para uso a partir do host); é o compose que
sobrescreve para o valor do container.

> **Não verificado nesta máquina:** o Ollama no Windows escuta por default só em
> `127.0.0.1`, e `host.docker.internal:host-gateway` chega pelo IP do gateway da
> bridge, não pelo loopback do host. Se o container der connection refused mesmo com
> o `curl` do host funcionando, a causa provável é essa — o ajuste é fazer o Ollama
> escutar em todas as interfaces (`OLLAMA_HOST=0.0.0.0` no ambiente do serviço do
> Ollama, no host) ou apontar `OLLAMA_URL` para o IP de LAN da máquina, como já é
> feito com o LM Studio. Teste antes de assumir qualquer dos dois.

**GPU agora é problema do host.** Sem container de inferência, não há mais
passthrough, não há mais `--gpus`, não há mais NVIDIA Container Toolkit no caminho
crítico: quem usa a placa é o processo nativo (LM Studio ou Ollama), com o driver
NVIDIA normal do Windows. O erro
`could not select device driver "nvidia" with capabilities: [[gpu]]` deixou de existir
nesta stack.

Fica o trade-off de hardware, que não mudou: um 8B quantizado não cabe inteiro nos
4 GB da 1050 Ti. O runtime põe na GPU as camadas que couberem e transborda o resto
para a RAM, executada por uma CPU pré-AVX2. O ganho é real mas parcial. A diferença é
que agora essa decisão (quantas camadas, qual quantização) é tomada na UI do LM Studio
ou nas options do Ollama, não num arquivo de compose.

`KOBOLD_URL` segue no `.env` com o mesmo racional — runtime local fora do Compose —
mas sem provider próprio no mapa de `deps.py`: KoboldCpp entraria como `local`, via
`OPENAI_BASE_URL`.

---

## 5. Portas expostas

Todas em `127.0.0.1`, nunca `0.0.0.0` — convenção **D5**.

| Serviço | Host | Container |
|---|---|---|
| `postgres` | `127.0.0.1:5433` | 5432 |
| `redis` | `127.0.0.1:6379` | 6379 |
| `api` | `127.0.0.1:8000` | 8000 |
| `web` | `127.0.0.1:5173` | 5173 |

`migrate` e `orchestrator` não publicam porta — não servem tráfego. O LM Studio (1234)
e um eventual Ollama (11434) não estão nesta tabela porque não são desta stack: quem
publica a porta deles é o host.

**Por que só loopback:** não existe porta aberta no roteador (plan.md §2 e §14). O
acesso remoto é Cloudflare Tunnel + Access (§8), e o conector abre a conexão *de
dentro* para fora — não precisa de porta publicada na LAN. Publicar em `0.0.0.0`
exporia Postgres para qualquer dispositivo do Wi-Fi, incluindo rede de trabalho.
`5433` no host, e não `5432`, para não colidir com um Postgres instalado nativo.

> **Estas duas linhas são as origens do túnel.** O conector roda como serviço do
> Windows **no host**, fora do Docker (§8.1): para ele, `api` e `web` não existem como
> nomes — o que existe é `127.0.0.1:8000` e `127.0.0.1:5173`, exatamente o que está na
> tabela acima. Mudar o lado esquerdo de qualquer um desses dois mapeamentos quebra a
> publicação, e o sintoma é 502 na borda, não erro local.

Dentro dos containers os processos escutam em `0.0.0.0` (`API_HOST: 0.0.0.0` no
compose, `--host 0.0.0.0` no Vite) — obrigatório, senão a porta publicada não alcança
o processo. O confinamento é feito pelo `127.0.0.1:` do lado esquerdo do mapeamento.

### O PWA no container

O `web` está no caminho default, sem profile. A pendência que antes o mantinha atrás de
um profile foi resolvida: `apps/web/vite.config.ts` lê
`process.env.VITE_PROXY_TARGET`, com default `http://127.0.0.1:8000`, e o compose
injeta `VITE_PROXY_TARGET=http://api:8000` no serviço.

Os dois modos, portanto, funcionam:

| Onde roda o dev server | Target do proxy | Vem de |
|---|---|---|
| container `web` | `http://api:8000` | `environment` do compose |
| `npm run dev` no host | `http://127.0.0.1:8000` | default do `vite.config.ts` |

Isso importa porque o front usa caminho relativo (`fetch('/api/...')`) e **depende** do
proxy; sem target correto o resultado é connection refused, não erro de CORS.

É `process.env` e não `import.meta.env` porque o arquivo roda no Node (config do Vite),
antes de existir bundle — o prefixo `VITE_` só vale para o que é exposto ao browser, e
esse valor nunca chega ao cliente.

O serviço monta `../../apps/web:/app/apps/web` para ter HMR, e por cima disso um volume
**anônimo** em `/app/apps/web/node_modules`. Esse segundo volume não é detalhe: sem ele
um host sem `node_modules` apagaria o da imagem, e um host **com** `node_modules`
injetaria binário nativo de Windows num container Linux (esbuild e rollup são por
plataforma).

---

## 6. Derrubar

```powershell
# para os containers, PRESERVA os volumes (dados intactos)
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env stop

# remove containers e rede, PRESERVA os volumes — este é o "desligar" normal
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env down
```

`down` sem `-v` **não** apaga volume nomeado: `jarvis_pgdata` e `jarvis_redisdata`
continuam lá. São os dois únicos volumes nomeados que restaram — o `ollamamodels`
morreu junto com o container de inferência, e é por isso que `down -v` hoje é bem menos
caro do que era: não force download de modelo nenhum.

Apagar de propósito, com consciência do que morre:

```powershell
# APAGA TUDO: banco e Redis.
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env down -v
```

Isso destrói a memória do sistema (goals, tasks, histórico). Não há backup automatizado
antes da v1 (plan.md §2) — dump antes:

```powershell
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env exec postgres pg_dump -U jarvis jarvis > backup.sql
```

Para apagar só o banco:

```powershell
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env down
docker volume rm jarvis_pgdata
```

No `up` seguinte o `migrate` recria o schema sozinho. Os dados, não.

---

## 7. Quando algo não sobe

| Sintoma | Causa provável |
|---|---|
| `variable is not set. Defaulting to a blank string` | faltou `--env-file .env` |
| API morre no boot com erro de campo obrigatório | `.env` não existe ou está sem `DATABASE_URL`/`TAVILY_API_KEY` |
| `DATABASE_URL precisa usar o driver async` | o DSN não começa com `postgresql+asyncpg://` — validator em `Settings` |
| `api` e `orchestrator` nunca saem de `Created` | o `migrate` falhou. Veja `logs migrate`: eles esperam `service_completed_successfully` |
| migration nova não foi aplicada | `migrate` não tem bind mount; rode `up -d --build` |
| `password authentication failed for user "jarvis"` | o volume `jarvis_pgdata` já foi inicializado com OUTRA senha. Ver abaixo. |
| `port is already allocated` | Postgres ou Redis nativo já ocupa a porta no host — pare o serviço nativo |
| erro de conexão ao gerar resposta, com o resto de pé | provider apontando para runtime que não está no ar. Teste a URL do provider a partir do **host** e de dentro do container (`exec api python -c "..."`) — ver §4 |
| `Provider de LLM desconhecido: ...` | a linha de `system_settings` tem um provider morto (a coluna é String livre). Válidos: os do mapa em `deps.py` |
| `api` reinicia em loop com `ModuleNotFoundError: No module named 'jwt'` | a imagem da `api` é anterior ao `PyJWT[crypto]` do `pyproject.toml`. O bind mount traz o **código** novo, nunca a **dependência** nova. `build api` e suba de novo (medido em 2026-07-31: era exatamente isto) |
| `--reload` não recarrega ao salvar arquivo | bind mount do Windows não emite inotify; `WATCHFILES_FORCE_POLLING=true` já está no compose, confirme que o container foi recriado |
| PWA carrega mas todo `/api` falha | proxy do Vite sem target certo; confirme `VITE_PROXY_TARGET` no serviço `web` |
| build lento/enorme | `.dockerignore` da raiz caiu; ele é o que mantém o contexto enxuto para as três imagens |

Validar a sintaxe e ver os valores já resolvidos, sem subir nada:

```powershell
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env config
```

### Senha do Postgres depois do primeiro boot

`POSTGRES_PASSWORD` é lido pela imagem do Postgres **só quando o data dir está
vazio**. Se o volume `jarvis_pgdata` já existe, mudar a senha no `.env` não muda nada
no banco — a app passa a falhar autenticação com a senha nova.

Duas saídas:

```powershell
# a) alinhar o banco à senha nova (preserva os dados)
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env exec postgres psql -U jarvis -c "ALTER USER jarvis WITH PASSWORD 'senha-nova';"

# b) recriar do zero (APAGA o banco; use só se não houver nada a perder)
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env down
docker volume rm jarvis_pgdata
```

> Na validação original desta infra o volume `jarvis_pgdata` foi criado com a senha
> **placeholder** do `.env.example` (`troque-esta-senha`), porque o `.env` real não
> existia ainda. Se o volume desta máquina ainda for aquele, rode a opção (b) antes do
> primeiro uso sério, para o banco nascer com a sua senha de verdade. Com o `migrate`
> automático, recriar custa um `up` — o schema volta sozinho.

---

## 8. Publicação: Cloudflare Tunnel + Zero Trust Access

Objetivo da v1.5: o sistema acessível de fora da rede, em
`https://ia.atmosintelli.com.br`, **sem nenhuma porta aberta no roteador**. O
conector abre uma conexão de saída para a borda da Cloudflare e o tráfego de entrada
desce por ela; nada precisa ser publicado na LAN nem redirecionado no roteador. Isso
não mudou e é o critério de aceite.

O que mudou foi *onde o conector roda* e *onde as regras de roteamento moram*.

### 8.1 A decisão: conector como serviço do Windows, no host

**O caminho suportado é um só: o túnel `JARVIS_TUNNEL`, criado no dashboard
(remotely-managed), rodando como serviço do Windows no host.** O serviço
`cloudflared` do Compose foi **removido** e o `infrastructure/cloudflared/config.yml`
foi **aposentado** (sucedido por `ingress.expected.yml`, que não é configuração — é
contrato; ver §8.3).

Não é preferência estética. São três incompatibilidades concretas:

1. **Um túnel por token ignora o `config.yml` local.** O `service install <token>`
   registra o serviço com os argumentos `tunnel run --token-file <caminho>`
   (verificado no fonte: `cmd/cloudflared/windows_service.go` →
   `installWindowsService` → `buildArgsForTokenFile`, e
   `cmd/cloudflared/common_service.go`). Rodando assim, a configuração que vale chega
   da borda em runtime e **substitui** o ingress carregado localmente
   (`orchestration.Orchestrator.UpdateConfig`). Um `config.yml` versionado com regras
   de ingress, nesse modo, não é configuração: é um arquivo que descreve um
   roteamento que não é o que roda. Pior do que não ter documentação.
2. **As origens são outras.** O conector está no host, fora do Docker. `api:8000` e
   `web:5173` são nomes do DNS interno do Compose e **não resolvem do host**. O que
   existe do host são as portas publicadas em loopback (§5): `127.0.0.1:8000` e
   `127.0.0.1:5173`. O `config.yml` antigo apontava para `http://api:8000` — correto
   para um conector dentro da rede do Compose, 502 permanente para um conector no host.
3. **Dois conectores no mesmo túnel é armadilha, não redundância.** Se o container e
   o serviço do Windows subissem juntos, virariam duas réplicas do mesmo túnel. Ver
   §8.6.

E um ganho real que o caminho Docker não tem: o serviço do Windows sobe com a
máquina, sobrevive a reboot e não depende de o Docker Desktop ter iniciado. Para um
túnel — a coisa que decide se o sistema está alcançável — essa é a diferença entre
"está no ar" e "está no ar quando eu lembro de abrir o Docker".

#### O que se perdeu, dito sem maquiagem

O agente anterior argumentou contra o túnel por token, e o argumento **continua
válido**: com as regras no dashboard, a tabela de roteamento vira uma lista arrastável
que nenhum `git diff` revisa. Trocar a ordem de dois itens manda `/api/chat/ws` para o
Vite, que responde `200` com o `index.html` em vez de abrir o WebSocket — falha
silenciosa, cara de achar (§8.3). Esse custo é real e o dono o assumiu conscientemente,
em troca da robustez operacional do serviço no host.

A mitigação, que é o melhor disponível e não é equivalente: as regras pretendidas
estão versionadas em `infrastructure/cloudflared/ingress.expected.yml` como **fonte de
verdade que o dashboard tem de espelhar**. Isso não impede a divergência; torna a
divergência *detectável*, por diff contra o estado remoto (§8.7). A revisão deixou de
ser automática (um PR) e virou deliberada (rodar a conferência).

> Para reviver o caminho Docker — o que só faz sentido com um túnel **diferente**,
> criado por `cloudflared tunnel create`, e com o serviço do Windows desinstalado:
> `git show 76a5800:infrastructure/docker/docker-compose.yml` e
> `git show 76a5800:infrastructure/cloudflared/config.yml`.

### 8.2 Instalar o conector como serviço do Windows

Baixe e instale o MSI (é o download oficial para Windows amd64, confirmado na doc de
downloads da Cloudflare):

<https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.msi>

O MSI põe os arquivos em `C:\Program Files (x86)\cloudflared`. Depois, num terminal
**como Administrador** (o `service install` fala com o Service Control Manager):

```powershell
cloudflared.exe service install <TOKEN-DO-TUNEL>
```

O token sai do dashboard: **Networking → Tunnels → JARVIS_TUNNEL → aba Overview →
Add a replica**, que revela o comando de instalação pronto por sistema operacional.

**O que esse comando faz no disco** — importante saber exatamente, porque é isso que
precisa ser limpo quando o token for rotacionado (§8.5). Verificado no fonte:

| Coisa | Onde |
|---|---|
| serviço | nome `Cloudflared`, display `Cloudflared agent`, start automático |
| **o token** | gravado em `%PROGRAMDATA%\cloudflared\token`, permissão `0600` |
| argumentos do serviço | `tunnel run --token-file %PROGRAMDATA%\cloudflared\token` |
| recuperação | reinício automático 20 s após falha |
| log | Visualizador de Eventos do Windows (registrado via `eventlog.InstallAsEventCreate`) |

O token **não** fica no `ImagePath` do registro nas versões atuais — fica no arquivo.
Confira mesmo assim antes de assumir (versões antigas passavam o token direto como
argumento do serviço, e aí ele estaria no registro em texto claro):

```powershell
sc.exe qc Cloudflared
Get-Service Cloudflared
```

Desinstalar (o `uninstall` remove o serviço, o event logger **e apaga o arquivo de
token** — verificado em `uninstallWindowsService`):

```powershell
cloudflared.exe service uninstall
```

`%PROGRAMDATA%` é `C:\ProgramData` numa instalação padrão, então o caminho do token é
`C:\ProgramData\cloudflared\token`. Ele fica fora do repositório de propósito.

> **Não verificado nesta máquina:** o MSI recente pode já registrar o serviço na
> instalação. Se o `service install` responder que o serviço já existe, rode
> `cloudflared.exe service uninstall` antes de reinstalar com o token.

### 8.3 As duas rotas no dashboard, na ordem

No dashboard: **Networking → Tunnels → JARVIS_TUNNEL → aba Routes → Add route →
Published application**. (Em partes do dashboard o mesmo lugar aparece como
*Zero Trust → Networks → Connectors → Cloudflare Tunnels → Edit → Published
application routes*; são a mesma coisa, a navegação mudou de nome recentemente.)

**Crie a rota 1 primeiro.** A ordem em que elas aparecem na lista é a ordem de
avaliação.

#### Rota 1 — API (inclui o WebSocket)

| Campo | Valor |
|---|---|
| Subdomain | `ia` |
| Domain | `atmosintelli.com.br` |
| **Path** | `^/api(/\|$)` |
| Type | `HTTP` |
| URL | `127.0.0.1:8000` |

O valor do Path, para copiar sem o escape que a tabela acima exige:

```
^/api(/|$)
```

#### Rota 2 — PWA (casa tudo o que sobrou)

| Campo | Valor |
|---|---|
| Subdomain | `ia` |
| Domain | `atmosintelli.com.br` |
| **Path** | *(vazio)* |
| Type | `HTTP` |
| URL | `127.0.0.1:5173` |
| Additional application settings → HTTP Settings → **HTTP Host Header** | `localhost:5173` |

#### Por que a ordem é o item mais frágil desta seção

O cloudflared avalia as regras de cima para baixo e para na **primeira** que casa —
verificado no fonte, não na prosa da doc: `ingress/ingress.go`, `FindMatchingRule`,
retorna assim que `rule.Matches(hostname, path)` é verdadeiro; e a validação exige que
a última regra case tudo ("The last ingress rule must match all URLs").

Consequência: **se a rota do PWA (path vazio) ficar em primeiro lugar, ela captura
`/api/...` inteiro.** O sintoma mais caro é o WebSocket. A rota do chat é
`/api/chat/ws` (`apps/api/main.py` monta o router com `prefix="/api/chat"`;
`apps/api/routers/chat.py` declara `@router.websocket("/ws")`), e o Vite responde a
qualquer path desconhecido com `200 OK` e o `index.html`. O front então tenta abrir um
WebSocket contra algo que devolveu HTML: o chat carrega, parece saudável e nunca
conecta. Nenhum log grita. É o único erro desta configuração que não produz mensagem
de erro — daí ele merecer uma seção.

Com a ordem certa, o WebSocket não pede mais nada: o `^/api(/|$)` já o cobre, e o
cloudflared faz proxy de `Upgrade` nativamente, sem chave de configuração.

#### Sobre o campo Path

O texto de ajuda do próprio dashboard resume a semântica: *"Match all paths: leave
empty / Match path prefix: `^/api`"*. Por baixo é regex Go casada com `MatchString`,
que casa em **qualquer posição** da string — verificado em `ingress/rule.go`:

```go
pathMatch := r.Path == nil || r.Path.Regexp == nil || r.Path.Regexp.MatchString(path)
```

Por isso:

- o `^` **não é decorativo**: sem ele, `/qualquer/coisa/api/x` cairia na API;
- o `(/|$)` evita que um futuro `/apiary` seja capturado por engano. Se o dashboard
  recusar os parênteses, `^/api` sozinho já resolve o caso real — mas prefira a forma
  completa.

#### Sobre o campo URL: `127.0.0.1`, não `localhost`

O Compose publica em `127.0.0.1:8000` e `127.0.0.1:5173` — IPv4 loopback, e só ele
(§5). No Windows, `localhost` costuma resolver para `::1` antes de `127.0.0.1`, e não
há nada escutando em `::1`. Na melhor hipótese o conector tenta IPv6, falha e cai para
IPv4 (latência a mais em cada conexão); na pior, falha e pronto. Escrever o IP tira a
resolução de nome do caminho. *(Raciocinado a partir do binding do Compose, não medido
nesta máquina.)*

#### Por que o HTTP Host Header na rota do PWA

O conector repassa o `Host` original (`ia.atmosintelli.com.br`) para a origem. O dev
server do Vite valida esse header contra `server.allowedHosts` — defesa contra DNS
rebinding — e responde `Blocked request. This host is not allowed.` a host
desconhecido. Sem a reescrita, **todo** request do PWA morreria aí. Reescrever para
`localhost:5173`, que o Vite sempre aceita, resolve na borda sem tocar em
`apps/web/vite.config.ts` (que pertence a outro dono).

A API não precisa disso: uvicorn/FastAPI não valida `Host`.

> Herdado da configuração anterior e **não retestado de fora da rede**. Se o PWA
> responder `Blocked request...`, é este campo que está faltando ou errado.

#### DNS

Salvar uma rota com hostname público cria o registro CNAME correspondente na zona
`atmosintelli.com.br` automaticamente. As duas rotas usam o **mesmo** hostname, então
o registro é um só. *(Comportamento documentado pela Cloudflare; não conferido na zona
desta conta.)*

### 8.4 Zero Trust Access: a aplicação, a policy, o AUD e o team domain

O túnel publica; ele não autentica. Sem uma aplicação do Access na frente,
`ia.atmosintelli.com.br` fica aberto para a internet inteira. Esta seção é obrigatória,
não opcional.

**Criar a aplicação:** dashboard → **Zero Trust → Access controls → Applications →
Create new application → Self-hosted and private → Add public hostname**, e informe o
mesmo hostname das rotas: `ia` + `atmosintelli.com.br`, com o path vazio (a aplicação
tem de cobrir o hostname inteiro — API e PWA — senão sobra caminho sem gate).

**A policy:** uma só, com esta forma exata:

```
Action: Allow
Include → Emails → <e-mail do dono>
```

Um único e-mail no `Include`. Nada de `Emails ending in` nem grupos: o sistema tem um
usuário, e a policy tem de dizer isso literalmente.

> O login em si depende de haver um método de identidade habilitado. Com nenhum IdP
> configurado, o **One-time PIN** é o caminho — o Access manda um código para o e-mail
> e valida por ali. *(Não conferido nesta conta; se a tela de login não oferecer nada,
> é isso que está desligado em Zero Trust → Settings → Authentication.)*

**Os dois valores que a origem precisa:**

| Valor | Onde achar no dashboard | Vai para |
|---|---|---|
| **Application Audience (AUD) Tag** | Zero Trust → Access controls → **Applications** → *Configure* na aplicação → **Additional settings** | `CF_ACCESS_AUD` |
| **team domain** (`<team>.cloudflareaccess.com`) | Zero Trust → **Settings** (General/Custom Pages mostram o domínio da equipe) | `CF_ACCESS_TEAM_DOMAIN` |

Os dois caminhos acima estão na doc oficial de validação de JWT do Access, que também
fixa os formatos que a origem usa: emissor `https://<team>.cloudflareaccess.com` e
JWKS em `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs`.

Nenhum dos dois é segredo — o AUD viaja dentro do próprio JWT.

**Como a origem consome isso.** `packages/shared/settings.py` já lê (nomes conferidos
no arquivo, não inventados):

| Variável | Obrigatória? | O que faz |
|---|---|---|
| `CF_ACCESS_TEAM_DOMAIN` | junto com as outras duas | aceita `meutime` ou `meutime.cloudflareaccess.com`; um validator normaliza e deriva `iss` e a URL do JWKS |
| `CF_ACCESS_AUD` | junto com as outras duas | a AUD tag da aplicação |
| `CF_ACCESS_EMAIL` | junto com as outras duas | o claim `email` do token tem de bater **exatamente** (normalizado para minúsculas) |
| `CF_ACCESS_ENFORCE` | não (`auto`) | `auto` liga a verificação quando as três acima estão preenchidas; `on` força; `off` é escape hatch |
| `CF_ACCESS_JWKS_TTL_SECONDS` | não (`3600`) | de quanto em quanto tempo o JWKS é rebuscado |

Duas armadilhas que o `Settings` transforma em erro de boot, de propósito:

- **preencher só uma ou duas das três derruba a app.** Não existe leitura benigna de
  meia configuração de autenticação — em especial `CF_ACCESS_AUD` vazio, que numa
  verificação ingênua aceitaria qualquer aplicação da conta;
- **`ENVIRONMENT=prod` sem as três preenchidas e sem `CF_ACCESS_ENFORCE=off` também
  derruba a app.** É o único cenário em que não subir é estritamente melhor do que
  subir.

Ou seja: a ordem de operações é **criar a aplicação do Access → copiar AUD e team
domain → preencher o `.env` → reiniciar `api` e `orchestrator`**. Preencher pela metade
para "ver se funciona" não é um estado que exista.

**Defesa em profundidade (opcional, recomendada).** Dá para exigir o JWT do Access no
próprio conector, antes de proxiar: na rota, *Additional application settings → Access
→ Protect with Access*, informando o Team Name e a AUD Tag. Com isso, request sem token
do Access nem chega à origem, mesmo que a verificação na API esteja desligada.
**Precisa ser marcado nas duas rotas** — marcar só numa deixa a outra aberta.

**WebSocket e Access:** o Access entrega a identidade num cookie `CF_Authorization` no
domínio. Como o PWA e a API estão no mesmo hostname, o handshake do WebSocket carrega o
cookie junto — não há nada a configurar. *(Raciocinado a partir do modelo de cookie do
Access; não testado de fora.)*

### 8.5 O token do túnel vazou — rotacione

Um token de túnel é um JSON em base64 com três campos: a conta (`a`), o UUID do túnel
(`t`) e um **segredo** (`s`). A doc da Cloudflare é direta: *"anyone with access to the
token will be able to run the tunnel"*. Quem tem o token levanta um conector que se
apresenta como esta máquina e recebe o tráfego do hostname — ou seja, o token é uma
porta para dentro da rede, não uma credencial de leitura.

**O token deste túnel foi colado em chat. Trate-o como comprometido.**

1. **Rotacione.** Dashboard → **Networking → Tunnels → JARVIS_TUNNEL → aba Overview →
   Refresh token**, e copie o comando de instalação novo. Depois de rotacionar, o
   token antigo não estabelece conexões novas; conectores já rodando continuam
   servindo até serem reiniciados — então o passo 2 não é opcional.
2. **Reinstale o serviço com o token novo**, para o arquivo em disco deixar de conter o
   valor velho:
   ```powershell
   cloudflared.exe service uninstall
   cloudflared.exe service install <TOKEN-NOVO>
   ```
   O `uninstall` apaga `%PROGRAMDATA%\cloudflared\token`; o `install` o reescreve com o
   valor novo. Se por qualquer motivo você não for reinstalar agora, apague o arquivo à
   mão — ele é o único lugar do disco onde o token antigo está.
3. **Confira o resto do disco.** Se alguma versão anterior tiver embutido o token nos
   argumentos do serviço, ele está no registro: `sc.exe qc Cloudflared` mostra o
   `BINARY_PATH_NAME` completo. Confira também o histórico do PowerShell
   (`(Get-PSReadlineOption).HistorySavePath`) — um `service install <token>` digitado no
   terminal fica gravado lá em texto claro.
4. **Onde o valor pode viver depois disso:** no `%PROGRAMDATA%\cloudflared\token`
   (escrito pelo próprio cloudflared) e, se você precisar guardá-lo, no `.env` da raiz,
   que não é versionado e não entra em imagem (§1). **Em nenhum arquivo do repositório,
   nunca — nem parcialmente, nem "só o UUID".** O UUID sozinho não é segredo, mas
   colar "só um pedaço" é como esse tipo de vazamento costuma acontecer.

Rotacione periodicamente mesmo sem incidente; a própria doc recomenda cadência regular.

### 8.6 A segunda máquina (o PC de casa)

**Não instale o mesmo token nas duas máquinas.**

O que acontece se instalar: os dois conectores viram **réplicas do mesmo túnel**. E
réplica, na Cloudflare, não é balanceamento — a doc é explícita: *"Replicas do not
support traffic steering (such as round-robin or hash-based routing)"*, e *"when a
request arrives at Cloudflare, it is forwarded to the geographically closest replica.
If that connection fails, Cloudflare retries with other replicas, but there is no
guarantee about which one is chosen"*.

Réplicas existem para alta disponibilidade de origens **idênticas e sem estado
próprio**. Aqui as duas máquinas rodariam stacks **diferentes**: dois Postgres, dois
Redis, duas memórias. O resultado é o pior tipo de bug:

- a escolha do destino é por proximidade geográfica e **sem garantia** — do ponto de
  vista do dono, arbitrária;
- duas máquinas em cidades próximas podem alternar entre requests da mesma sessão;
- o chat abre WebSocket contra uma máquina e faz `GET /api/history` contra a outra:
  histórico que some e volta, goal criado que "não existe";
- e a máquina desligada não some do túnel imediatamente — durante a janela de
  desregistro, parte do tráfego bate em porta fechada.

Nada disso aparece como erro. Aparece como "o sistema está estranho".

**Os dois padrões corretos:**

| Padrão | Como | Quando serve |
|---|---|---|
| **Um túnel por máquina** *(recomendado)* | crie um segundo túnel no dashboard (ex. `JARVIS_TUNNEL_CASA`), com token próprio e hostname próprio (ex. `ia-casa.atmosintelli.com.br`), replicando as duas rotas do §8.3 e apontando a **mesma** aplicação do Access para os dois hostnames (ou uma por hostname) | usar as duas máquinas no mesmo dia, cada uma com a sua stack e o seu banco |
| **Uma máquina por vez** | mesmo token, mas `cloudflared.exe service uninstall` na máquina que sai antes de `service install` na que entra | você só trabalha numa por vez e quer um hostname só |

O que **não** é solução: instalar nas duas e "desligar" o serviço na que não está em
uso. `Stop-Service Cloudflared` funciona enquanto você lembrar; um reboot religa o
serviço (start automático) e o problema volta silenciosamente. Se for por esse caminho,
use `sc.exe config Cloudflared start= demand` na máquina secundária, para o start
automático não desfazer a decisão.

Vale para o Compose também: o serviço `cloudflared` do Docker foi removido justamente
porque, rodando junto com o do Windows, criaria esse cenário **dentro da mesma máquina**.

### 8.7 Conferir que está certo, e o que quebra

**A conferência que vale**, porque compara o que roda com o que está versionado — o
endpoint devolve o ingress na ordem real:

```powershell
curl "https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/cfd_tunnel/<TUNNEL_ID>/configurations" `
  -H "Authorization: Bearer <CF_API_TOKEN>"
```

Compare a lista `config.ingress` com `infrastructure/cloudflared/ingress.expected.yml`:
mesmos hostnames, mesmos paths, mesmos services, **na mesma ordem**. Divergiu, o
dashboard está errado — o arquivo é a intenção revisada. *(O `<CF_API_TOKEN>` é um API
token do Cloudflare, não o token do túnel; e ele também nunca entra no repositório.)*

Checagens rápidas, de fora da rede (celular no 4G, não no Wi-Fi de casa):

```powershell
# 1. o PWA carrega e o Access intercepta antes (deve redirecionar para o login da equipe)
curl -I https://ia.atmosintelli.com.br/

# 2. a API responde pela rota certa
curl https://ia.atmosintelli.com.br/health

# 3. o serviço está de pé e conectado
Get-Service Cloudflared
```

| Sintoma | Causa provável |
|---|---|
| tudo devolve o `index.html`, inclusive `/api/...` | a rota do PWA (path vazio) está **antes** da rota da API. §8.3 |
| chat carrega mas nunca conecta; nenhum erro no log | mesma causa: `/api/chat/ws` caiu no Vite, que devolveu `200` com HTML |
| `Blocked request. This host is not allowed.` | falta o **HTTP Host Header** = `localhost:5173` na rota do PWA |
| 502 em tudo | origem errada: `api:8000`/`web:5173` não resolvem do host — use `127.0.0.1:8000` / `127.0.0.1:5173`. Ou a stack não está de pé (`docker compose ps`) |
| 502 só às vezes, ou dados que somem e voltam | dois conectores no mesmo túnel. §8.6 |
| conecta mas sem pedir login | não existe aplicação do Access cobrindo o hostname, ou a policy não é `Allow/Include/Emails` |
| a app derruba no boot reclamando de Access "pela metade" | `CF_ACCESS_*` preenchidas parcialmente. §8.4 |
| `Provided tunnel token is not valid (unexpected end of JSON input)` | o token foi colado com quebra de linha ou caractere invisível; recopie do dashboard |
| serviço não sobe depois de rotacionar | `service uninstall` + `service install <TOKEN-NOVO>`; reiniciar o serviço com o token velho não adianta |

#### Verificado vs. assumido, para esta seção

**Verificado no fonte do cloudflared** (`github.com/cloudflare/cloudflared`, `master`):
casamento de path por regex Go **não ancorada** (`ingress/rule.go`), primeira regra que
casa vence e catch-all obrigatório no fim (`ingress/ingress.go`), o que o
`service install` grava no Windows e onde (`cmd/cloudflared/windows_service.go`,
`cmd/cloudflared/common_service.go`), e que a configuração remota substitui o ingress
local em runtime (`orchestration/orchestrator.go`).

**Verificado na doc oficial:** navegação para rotas, token e *Refresh token*
(Networking → Tunnels → Overview); comportamento de réplicas (sem steering, réplica
geograficamente mais próxima, sem garantia); caminho da AUD tag e do team domain, e os
formatos de `iss` e do JWKS; nomes dos campos do dashboard (`HTTP Host Header`,
`Protect with Access`); URL do MSI; endpoint de leitura da configuração remota.

**Não verificado (flagrado no texto onde aparece):** se o dashboard atual permite
reordenar rotas já criadas por arrasto — por isso a instrução de **criar na ordem** e
conferir pelo endpoint; se o MSI recente já registra o serviço sozinho; a criação
automática do CNAME nesta zona; o comportamento do `allowedHosts` do Vite contra este
hostname (herdado da configuração anterior); o cookie do Access no handshake do
WebSocket; e a preferência `::1` vs `127.0.0.1` no resolvedor desta máquina.

#### Variáveis de ambiente

**Precisam entrar no `.env` (e no `.env.example`, sem valor):**

| Variável | Valor | Origem |
|---|---|---|
| `CF_ACCESS_TEAM_DOMAIN` | `<team>.cloudflareaccess.com` | §8.4 |
| `CF_ACCESS_AUD` | a AUD tag da aplicação | §8.4 |
| `CF_ACCESS_EMAIL` | o e-mail do dono | §8.4 — já existe no `.env.example` |

Opcionais, com default em `Settings`: `CF_ACCESS_ENFORCE` (`auto`) e
`CF_ACCESS_JWKS_TTL_SECONDS` (`3600`).

**Deixaram de ser usadas** com a remoção do serviço `cloudflared` do Compose, e podem
sair do `.env`/`.env.example`: `CLOUDFLARE_TUNNEL_ID` e
`CLOUDFLARE_TUNNEL_CREDENTIALS_FILE`.

**Nunca entra em variável versionada:** o token do túnel. Ele vive em
`%PROGRAMDATA%\cloudflared\token`, escrito pelo próprio cloudflared (§8.5).

### Dados concretos do túnel atual

- **Túnel:** `JARVIS_TUNNEL` — o UUID e o token vivem no `.env` (não versionado),
  nunca aqui. Ver §8.5.
- **Route:** `ia.atmosintelli.com.br`

**Comando de instalação no host** (o token sai do dashboard na hora, em
Networking → Tunnels → JARVIS_TUNNEL → Overview → *Add a replica*; terminal como
Administrador):

```powershell
cloudflared.exe service install <TOKEN-DO-TUNEL>
```

> Esta seção já conteve o token real, em texto claro e commitado. Ele foi
> removido do arquivo, mas **continua no histórico do git** — por isso a
> rotação do §8.5 não é higiene preventiva, é reparo de um vazamento que já
> aconteceu.

---

## 9. O que só o dono pode fazer

Tudo abaixo exige ou a **conta Cloudflare**, ou um **navegador com sessão humana**,
ou um **aparelho na mão**. Nenhum agente consegue executar nada disto, e nenhum
deles deve tentar: autenticar-se no Access como o dono é justamente o que o gate
existe para impedir.

A validação automatizada **para no 302**. Ela prova que o Access está na frente;
ela não prova que o login funciona, nem que o app é usável. As duas coisas
precisam de você.

### 9.1 Checklist

- [ ] **Login real no Access, no navegador.** Abrir `https://ia.atmosintelli.com.br`,
      completar o método de identidade (One-time PIN por e-mail, se nenhum IdP
      estiver configurado — §8.4) e confirmar que o PWA carrega **depois** do
      login. É o único teste que exercita a policy `Allow / Include / Emails` de
      ponta a ponta. Se o login não for oferecido, o método está desligado em
      *Zero Trust → Settings → Authentication*.
- [ ] **Chat conectando de verdade.** Com a sessão aberta, confirmar que o
      WebSocket `/api/chat/ws` conecta (DevTools → Network → WS → status
      `101 Switching Protocols`). É a única checagem que pega a ordem errada das
      rotas do §8.3, que não produz erro nenhum — o chat carrega e nunca conecta.
      *Resposta do modelo não é o critério aqui: não há inferência nesta máquina,
      então o chat não responder é esperado.*
- [ ] **Teclado do iOS, no aparelho.** Instalar o PWA pela tela de
      compartilhamento do Safari (*Adicionar à Tela de Início*) e digitar no
      chat. O que só aparece no aparelho: o teclado cobrindo o campo de entrada,
      o `safe-area` do notch, o scroll da conversa quando o teclado sobe e o
      zoom automático que o Safari aplica em input com fonte menor que 16px.
      Emulador de desktop não reproduz nenhum dos quatro.
- [ ] **Rotacionar o token do túnel** (§8.5) e reinstalar o serviço. O token está
      no histórico do git; a rotação é reparo, não prevenção.
- [ ] **Apontar a rota do PWA para o build de produção.** Hoje ela vai para
      `127.0.0.1:5173`, que é o **dev server do Vite** (§8.3, rota 2). O nginx de
      produção já roda e foi validado em `127.0.0.1:5174` (serviço `web-prod`,
      profile `prod`). Trocar o campo URL da rota 2 para `127.0.0.1:5174` é uma
      edição de dashboard. Com o nginx, o campo *HTTP Host Header* deixa de ser
      necessário — o nginx não valida `Host` (`server_name _`).
- [ ] **Marcar *Protect with Access* nas duas rotas** (§8.4, defesa em
      profundidade). Nas **duas**: marcar só numa deixa a outra aberta.
- [ ] **Conferir a ordem das rotas** pelo endpoint de configuração (§8.7). Exige
      um API token da Cloudflare, que não existe neste repositório.

### 9.2 O que já foi validado de fora, e como

Medido em 2026-07-31, do host, com o túnel no ar e a stack de pé:

| Verificação | Resultado |
|---|---|
| `curl -sI https://ia.atmosintelli.com.br` | `302` → `odd-poetry-1a33.cloudflareaccess.com` — Access na frente, **não** o `index.html` |
| `curl -sI .../api/health` | `302` para o login — sem JWT não passa |
| `curl -sI .../api/chat/ws` | `302` para o login — o WebSocket também está atrás do gate |
| `CF-RAY` e certificado | presente; cert Google Trust Services `WE1`, SAN `*.atmosintelli.com.br`, válido até 28/10/2026 |
| Portas em `0.0.0.0` | nenhuma. `8000`, `5173`, `5174`, `5433`, `6379` todas em `127.0.0.1` |
| `atmosintelli.com.br` / `www` | `200` (site normal, `<title>ATMOS™</title>`) e `301` para o apex — intactos |
| `web-prod` (nginx, `127.0.0.1:5174`) | SPA com fallback para `index.html`; `/assets/` inexistente dá `404`; `/api/` atravessa para a API |

O `aud` que a borda devolve no redirect de login bate com o `CF_ACCESS_AUD` que a
origem registra no boot (`cf_access.enabled`) — borda e origem falam da **mesma**
aplicação do Access. É a conferência que pega AUD copiado de outra aplicação da
conta, e ela passa.
