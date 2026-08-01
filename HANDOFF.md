# Handoff — trabalho interrompido no meio (2026-07-30)

Dois agentes foram parados antes de terminar: um por limite de sessão da API, o
outro por decisão do dono. O código que eles produziram **está no disco e é
substancial** — não é rascunho. Este arquivo diz exatamente onde cada um parou,
o que está verificado, o que está quebrado e o que falta.

Regra deste arquivo: **nada aqui é declarado, tudo é medido.** Todo número abaixo
saiu de um comando real, colado como saiu.

---

## 0. Estado da árvore

Tudo que veio antes do túnel está **commitado e pushado** (`a`, `b` sobre
`7d696ea cintune`). O trabalho do túnel descrito aqui está **no working tree**.

Não versionados e não relacionados a este trabalho: `.agents/`, `.codex/`,
`AGENTS.md` — instalação da skill do graphify para outras ferramentas de agente.

---

## 1. Como rodar qualquer coisa

**Não existe Python utilizável no PATH desta máquina.** Os venvs de `apps/api` e
`orchestrator` têm as dependências da app mas não têm `pytest`; o Python do
sistema tem `pytest` mas não tem `anthropic` nem `structlog`, e a coleta morre no
import do `conftest`. Tudo roda em container, com o repositório montado (edição no
host vale na hora, sem rebuild):

```powershell
$C = "-f infrastructure/docker/docker-compose.yml --env-file .env"

docker compose $C --profile test run --rm test pytest
docker compose $C --profile test run --rm test mypy packages/
docker compose $C --profile test run --rm test ruff check .
```

**Exceção:** mexeu em `pyproject.toml`, precisa rebuildar antes de a dependência
existir:

```powershell
docker compose $C --profile test build test
```

---

## 2. Placar agora

| Verificação | Baseline (antes do túnel) | Agora | Situação |
|---|---|---|---|
| `pytest` | 128 passed, 4 xfailed | **182 passed, 4 xfailed, 0 failed** | as 2 falhas do Access foram corrigidas — §4 |
| `mypy packages/` | Success, 26 arquivos | Success, 26 arquivos | sem regressão |
| `ruff check .` | All checks passed | **1 error** | `packages/shared/settings.py:104` E501, com dono |
| `docker compose config` | resolve | resolve | ok |

`mypy` sobre `apps/api` acusa 9 erros, mas eles são **backlog anterior**
(`routers/tools.py`, `routers/goals.py`, `routers/chat.py`, `db/models.py` —
`dict` sem parâmetro de tipo, anotação de retorno faltando). Nenhum deles está em
`apps/api/cf_access.py`. Não foi introduzido agora; também não foi resolvido.

---

## 3. Agente A — Cloudflare Tunnel (infraestrutura)

**Parou por:** limite de sessão da API, no meio da validação das regras de
ingress com o próprio `cloudflared`.

### Entregue e no disco

| Arquivo | O que tem |
|---|---|
| `infrastructure/cloudflared/config.yml` | ingress completo e comentado |
| `infrastructure/cloudflared/.gitignore` | barra `credentials.json` |
| `infrastructure/docker/docker-compose.yml` | serviço `cloudflared` atrás do profile `tunnel` |

**Decisão tomada: túnel _locally-managed_, não o de token.** O motivo está escrito
no topo do `config.yml` e vale repetir: as regras de roteamento são uma **lista
ordenada** casada por regex de path. Num túnel por token essa lista mora no
dashboard, como itens arrastáveis que nenhum diff revisa — e trocar a ordem de
dois itens manda `/api/chat/ws` para o Vite, que devolve `index.html` em vez de
abrir o WebSocket. Erro silencioso. Em arquivo, a ordem aparece no `git diff`.

Roteamento definido para `ia.atmosintelli.com.br`:

1. `^/api(/|$)` → `http://api:8000` — inclui o WebSocket `/api/chat/ws`. Vai
   direto na API em vez de passar pelo proxy do Vite: tira um salto do streaming e
   sobrevive à troca do dev server por nginx.
2. resto → `http://web:5173`, com `httpHostHeader: localhost:5173`. **Isso não é
   cosmético**: o Vite valida o header `Host` contra `server.allowedHosts` e
   responderia `Blocked request` a `ia.atmosintelli.com.br`.
3. catch-all `http_status:404` — obrigatório, e escolhido para que qualquer
   hostname que não seja o nosso morra ali em vez de vazar para dentro da stack.

Nenhuma porta nova publicada, em serviço nenhum. É o aceite da v1.5.

### Falta

1. **`infrastructure/README.md` §8 nunca foi escrito.** O README hoje tem §1 a §7.
   Falta a seção com o click-path do dashboard: criar o túnel, pegar o UUID e o
   JSON de credenciais, criar o hostname público `ia`, criar a aplicação Zero
   Trust do Access, e onde achar o **AUD tag** e o **team domain** — os dois
   valores que o Agente B consome.
2. **`.env.example` não ganhou as variáveis do túnel.** Faltam
   `CLOUDFLARE_TUNNEL_ID` e `CLOUDFLARE_TUNNEL_CREDENTIALS_FILE`.
3. **Nada foi validado contra o `cloudflared` de verdade** — foi exatamente onde o
   agente morreu. O `config.yml` nunca passou por `cloudflared tunnel ingress
   validate`. Trate-o como não verificado.
4. O bloco `originRequest.access` (validação do JWT pelo próprio conector, defesa
   em profundidade) está **comentado** no `config.yml`, esperando os dois valores
   que só existem depois de criar a aplicação no dashboard.

### Risco registrado, não resolvido

O túnel aponta para o **dev server do Vite**. É um servidor de desenvolvimento,
com HMR sobre WebSocket, exposto à internet. `apps/web/Dockerfile` tem os estágios
`build` + `nginx` apenas como comentário — nunca foram escritos. Isso precisa de
decisão antes de o túnel ficar de pé em caráter permanente.

---

## 4. Agente B — validação do JWT do Access na origem

**Parou por:** foi encerrado pelo dono, enquanto rebuildava a imagem de teste.

### Entregue e no disco

| Arquivo | O que tem |
|---|---|
| `apps/api/cf_access.py` | `JwksCache`, verificador, `install_cloudflare_access` |
| `apps/api/main.py` | middleware instalado; ordem em relação ao CORS comentada como significativa |
| `packages/shared/settings.py` | 5 campos novos + validadores + 5 propriedades derivadas |
| `pyproject.toml` | `PyJWT[crypto]>=2.8` (o extra `[crypto]` não é opcional: sem ele o PyJWT não faz RS256) |
| `tests/unit/test_cf_access.py` | ~30 testes, chaves RSA geradas na fixture, zero rede |

Configuração adicionada: `cf_access_team_domain` (aceita `meutime` ou
`meutime.cloudflareaccess.com`, normalizado por validador), `cf_access_aud`,
`cf_access_email` (que já existia sem uso), `cf_access_enforce`
(`auto` | `on` | `off`) e `cf_access_jwks_ttl_seconds`.

**Decisão sobre o default do enforcement:** `auto` — liga sozinho quando as três
variáveis do Access estão preenchidas. Com `environment=prod` e as variáveis
vazias, `_validate_cf_access` **derruba o boot** em vez de servir uma origem sem
autenticação. É o comportamento certo: o modo de falha proibido aqui é o
fail-open silencioso.

### Quebrado — 2 testes → **CORRIGIDO (mesma sessão)**

As duas falhas abaixo estão resolvidas; `tests/unit/test_cf_access.py` agora dá
54 passed. A descrição fica como registro do que era e do que foi decidido.

**(a) `test_verificador_devolve_as_claims` — bug do teste, não do código.**

```
assert claims["aud"] == [AUD]  # PyJWT normaliza `aud` para lista
E  AssertionError: assert 'aaaa…' == ['aaaa…']
```

O comentário está errado: o PyJWT **não** normaliza um `aud` string para lista,
devolve a string. Correção é de uma linha, no teste. A verificação em si funciona
— o `aud` é conferido pelo próprio `jwt.decode`.

**(b) `test_kid_desconhecido_nao_vira_tempestade` — desacordo real de design.**

```
assert jwks.hits == 2, "uma rebusca, não uma por requisição"
E  assert 1 == 2
```

O que o teste quer: `kid` desconhecido dispara **exatamente uma** rebusca do
JWKS, e as tentativas seguintes caem no cooldown. O que o código faz: o cooldown
começa a contar já na **carga inicial**, então a primeira rebusca nunca acontece.

Isso importa de verdade. `kid` inventado é o caminho de quem forja token: sem
cooldown, cada requisição forjada vira um GET nosso para a Cloudflare, e o
atacante passa a escolher o nosso tráfego de saída. Mas com o cooldown como está,
**uma rotação de chave legítima da Cloudflare deixa a API recusando todo mundo até
o TTL expirar** — falha fechada, mas indisponível.

**Decisão tomada:** carga inicial deixou de ser rebusca e não gasta mais o
orçamento do cooldown. O teste estava certo — contando a carga inicial, um `kid`
girado logo após o boot cai direto no freio e a API recusa todo mundo por uma
janela inteira **sem uma única tentativa de se recuperar**, e o evento que dispara
isso é controlado pela Cloudflare, não por nós. Custa no máximo uma requisição a
mais.

Junto entrou o contrapeso: tentativa que **falha** conta para o cooldown mesmo
sendo a carga inicial. Sem isso, a isenção acima abriria a mesma tempestade por
outro caminho — JWKS fora do ar viraria um GET nosso por requisição recebida.

### Falta

1. Corrigir os 2 testes acima.
2. `.env.example` não ganhou nenhuma das variáveis novas do Access, e o comentário
   do `CF_ACCESS_EMAIL` que já estava lá diz "opcional" — agora ele é parte de um
   conjunto que, incompleto em prod, derruba o boot.
3. 3 × E501 (`packages/shared/settings.py:104`, `tests/unit/test_cf_access.py:431`
   e `:595`) — o `ruff` do CI é passo bloqueante.
4. Middleware nunca exercitado contra um Access de verdade. Os testes assinam os
   próprios tokens; ninguém passou por `ia.atmosintelli.com.br` ainda.

---

## 5. Ordem sugerida para retomar

~~1. 3 × E501~~ — feito, sobrou 1 e tem dono.
~~2. `test_verificador_devolve_as_claims`~~ — feito, era o teste.
~~3. Cooldown do JWKS~~ — decidido e implementado, ver §4.

Restante:

4. **`.env.example`** — as variáveis novas (túnel + Access + perfis de modelo),
   num bloco só, com o aviso de que em `prod` o conjunto de Access incompleto
   derruba o boot. Depende do que os agentes em curso reportarem.
5. **`infrastructure/README.md` §8** — click-path do dashboard.
6. **Decidir o estágio de produção do PWA** antes de deixar o túnel de pé — hoje o
   que ficaria exposto é o dev server do Vite. **Este é o item mais importante da
   lista** e o único sem dono.

O item 4 não depende de nada externo. Os itens 5 e 6 dependem de decisão do dono.

### Mudou desde que este arquivo foi escrito

O dono foi por outro caminho no túnel: criou **JARVIS_TUNNEL** no dashboard em
modo **token** e instala o conector como **serviço do Windows no host**
(`cloudflared.exe service install <token>`), não em container. Isso inverte a
premissa da §3: o conector passa a enxergar `127.0.0.1:8000` e `127.0.0.1:5173`
(portas publicadas em loopback), não `api:8000` da rede do Compose, e as regras de
ingress passam a viver no dashboard. Há um agente reconciliando isso.

**O token colado no chat é credencial viva** — decodifica para JSON com `a`
(conta), `t` (UUID) e `s` (segredo). Precisa ser rotacionado.

---

## 6. O que o dono precisa fazer no dashboard

Nada disso pode ser feito por aqui — exige a conta Cloudflare.

| Precisa | Vira a variável |
|---|---|
| Criar o túnel (Zero Trust → Networks → Tunnels) | `CLOUDFLARE_TUNNEL_ID` |
| Baixar o JSON de credenciais do túnel | `CLOUDFLARE_TUNNEL_CREDENTIALS_FILE` (caminho no host) |
| Public hostname `ia.atmosintelli.com.br` | — |
| Access application sobre esse hostname, política com o e-mail do dono | `CF_ACCESS_AUD`, `CF_ACCESS_TEAM_DOMAIN`, `CF_ACCESS_EMAIL` |

O apex `atmosintelli.com.br` e o `www` **não são tocados** por nada disto: é um
subdomínio novo, com zona, aplicação Access e regra de ingress próprias.
