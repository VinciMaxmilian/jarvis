# Plano — Aba "MCP Ext": conectar MCPs externos (Drive, Gmail, etc.)

*Escrito em 2026-08-05, sobre leitura do código atual. Nada aqui está implementado.*

## 1. O objetivo

Hoje, para o Jarvis ganhar uma habilidade nova via MCP, é preciso criar uma pasta
em `mcp/`, escrever `main.py` e reiniciar. Isso funciona para servidor caseiro e
não funciona para os de terceiros — Google Drive, Gmail, Notion, Slack — que já
existem prontos, rodam por `npx`/`uvx` ou por HTTP remoto, e pedem OAuth.

A entrega é uma aba **MCP Ext** no PWA onde o dono adiciona, autentica, liga,
desliga e testa servidores MCP externos, sem tocar em código e sem reiniciar a
stack.

---

## 2. O que já existe (e o que falta)

| Peça | Onde | Estado |
|---|---|---|
| Cliente MCP multi-servidor | [client_manager.py](packages/mcp/client_manager.py) | Funciona. Conecta stdio e SSE, roteia por nome de tool (`tool_routes`) |
| `refresh()` sem reiniciar | [client_manager.py:181](packages/mcp/client_manager.py#L181) | Existe, ninguém chama |
| Merge no catálogo do agente | [executor.py:215](packages/agents/tools/executor.py#L215) | `get_all_specs` já junta system + MCP |
| Política por perfil | [tool_guard.py](packages/agents/tool_guard.py) | Recusa antes de executar. Serve para MCP também |
| Abas do PWA | [Layout.tsx:5](apps/web/src/components/Layout.tsx#L5), [App.tsx:26](apps/web/src/App.tsx#L26) | 6 abas, navegação por `useState` (sem router) |
| Rotas da API | [main.py:179](apps/api/main.py#L179) | chat, goals, settings, tools, history, memory, voice |

**O que falta, e é tudo:**

- Nenhuma **persistência** de servidor MCP. A descoberta é um `iterdir()` em
  `mcp/` ([client_manager.py:70](packages/mcp/client_manager.py#L70)) mais UMA
  URL SSE fixa no código. Não há tabela, não há CRUD.
- Nenhuma rota `/api/mcp`.
- Nenhum suporte a **OAuth** em lugar nenhum do projeto.
- Nenhum lugar para guardar **segredo** de terceiro (token, client secret).

---

## 3. O problema que vai doer, e é melhor resolver antes

`get_tools_specs()` interroga **todos** os servidores com `list_tools()`, **em
série**, **a cada mensagem** — o próprio código já registra isso como nota de
custo em [client_manager.py:120](packages/mcp/client_manager.py#L120), e o
`ChiefAI` loga `agent.catalogo_lento` acima de meio segundo.

Com servidores locais isso é caro. Com servidores **remotos** vira inviável: cada
mensagem passaria a somar uma ida à internet por servidor conectado, em série,
antes do modelo começar a responder. Num canal de voz isso é silêncio puro.

**Cache de specs com TTL é pré-requisito, não otimização.** Catálogo de MCP muda
quando o servidor muda, não a cada frase do dono:

- specs em memória com TTL (~5 min) por servidor;
- invalidação explícita no `refresh()` e ao ligar/desligar um servidor pela UI;
- `list_tools()` em paralelo (`asyncio.gather`) em vez de série;
- servidor que estourar timeout entra em `degradado` e sai do catálogo, em vez de
  segurar a resposta.

Sem isso, a aba MCP Ext entrega uma funcionalidade que piora o produto a cada
servidor adicionado.

---

## 4. Modelo de dados

Tabela nova `mcp_servers` (migration Alembic):

| Campo | Tipo | Nota |
|---|---|---|
| `id` | UUID | |
| `nome` | str único | slug, vira prefixo no log |
| `rotulo` | str | o que aparece na UI ("Meu Drive") |
| `transporte` | enum | `stdio` \| `sse` \| `http` |
| `comando` / `args` | str / json | só para `stdio` (ex.: `npx`, `["-y","@modelcontextprotocol/server-gdrive"]`) |
| `url` | str | só para `sse`/`http` |
| `env` | json | variáveis do processo — **valores sensíveis cifrados** |
| `headers` | json | idem, para transporte HTTP |
| `auth_tipo` | enum | `nenhum` \| `bearer` \| `oauth2` |
| `oauth_*` | json cifrado | tokens, refresh, expiry, client id/secret |
| `habilitado` | bool | liga/desliga sem apagar |
| `estado` | enum | `desconectado` \| `conectado` \| `erro` \| `degradado` |
| `ultimo_erro` | str | o que mostrar na UI quando cair |
| `tools_cache` | json | último catálogo conhecido + timestamp |

**Segredo não vai em claro.** Hoje o `.env` já é o cofre do projeto, mas ali quem
escreve é o dono. Aqui quem escreve é a UI, e o valor vai para o Postgres —
`pgdata` é um volume que sai em backup e em `pg_dump`. Cifra simétrica com chave
derivada de uma nova `MCP_SECRETS_KEY` no `.env`; sem a chave, o campo é ilegível
e o servidor entra em `erro` pedindo reconfiguração. Isso é o mínimo: sem cifra,
um `pg_dump` num chat vira vazamento de token do Gmail.

---

## 5. OAuth — a parte difícil, e a decisão que ela força

Google Drive e Gmail não aceitam "cole seu token". O fluxo é OAuth 2.0 com
consentimento no navegador, refresh token e escopos.

Existem dois caminhos, e eles têm custos bem diferentes:

### Caminho A — servidor MCP local que já faz o OAuth (recomendado para começar)

Os servidores oficiais (`@modelcontextprotocol/server-gdrive` e similares) rodam
por `npx` e cuidam do OAuth sozinhos, guardando as credenciais num arquivo local.
O Jarvis só precisa saber lançar o processo com o `env` certo.

- **Custo:** baixo. É `transporte=stdio` com `comando`/`args`/`env` — a UI já
  cobre isso sem nenhum código de OAuth do nosso lado.
- **Pega:** o processo precisa de Node e de um navegador para o consentimento
  inicial. Dentro do container da API não há navegador. **Consequência: o
  primeiro consentimento tem de ser feito no host**, e o servidor MCP roda no
  host — exatamente o mesmo desenho do `jarvis_windows_host`, reaproveitando a
  ponte SSE da porta 8765 que já existe e já funciona.
- É por isso que este caminho vem primeiro: ele reusa infraestrutura pronta.

### Caminho B — OAuth nativo no Jarvis (fase posterior)

Implementar o fluxo no backend: rota `/api/mcp/{id}/oauth/iniciar` que redireciona,
`/callback` que troca o código por token, refresh automático antes do vencimento.

- **Custo:** alto. É a especificação de autorização do MCP inteira (OAuth 2.1,
  PKCE, discovery de metadata, registro dinâmico de cliente).
- **Ganha:** conectar MCP remoto puro (SaaS que só existe como URL), sem processo
  local nenhum.
- **Só vale depois** que a aba estiver de pé e você souber quais servidores usa
  de verdade.

**Recomendação:** Caminho A nas fases 1–3. Caminho B só se um servidor que você
queira não tiver versão local.

---

## 6. Backend

### `packages/mcp/registry.py` (novo)
Fonte de verdade dos servidores. Lê a tabela, decifra segredo, entrega config
pronta ao `MCPClientManager`.

### `client_manager.py` (refatorar)
Hoje ele **descobre** servidores (`iterdir` + URL fixa). Passa a **receber** a
lista de quem já decidiu:

- `discover_and_connect()` continua varrendo `mcp/` (os caseiros e o `HOST_ONLY`),
  e passa a somar os do banco;
- `conectar(servidor)` / `desconectar(nome)` para ligar e desligar um só;
- cache de specs com TTL + `list_tools()` em paralelo (§3);
- `tool_routes` ganha desempate explícito: hoje o último a registrar vence em
  silêncio, e com servidores de terceiro colisão de nome (`search`, `list_files`)
  deixa de ser hipótese. Prefixar com o nome do servidor (`gdrive__search`) na
  exposição ao modelo, mantendo o nome real na chamada.

### `apps/api/routers/mcp_ext.py` (novo) — `/api/mcp`

| Método | Rota | O que faz |
|---|---|---|
| `GET` | `/api/mcp` | lista servidores + estado + nº de tools |
| `POST` | `/api/mcp` | cria |
| `PATCH` | `/api/mcp/{id}` | edita / liga / desliga |
| `DELETE` | `/api/mcp/{id}` | remove |
| `POST` | `/api/mcp/{id}/testar` | conecta, faz `list_tools`, devolve resultado **sem** salvar no catálogo vivo |
| `POST` | `/api/mcp/{id}/reconectar` | força `refresh()` |
| `GET` | `/api/mcp/{id}/tools` | catálogo daquele servidor |
| `GET` | `/api/mcp/catalogo` | presets prontos (Drive, Gmail, Notion, Slack, Filesystem) |

O **testar** é a rota que faz a aba não ser frustrante: erro de credencial aparece
na hora, com a mensagem real do servidor, em vez de virar "o agente não conseguiu"
três mensagens depois no chat.

---

## 7. Frontend

- `apps/web/src/pages/McpExtPage.tsx` (novo, `lazy` como as outras).
- Registrar em [App.tsx:13](apps/web/src/App.tsx#L13) e a aba em
  [Layout.tsx:5](apps/web/src/components/Layout.tsx#L5) — `{ id: 'mcp', icon: '🔌',
  label: 'MCP Ext' }`. `PageId` sai do próprio array, então não há tipo a mexer.

Tela:

1. **Lista** de servidores: rótulo, transporte, bolinha de estado, nº de tools,
   switch de ligar/desligar, botões testar/editar/remover.
2. **Catálogo de presets** — cartões para Drive, Gmail, Notion, Slack, Filesystem,
   com o `comando`/`args` já preenchidos. O dono só completa o segredo. É o que
   separa "usável" de "formulário de 9 campos".
3. **Formulário manual** para o que não estiver no catálogo.
4. **Expandir servidor → lista de tools** com nome, descrição e um toggle por
   tool. Nem tudo que um servidor expõe deve entrar no catálogo do modelo:
   30 tools do Drive competindo com as 19 do desktop pioram a escolha.
5. **Estado de erro visível**, com o `ultimo_erro` do banco. Falha silenciosa foi
   o que fez a ponte do host parecer quebrada por horas.

---

## 8. Segurança

O que a aba faz, na prática, é dar ao modelo acesso ao seu e-mail e aos seus
arquivos. Os itens abaixo não são opcionais:

1. **Segredo cifrado no banco** (§4), nunca devolvido pela API — o `GET` mostra
   `configurado: true`, não o valor.
2. **Ligar um servidor é ato do dono**, nunca do agente. Nenhuma tool `mcp_*` de
   gestão entra no catálogo do modelo; a superfície é só a UI.
3. **Tool de terceiro entra em `_ACAO`**, não em `_LEITURA`
   ([profiles.py:141](packages/agents/profiles.py#L141)): `planner`, `researcher`
   e `reviewer` não mandam e-mail.
4. **Confirmação para o que sai da máquina.** Enviar e-mail, compartilhar arquivo,
   apagar no Drive — mesma regra do computer use: recusa pedindo confirmação
   explícita. Aqui o erro não é um clique errado, é uma mensagem enviada para a
   pessoa errada, e isso não tem desfazer.
5. **Escopo mínimo no OAuth.** Gmail com escopo de leitura se o objetivo é ler.
6. **Auditoria** de toda chamada a MCP externo, com argumentos, no mesmo formato
   de `data/desktop_audit/`.
7. **Timeout e disjuntor por servidor:** servidor que falha N vezes entra em
   `degradado` e sai do catálogo até o dono reconectar. Sem isso, um MCP remoto
   fora do ar trava toda conversa.

---

## 9. Fases

### Fase 0 — Cache de specs (1 dia) · *pré-requisito*
- [ ] TTL + `asyncio.gather` + timeout por servidor em `get_tools_specs`.
- [ ] Teste: 3 servidores, um deles lento, não somam no tempo de resposta.
- **Aceite:** `agent.catalogo_lento` para de aparecer com 3+ servidores.

### Fase 1 — Persistência e API (2 dias)
- [ ] Migration `mcp_servers` + cifra de segredo.
- [ ] `packages/mcp/registry.py`.
- [ ] Router `/api/mcp` com CRUD + `testar`.
- **Aceite:** adicionar servidor por `curl`, `testar` devolve a lista de tools.

### Fase 2 — Conexão dinâmica (2 dias)
- [ ] `conectar`/`desconectar` sem reiniciar; prefixo anti-colisão de nome.
- [ ] Disjuntor e estado `degradado`.
- **Aceite:** ligar um servidor pela API e o modelo usar a tool no turno seguinte.

### Fase 3 — Aba MCP Ext (3 dias)
- [ ] `McpExtPage.tsx` + aba no Layout.
- [ ] Presets (Drive, Gmail, Notion, Slack, Filesystem).
- [ ] Toggle por tool, estado de erro visível.
- **Aceite:** conectar o Google Drive pela UI, sem editar arquivo, e pedir ao
  Jarvis "liste meus últimos arquivos do Drive".

### Fase 4 — OAuth nativo (4–5 dias, opcional)
- [ ] Fluxo OAuth 2.1 + PKCE, refresh automático.
- **Aceite:** conectar um MCP remoto puro, só com URL.

**Total: ~8 dias** até a Fase 3, que é onde o valor está. A Fase 4 só se
necessária.

---

## 10. Riscos

| Risco | Mitigação |
|---|---|
| Catálogo inchado degrada a escolha do modelo | Toggle por tool (§7.4); prefixo por servidor; teto de tools ativas |
| MCP remoto lento trava toda conversa | Fase 0 é pré-requisito; disjuntor |
| Colisão de nome entre servidores | Prefixo `servidor__tool` na exposição |
| Vazamento de token por `pg_dump` | Cifra com `MCP_SECRETS_KEY` fora do banco |
| Servidor `stdio` precisa de Node no container | Caminho A roda no host, pela ponte SSE que já existe |
| Modelo local pequeno erra mais com catálogo grande | Toggle por tool; considerar catálogo por perfil de agente |
| Agente liga servidor sozinho | Gestão fora do catálogo do modelo (§8.2) |

---

## 11. Decisões que preciso que você tome

1. **Caminho A ou B para o Drive/Gmail?** A recomendação é A (servidor local no
   host, reusando a ponte 8765). B é ~5 dias a mais.
2. **Toggle por tool desde a Fase 3, ou tudo-ou-nada por servidor?** Por tool é
   mais trabalho e evita o catálogo inchado, que é o risco mais provável aqui.
3. **Quais servidores entram no catálogo de presets?** Drive e Gmail são certos;
   Notion, Slack, GitHub, Filesystem — quais você usa?
4. **Confirmação para ação externa** (enviar e-mail, compartilhar arquivo): mesma
   régua do computer use, ou a aba MCP Ext fica livre?
