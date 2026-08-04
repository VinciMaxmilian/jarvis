# Planos — Design Industry, Voz Live, Self-Evolution, Capabilities

Documento de planejamento (2026-08-04). Nada aqui foi implementado. Complementa
`ESTADO_DO_PROJETO.md`, que descreve o estado real do código.

---

## Plano A — Adotar o visual "Jarvis Command" (Industry) em web + desk

### A.0 O que a fonte realmente é

Projeto Claude Design `6448b535-26d2-432a-a513-9b566f2ae4b2` ("Projeto Jarvis
interface STARK"), tipo `PROJECT_TYPE_PROJECT`.

| Arquivo | O que é | Aproveitável? |
|---|---|---|
| `Jarvis Command.dc.html` | 92 KB, mock estático, quase tudo `style=""` inline, dados fake | **Referência visual apenas.** Não portar markup |
| `_ds/industry-…/styles.css` | Tokens + camada de componentes. Plain CSS, sem build | **Sim — é a base real** |
| `_ds/industry-…/readme.md` | Guia do sistema (regras do blueprint) | Sim, como contrato de estilo |
| `_ds/industry-…/_ds_bundle.js` | Bundle do preview | Não |
| `support.js` | Runtime `<x-dc>` do Claude Design (React) | **Não.** É harness de preview |

**Tokens do Industry:** fundo `#f2f2f3`, texto `#1d1f20`, acento aço `#5980a6`,
rampas 100–900 em OKLCH, `--space-1..8` (3.4 → 27.2px), `--radius-sm/md/lg`
(2/4/7px) — **anulados** pela camada blueprint (`.card,.btn,.input,.tag,.seg,.dialog
{ border-radius: 0 }`), `--shadow-sm/md/lg`.

**Gramática blueprint:** objeto = quadrado, borda hairline, **fundo transparente**,
4 marcas de registro (`.blueprint` + `<i class="corner tl|tr|bl|br">`). Única
exceção sólida: `.btn-primary`. Tipografia Barlow Condensed (títulos) sobre
Barlow (corpo). Ícones Lucide stroke 1.5.

**A tela Jarvis é uma inversão escura do DS:** `body` vira `#101a24`, texto vira
`var(--color-bg)`, e o fundo ganha grade (linhas de `--color-accent-300` a 4%,
passo 34px) + radial `#1d2d3d → #101a24`. O `readme.md` do DS diz explicitamente
que em fundo escuro o estado pressionado muda para `--color-accent-400`. Ou seja:
**é um segundo tema, não um override solto.**

**Painéis do mock** (vocabulário a implementar): `ESTADO DO KERNEL`,
`MATRIZ DE SUBSISTEMAS`, `OBJETIVOS PERSISTENTES`, `CADEIA DE TASKS`,
`MAPA NEURAL`, `TRECHO DO GRAFO`, `EVENTOS`/`BUS`/`FILA`, `TOOLS DECLARADAS`,
`CAPABILITIES`, `CUSTO DO TURNO`, `NESTE TURNO`, `CANAL DIRETO` (chat),
`INFRA`/`REDE`/`DISCO`/`RUNTIME`, `TRUST`/`ZERO`, `EVO`, `DIGEST`/`HIST`, `RULES`.

**Grids do mock:** `292px minmax(420px,1fr) 322px`, `minmax(0,1fr) 348px`,
`repeat(2,minmax(0,1fr)) 320px`, `repeat(5,minmax(0,1fr))`, `88px 1fr`.

### A.1 O obstáculo real

`apps/web/src/index.css` carrega um sistema **neumórfico claro** completo
(`--neu-bg`, `--neu-hi/lo`, sombras duplas `--neu-xs..lg`, `--neu-in-*`, `--ink*`,
mais aliases legados `--hud-*` em `hsl()`). E `Layout.tsx`, `Sidebar.tsx` e as
páginas usam **objetos de estilo inline**, não classes.

Consequência: trocar tokens muda cor, mas **não** mata sombra dupla nem raio
arredondado embutidos no JSX. Neumorfismo e blueprint são opostos — um é volume
por sombra, o outro é linha sem preenchimento.

### A.2 Estratégia: ponte de tokens, depois migração por página

**Fase D0 — fundação (1 commit, muda tudo de cara)**
1. `apps/web/src/styles/industry.css`: copiar o token sheet do DS + camada de
   componentes. **Não** usar o `@import` do Google Fonts do DS.
2. Fontes self-hosted: `@fontsource/barlow` + `@fontsource/barlow-condensed`.
   Motivo: PWA offline (`vite-plugin-pwa`) e `nginx/security-headers.inc`
   quebram com fonte remota; e o desk roda com `csp: null` hoje, que deve ser
   fechado depois.
3. `[data-theme="command"]`: camada escura (fundo `#101a24`, grade 34px, texto
   `--color-bg`, pressed → `--color-accent-400`, divider recalculado sobre
   escuro). O `ThemeContext.tsx` existente passa a alternar
   `industry-light` ⇄ `command-dark` em vez de claro/escuro ad-hoc.
4. **Ponte:** redefinir os nomes legados sobre os tokens novos —
   `--neu-xs..lg: none`, `--neu-surface: transparent`, `--ink → --color-text`,
   `--accent → --color-accent`, `--radius*: 0`, e uma borda hairline global nos
   contêineres que hoje dependem de sombra. Assim as páginas não migradas já
   nascem no visual novo, sem ficarem quebradas.

**Fase D1 — primitivos React** em `apps/web/src/components/ds/`:
`<Panel>` (blueprint + 4 corners + kicker), `<Stat>`, `<Meter>`, `<Tag>`,
`<Btn>`, `<Field>`, `<DataTable>`, `<Feed>`, `<Readout>` (números monoespaçados
do HUD). Regra: **nenhum hex, px ou nome de fonte literal** — só `var(--*)`.

**Fase D2 — migração por página**, uma por commit, removendo estilo inline:
`Layout`+`Sidebar` → `ChatPage` (CANAL DIRETO) → `ToolsPage` (TOOLS DECLARADAS)
→ `HistoryPage` (DIGEST) → `MemoryPage` → `RulesPage` → `BrainPage`/`NeuralMap`
(só moldura + paleta; o canvas já existe).

**Fase D3 — página nova `CommandPage`** (o cockpit do mock). Não existe hoje.
Depende de backend que **não existe**:

| Painel | Fonte de dados | Existe? |
|---|---|---|
| OBJETIVOS / TASKS | `routers/goals.py` | ✅ |
| TOOLS DECLARADAS | `routers/tools.py` | ✅ |
| MAPA NEURAL / GRAFO | `graphify-out/graph.json` | ✅ |
| DIGEST / HIST | `routers/history.py` | ✅ |
| ESTADO DO KERNEL, CARGA, UPTIME, COMMIT | — | ❌ novo `/metrics` |
| BUS / FILA / EVENTOS | Redis Streams (`XLEN`, lag do grupo) | ❌ novo |
| CAPABILITIES | `registry` | ❌ não exposto em rota |
| CUSTO DO TURNO | — | ❌ precisa contabilizar tokens no provider |
| INFRA / DISCO / REDE | — | ❌ novo |
| TRUST / ZERO | `cf_access.py` | ⚠️ parcial |

Sem esses endpoints o cockpit vira mock — decidir se entra com placeholders
marcados ou se o backend vem junto.

**Fase D4 — desk.** Herda tudo de graça (`frontendDist` aponta pra `apps/web`).
Específico: `titleBarStyle`/decorações escuras pra não ter faixa branca,
`backgroundColor` da janela = `#101a24` (evita flash branco no boot), ícone de
tray monocromático coerente, e revisar `csp: null` agora que a fonte é local.

### A.3 Riscos
- `color-mix()` + OKLCH: ok no WebView2/Chromium atual; fixar versão mínima do
  WebView2 no README do desk.
- Contraste: o próprio DS avisa que acento×fundo é ~3:1 — serve pra chrome e
  texto grande, **não** pra corpo de texto. Em fundo escuro usar passo claro da
  rampa, não o acento base.
- Migrar estilo inline é o grosso do esforço, não o CSS.

### A.4 Mapa de tokens — a ponte, linha a linha

`apps/web/src/index.css` hoje é um sistema neumórfico completo. A ponte não
apaga esses nomes: **redefine o que eles valem**. Assim nenhuma página quebra
enquanto a migração acontece.

| Nome legado (fica) | Vira | Por quê |
|---|---|---|
| `--neu-bg`, `--neu-surface` | `transparent` (objetos) / `--color-bg` (fundo) | blueprint é linha, não superfície preenchida |
| `--neu-xs/sm/md/lg` | `none` | sombra dupla é o oposto do hairline |
| `--neu-in-sm/md` | `none` + `border: 1px solid var(--color-divider)` | "afundado" vira campo com borda |
| `--neu-hi`, `--neu-lo` | `transparent` | eram os dois lados da luz neumórfica |
| `--neu-edge`, `--neu-edge-lo` | `--color-divider` | fio de luz vira hairline |
| `--accent` | `--color-accent` (`#5980a6`) | |
| `--accent-soft` | `--color-accent-400` | passo claro, legível no escuro |
| `--accent-ink` | `--color-bg` | texto sobre o acento sólido |
| `--accent-glow` | `color-mix(accent 22%)` | usado nos realces do HUD |
| `--ink`, `--ink-2`, `--ink-3` | `--color-text`, `mix 70%`, `mix 50%` | |
| `--radius`, `--radius-sm`, `--radius-lg` | `0` | regra dura do DS |
| `--hud-*` (legado em `hsl()`) | recalculados sobre `#101a24` | páginas ainda os usam |

Regra de ouro depois da ponte: **nenhum arquivo novo escreve hex, px de espaço
ou nome de fonte** — só `var(--color-*)`, `var(--space-*)`, `var(--font-*)`.

### A.5 Inventário de componentes a criar

Em `apps/web/src/components/ds/`. A coluna "fonte" diz de onde sai a marcação —
o `styles.css` do DS já traz a classe pronta; o mock só mostra o arranjo.

| Componente | Fonte | Onde aparece no mock |
|---|---|---|
| `<Panel kicker title>` | `.blueprint` + 4 `<i class="corner">` | todo painel do cockpit |
| `<Readout>` | mock (inline) | CARGA, UPTIME, COMMIT, HORA LOCAL |
| `<Stat label value unit>` | `.card-kicker` + `.card-title` | MATRIZ DE SUBSISTEMAS |
| `<Meter value max>` | mock (`@keyframes bar`) | DISCO, REDE, FILA |
| `<Tag tone>` | `.tag`, `.tag-outline` | STATUS, PRIOR., TRUST |
| `<Btn variant>` | `.btn` + variantes | ENTRADA, ações |
| `<Field>` / `<Input>` | `.field`, `.input` | CANAL DIRETO |
| `<DataTable>` | `.table` | TOOLS DECLARADAS, CADEIA DE TASKS |
| `<Feed>` | mock (`@keyframes creep`) | EVENTOS / BUS |
| `<Dialog>` | `.dialog` + `.dialog-backdrop` | confirmações, Gate 2 |

Ícones: **Lucide, stroke 1.5** (regra do DS). Hoje `Layout.tsx` usa emoji
(`💬 🧠 💾 🔧 📋 ⚙️`) — trocar, emoji não tem stroke nem herda cor.

Animações do mock que valem portar: `corepulse` (núcleo do HUD), `sweep`
(varredura), `creep` (entrada de linha de log), `blink` (indicador vivo), `bar`
(medidor). Todas devem respeitar `@media (prefers-reduced-motion: reduce)` — o
mock não faz isso.

### A.6 Checklist por página

| Ordem | Página | O que muda | Risco |
|---|---|---|---|
| 1 | `Layout` + `Sidebar` | chrome, nav, tabs; sai estilo inline; entram ícones Lucide | baixo — muda a cara toda de uma vez |
| 2 | `ChatPage` | vira CANAL DIRETO: painel + `<Feed>` + `<Field>`; `MarkdownRenderer` precisa de tema de código escuro | médio — KaTeX e blocos de código têm estilo próprio |
| 3 | `ToolsPage` | vira TOOLS DECLARADAS com `<DataTable>` | baixo |
| 4 | `HistoryPage` | vira DIGEST / HIST | baixo |
| 5 | `MemoryPage` | painéis por nível de memória | baixo |
| 6 | `RulesPage` | formulário com `.field`/`.input` | baixo |
| 7 | `BrainPage` + `NeuralMap` | só moldura e paleta; `Engine.ts` desenha em canvas com cores próprias | **alto** — as cores estão no TS, não no CSS; extrair para tokens antes |
| 8 | `VoiceButton` | vira o núcleo pulsante do HUD (`corepulse`) | baixo |

### A.7 Sequência de commits

1. `feat(web): tokens Industry + fontes self-hosted` — `industry.css`, `@fontsource`, sem tocar em componente.
2. `feat(web): tema command-dark e ponte de tokens legados` — o app inteiro muda de cara aqui.
3. `feat(web): primitivos ds/` — componentes novos, ainda não usados.
4. `refactor(web): Layout e Sidebar sobre ds/` — primeira página sem inline.
5. …um commit por página, ordem da A.6.
6. `feat(desk): janela escura` — `backgroundColor`, decorações, ícone de tray.
7. `feat(api): /metrics` — só quando o cockpit entrar.
8. `feat(web): CommandPage` — por último, depende de 7.

Cada commit deve deixar o app **utilizável**. Nada de "migração grande" numa
branch longa: a ponte (2) existe justamente para permitir parar no meio.

### A.8 Critérios de aceite

- `npm run build` limpo e `oxlint` sem erro novo.
- Nenhum hex ou `px` de espaçamento fora de `industry.css` (grep no CI).
- Zero requisição a `fonts.googleapis.com` em produção (a aba Network prova).
- Contraste: corpo de texto ≥ 4.5:1; acento puro só em chrome e texto grande.
- `prefers-reduced-motion` desliga as cinco animações.
- Desk abre sem flash branco e sem faixa de titlebar clara.
- PWA continua instalável e funcionando offline.

### A.9 O que não fazer

- **Não** copiar markup do `Jarvis Command.dc.html`: é inline, com dado fake, e
  depende do runtime `<x-dc>` do `support.js`.
- **Não** portar `support.js` nem `_ds_bundle.js` — são o harness de preview do
  Claude Design, não bibliotecas.
- **Não** manter `@import` de fonte remota do DS.
- **Não** arredondar canto nem preencher card: o DS trata isso como violação, e
  metade da identidade do visual está nisso.
- **Não** tirar as marcas de registro (`.corner`) de um elemento emoldurado.
- **Não** mexer no mobile agora — o escopo é web + desk.

---

## Plano B — Voz A2A com Gemini Live (P4)

Substitui o pipeline atual (`routers/voice.py`: faster-whisper `tiny` +
`webrtcvad` + LM Studio + `edge_tts`), que **continua sendo o fallback**.

### B.1 Topologia
```
navegador  --PCM16 16k-->  FastAPI /voice/live  --WS-->  Google Live API
navegador  <--PCM 24k----  FastAPI            <--WS---  Google
```
**Proxy no servidor, nunca direto do navegador.** Três motivos: a chave nunca
sai do servidor; o Cloudflare Access já protege a origem; e as tool calls
precisam passar pela camada de autorização do Jarvis.

### B.2 Etapas
1. **B-1 Transporte.** Rota `/voice/live` no FastAPI, ponte bidirecional,
   reconexão com *session resumption*, encerramento limpo. Flag em
   `system_settings` escolhe `live` ou `legacy` — nada é removido.
2. **B-2 Áudio no cliente.** `AudioWorklet` para captura e reprodução (não
   `ScriptProcessor`). **Barge-in**: ao receber sinal de interrupção, esvaziar
   a fila de reprodução imediatamente — sem isso o Jarvis fala por cima de si.
3. **B-3 Tools.** Gerar `function_declarations` a partir do `ToolSpec` do
   Capability Registry; executar via `ProfiledToolExecutor` (perfil `executor`,
   entregue no P3). Toda chamada passa pelo guard — o modelo não executa nada
   direto.
4. **B-4 Visão de tela.** `getDisplayMedia` → 1 fps, ~768px, JPEG q60 → ring
   buffer de 300 quadros (5 min) **em memória no cliente**. Enviar só sob
   demanda (últimos N quadros), nunca o buffer inteiro — é o item mais caro do
   plano. Nada em disco por padrão; interruptor visível de privacidade. No desk,
   captura via Tauri evita o prompt do navegador a cada sessão.
5. **B-5 Documentos** (`docx/pdf/xlsx/csv`): **é capability**, não voz. Ver
   Plano D.
6. **B-6 Ingestão de links/arquivos**: **é capability**. Ver Plano D.

### B.3 A confirmar antes de codar
- ID e endpoint exatos do modelo Live (o doc chama de "Gemini 3.1 Live") e
  limite de duração de sessão — ler a doc do Google na hora, não de memória.
- Qualidade da voz nativa em PT-BR.
- Latência via Cloudflare Tunnel: medir antes de prometer "baixa latência".
- Custo por minuto com vídeo ligado.
- Já existe `packages/llm/gemini_provider.py` — verificar se a credencial serve
  ou se a Live API exige outra.

---

## Plano C — Self-Evolution (P5)

**Pré-requisito duro:** suíte verde. Hoje o baseline é **14 failed / 24 errors**
(sandbox no Windows, `cf_access`, contagem CRLF). Um pipeline que decide instalar
código com base em "os testes passaram" é inútil enquanto o sinal de teste for
ruído. Isso vem antes de qualquer linha do P5.

### C.1 Máquina de estados
```
GAP → SPEC_DRAFT → GATE1_PENDING → GATE1_OK → CODEGEN → TESTS
    → BRANCH → GATE2_PENDING → GATE2_OK → DRY_RUN → INSTALLED
qualquer etapa → REJECTED | FAILED
```
Tabela nova `evolution_runs` (migration alembic) + eventos no Redis Streams.
Gatilho: `CapabilityGapDetected`, que **já existe** (`packages/registry/gap.py`),
consumido por um consumer group dedicado.

### C.2 Etapas
1. **C-1 SPEC.** Perfil `planner` redige a SPEC; perfil `reviewer` critica antes
   do Gate 1 (filtro barato — corta ideia ruim antes de gastar humano).
2. **C-2 Gate 1 (mobile).** `expo-notifications` + tabela de push tokens +
   `POST /evolution/{id}/approve|reject`. Expo Push Service primeiro (dispensa
   configurar FCM/APNs). É a razão de existir do app mobile e hoje não existe.
3. **C-3 Codegen.** Perfil `executor` escreve em branch `evo/<slug>`, usando o
   SDK (`manifest_de`) e obrigatoriamente casos de `CapabilityHarness`.
   **Allowlist de caminho: só `capabilities/`.** Nunca `packages/kernel`,
   `packages/registry` ou `apps/`.
4. **C-4 Testes** rodam no sandbox existente (`packages/kernel/runtime/`).
5. **C-5 Gate 2 (desk).** Tela com diff, permissões pedidas pelo manifesto e
   saída dos testes. Precisa do plugin de notificação nativa no Tauri
   (deliberadamente fora do escopo do P2).
6. **C-6 Dry-run.** Primeira execução com filesystem/network em negação total e
   gravação do que foi tentado. Só depois de dry-run limpo o registry marca
   `ACTIVE`, com manifesto assinado (`packages/registry/integrity.py`).

### C.3 Trilhos de segurança
Teto de tentativas por objetivo; humano obrigatório nos dois gates; sem
auto-modificação fora de `capabilities/`; toda instalação reversível por
`git revert` + desregistro no registry.

---

## Plano D — Capabilities (prioridade máxima)

> Um agente já está entregando `filesystem`, `shell` e possivelmente `http`.
> Confirmar o que chegou antes de começar — não duplicar.

Ordem por desbloqueio, não por facilidade:

| # | Capability | Tools | Notas |
|---|---|---|---|
| 1 | `filesystem` | ler, escrever, listar, mover, copiar, apagar | em andamento |
| 2 | `shell` | executar com timeout, allowlist, stdout/stderr/exit | em andamento; risco alto, documentar |
| 3 | `http` | GET/POST, timeout, teto de resposta | em andamento |
| 4 | `python_runner` | executar script/trecho | **reusar** `kernel/runtime/python_runtime.py` — não inventar sandbox |
| 5 | `git` | status, diff, log, branch, commit | pré-requisito do Gate 2 (C-5) |
| 6 | `rag_search` | buscar no conhecimento | fachada sobre `memory/knowledge.py` + `vector_store.py` |
| 7 | `ingest` | URL/arquivo → extrair → chunk → LanceDB → arquivar em `data/` | entrega o B-6 |
| 8 | `documentos` | criar/editar DOCX, XLSX, CSV, PDF | entrega o B-5 (`python-docx`, `openpyxl`, `reportlab`) |
| 9 | `memory_writer` | gravar fato durável com dedup | cuidado: colide com `routers/memory.py`, definir dono único |
| 10 | `browser` | navegar, extrair, clicar | Playwright é pesado; adiar — `http` + extrator resolve a maior parte |
| 11 | `planner_utilities` | decompor, estimar | **despriorizar**: é prompt, não ferramenta; `goal_manager.py` já decompõe |

Cada uma: manifesto válido, `docs/README.md`, casos de `CapabilityHarness`,
permissões declaradas, falha limpa via erros do SDK (`EntradaInvalida`,
`PermissaoNaoDeclarada`, `Problema`). Molde canônico:
`capabilities/memoria_anotacoes/`.

---

## Ordem sugerida entre os planos

1. **Higiene** — suíte verde (14 failed/24 errors), `ruff` (132), `F821` em
   `packages/shared/settings.py:243`. Destrava C e dá confiança em tudo.
2. **Plano D 1–6** — sem mãos, o kernel só orquestra.
3. **Plano A D0–D2** — o visual novo em cima do app que já funciona.
4. **Plano D 7–8** + **Plano B** — voz e multimodal já com ferramentas reais.
5. **Plano A D3** — cockpit, junto dos endpoints de métrica.
6. **Plano C** — por último, como o próprio `ESTADO_DO_PROJETO.md` determina.

## Decisões pendentes do usuário
- Rotacionar o token do Cloudflare Tunnel exposto.
- Host: manter `:5173` (Vite dev) ou empacotar produção com nginx `:5174`.
- Manter tema claro (Industry nativo) além do escuro, ou assumir dark-only.
- `CommandPage` entra com placeholders ou espera o backend de métricas.
- Trocar o identifier do desk (`com.paulo.desk`) — orfana o estado local do
  WebView2 — ou manter.
