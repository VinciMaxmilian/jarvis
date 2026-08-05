# Jarvis — Estado Definitivo do Projeto (Agosto 2026)

Este documento unifica e substitui os relatórios anteriores de planejamento e execução (`plan.md`, `plan-execution.md`, `plan-scheme.md`, `HANDOFF.md`, `31-07-handoff.md`, `jarvis_report.md` e `plano_voz.md`). Ele reflete **o que realmente está implementado** no código hoje e quais são as próximas metas da arquitetura.

*Última sincronização com o código: 2026-08-04.*

## 1. O que já está PRONTO e FUNCIONANDO (Fase v1 Completa)

A fundação do Jarvis como Sistema Operacional Cognitivo (v1) está testada e em operação (cobertura de `pytest` e tipagem estrita com `mypy`):

### 🧠 Kernel e Orquestração
- **Chief AI e Executive Function:** Entende objetivos, decompõe em tarefas (Tasks) persistentes no Postgres, e retoma exatamente de onde parou após reinícios.
- **Capability Registry e Miss Determinístico:** Resolve as intenções perfeitamente. Se o Jarvis não sabe fazer algo, em vez de inventar, ele bloqueia a tarefa e levanta o evento `CapabilityGapDetected`.
- **Isolamento de Runtime:** As capabilities rodam em subprocessos separados. O enforcement de limites de disco (`filesystem`) e rede (`network`) foi testado em tempo real e bloqueia chamadas não autorizadas.
- **Capability SDK:** Completamente estruturado, testado e capaz de gerar manifestos limpos para a criação de novas capacidades.

### 🔀 Event Bus com Redis Streams
- **Implementado e em uso.** `packages/kernel/event_bus/redis_bus.py` (`RedisEventBus`) usa `XADD`, `XGROUP_CREATE`, `XREADGROUP` e `XACK` — ou seja, *consumer groups*, *acks* e re-entrega já operam.
- Selecionado em runtime pelo `settings.redis_url`: o orchestrator (`orchestrator/main.py`) sobe como consumidor `orchestrator_1` e a API (`apps/api/deps.py`) como `api_1`. Sem `redis_url`, ambos caem para o `InProcEventBus` como fallback.
- A migração de transporte que estava planejada para a v2 está, portanto, **concluída**.

### 💾 Memória de 5 Níveis
Todos os níveis da arquitetura operam em conjunto:
- **Short:** O contexto da sessão atual.
- **Working:** Checkpoints das tarefas em andamento.
- **Long:** Fatos duráveis do sistema e usuário.
- **Knowledge:** RAG incremental rápido construído no LanceDB.
- **Experience:** Extrato comportamental retirado de falhas anteriores.

### 🎙️ Voz — Pipeline STT → LLM → TTS (em produção hoje)
Este é o pipeline que **efetivamente roda**, não um plano descartado:
- **Backend:** `apps/api/routers/voice.py` — VAD com `webrtcvad`, transcrição com `faster-whisper` (modelo `tiny`, CPU/int8, `language="pt"`), geração de resposta via LM Studio local (cliente `openai` apontado para o endpoint local) e síntese com `edge_tts` (voz `pt-BR-AntonioNeural`).
- **Frontend Web:** `apps/web/src/hooks/useVoiceCall.ts` para a chamada de voz e `apps/web/src/hooks/useWakeWord.ts` (Porcupine) para a wake word.
- A arquitetura A2A com a Gemini Live API é **meta futura** (ver seção 2), não substituição já feita.

### 🖱️ Computer Use — ver a tela, clicar e digitar (desde 2026-08-05)
Fallback para quando nenhuma capability, MCP ou comando resolve o pedido. Ver
`plano_computer_use.md` para o desenho completo e o que ficou pendente.
- **Servidor MCP no host Windows:** `mcp/jarvis_windows_host/` (19 tools
  `desktop_*`), carregado pelo `mcp/main.py` e servido em `127.0.0.1:8765` — a
  porta que `packages/mcp/client_manager.py` já procurava. Sobe com
  `scripts/run_desktop_host.ps1`; o marcador `HOST_ONLY` impede o container de
  subir uma cópia cega dele.
- **UIA antes de pixel:** `desktop_inspecionar` lê a árvore de acessibilidade e
  devolve cada controle com um `id`; `desktop_clicar_elemento` clica por `id`.
  Screenshot com caixas numeradas (Set-of-Mark) é o fallback.
- **Encanamento que faltava:** `call_tool` descartava blocos de imagem do MCP em
  silêncio, e o laço do `ChiefAI` não injetava captura de tool result na rodada
  seguinte — os dois corrigidos, com o teto de 2 imagens por rodada.
- **Travas:** interruptor mestre `DESKTOP_CONTROL_ENABLED` (desligado por
  padrão, só o dono liga), sessão com prazo, failsafe do canto da tela, denylist
  persistente que o dono amplia conversando, recusa em campo de senha,
  confirmação para ação irreversível, rate limit e auditoria com screenshot.
- **Percepção continua ligada** com o controle desligado: o Jarvis enxerga a
  tela sem poder mover nada.

### ⚙️ Infraestrutura e Rede Segura
- **Banco e Fila:** Postgres e Redis operacionais subindo automáticos com migrations validadas via Docker Compose.
- **Zero Trust:** Cloudflare Tunnel configurado localmente. O Cloudflare Access filtra as requisições externamente e a API valida ativamente os JWTs assinados (validando o `aud` e domínio), fechando portas locais vulneráveis.
- **Scheduler e Automações:** Jobs agendados nativos efetuam a reindexação do conhecimento, limpeza de logs e o processo de backup e restore, sem a necessidade de scripts externos.

### 🖥️ Frontend (PWA Web)
- Interface empacotada no Vite + React com alto desempenho de renderização (React.memo usado pesadamente no Neural Map/Graphify).
- **Conexões WS Resilientes:** Vazamento de WebSockets do chat eliminado; reconexão imediata e sem abas zumbis.
- Histórico operante e limpo, integrado ao banco.

### 📱 Mobile (Expo / React Native) — cliente fino funcional
- Aplicativo Expo RN que consome o servidor; **não** roda inferência local.
- Autenticação Cloudflare Access via WebView, chat por WebSocket, e telas de Goals, Brain, History e Settings. Estado em `zustand`, credenciais em `expo-secure-store`.
- O documento `apps/mobile/plan_mobile.md` descreve uma visão futura (v3) diferente deste app — ver o bloco de status no topo daquele arquivo.

---

## 2. O que está EM ANDAMENTO ou PENDENTE (O Futuro — v2 e v3)

O foco do projeto mudou de "criar o motor" para "ensinar o motor a andar" e deixá-lo evoluir:

### 🛠️ Fase v2: Capabilities e Papéis
- **Capabilities Escritas à Mão (bloqueador principal):** hoje existem apenas duas em `capabilities/` — `exemplo_nas` e `memoria_anotacoes`. Nenhuma das capabilities úteis listadas na seção 4 foi escrita. *Passo obrigatório antes da automação.*
- **Papéis de Agentes Dinâmicos:** `packages/agents/` continua monolítico (`chief.py`, `executive.py`, `goal_manager.py`). Falta distribuir o "Chief AI" em perfis (Planner, Executor, Reviewer) carregando prompts especialistas de arquivos, permitindo o uso de ferramentas específicas para cada modelo (ex: o Planner não roda código).
- ~~Event Bus Definitivo (Redis Streams)~~ — **concluído**, ver seção 1.

### 🧬 Fase v3: Self-Evolution (A Grande Fronteira)
Nada implementado ainda — não existe código de geração de SPEC, aprovação ou instalação autônoma.
- **Criação Autônoma:** Quando ocorre um "miss" e o objetivo trava, o Jarvis irá elaborar uma SPEC.
- **Aprovação Dual:**
  1. *Mobile (Gate 1):* Uma notificação para aprovar a ideia superficialmente.
  2. *Desktop (Gate 2):* Aprovação detalhada da branch de código e visualização dos testes. O dry run obrigatório acontece na primeira execução da capability finalizada.

### 🎙️ Fase Sensorial: Voz com Gemini 3.1 Live API (meta futura)
Substituirá o pipeline STT → LLM → TTS descrito na seção 1, que segue sendo o que roda hoje.
- **Arquitetura A2A (Audio-to-Audio):** a conversa vira uma via única de baixa latência utilizando WebSocket com a `Live API` do Google. Jarvis ouvirá e responderá com voz nativa interpretando inclusive entonações e gerindo suas próprias interrupções.
- **Visão Computacional Multimodal:** Durante a conversação por voz, o agente será capaz de **enxergar as telas** do usuário, tendo um histórico de 5 minutos da tela.
  - Criar, editar, excluir e mover arquivos e pastas de forma orgânica.
  - Criar e editar diretamente documentos formatados como **DOCX, PDF, XLSX e CSV**.
- **Ingestão e Vetorização Contínua:** O agente ganhará uma ferramenta para receber arquivos ou **links** (ex: artigos completos da Wikipedia), vetorizá-los sob demanda e arquivá-los diretamente na pasta `data`, transformando a fonte em uma memória permanente e consultável.

### 📱 Fase Mobile (Companion App)
O app existe como cliente fino (seção 1). O que falta para ele cumprir o papel de comunicador do *Gate 1*:
- `expo-notifications` não está instalado — não há push.
- Não há tela de aprovação de SPEC.
- Não há endpoint no servidor para listar/aprovar SPECs pendentes.

---

## 3. Débitos Técnicos Residuais a Resolver

1. **Linter:** `ruff check .` acusa **132 erros** (não os "3 mínimos" registrados no handoff antigo). Predominam `E501` (73 linhas longas), `I001` (26 blocos de import desordenados) e `F401` (20 imports não usados) — 50 são auto-fixáveis. O caso relevante é `packages/shared/settings.py:243`, `F821 Undefined name Any` (o módulo importa apenas `Annotated` e `Literal` de `typing`); só não quebra em runtime porque o arquivo usa `from __future__ import annotations`.
2. **Ferramenta ausente:** `ruff` não está instalado no `venv/` do projeto — foi necessário rodar via `uvx ruff check .`. Adicionar ao ambiente de dev.
3. **Decisão pendente de Host (ação do usuário):** Alterar o target do Cloudflare Tunnel de `:5173` (Vite dev server aberto) para uma versão empacotada de produção com Nginx (`:5174`).
4. **Rotação de credencial (ação do usuário):** Rotacionar e reinstalar o token do Tunnel que foi exposto publicamente no chat em iterações antigas.

---

## 4. Planos Possíveis e Diretrizes de Foco

### 1. Capabilities (Prioridade Máxima)
Sem capabilities úteis, o Kernel apenas orquestra. Nenhuma das "mãos" abaixo existe hoje — o diretório `capabilities/` contém somente `exemplo_nas` e `memoria_anotacoes`. O esforço deve ser concentrado em construir:
- **Filesystem**
- **Python Runner**
- **Git**
- **Shell**
- **Browser**
- **HTTP**
- **RAG Search**
- **Memory Writer**
- **Planner Utilities**

### 2. Event Bus — concluído
`RedisEventBus` já entrega retries, consumer groups e múltiplos workers, abrindo espaço para distribuição futura de carga. O trabalho restante aqui é apenas operacional (observabilidade da fila, tratamento de mensagens pendentes/DLQ).

### 3. Papéis Especializados
Separar definitivamente as etapas cognitivas em perfis:
- **Planner**
- **Researcher**
- **Executor**
- **Reviewer**

Cada um operando de forma restrita, com: **prompt próprio**, **ferramentas próprias**, **temperatura própria** e **modelo próprio** (inclusive alternando entre local ou remoto). Esse fluxo fechado reduzirá drasticamente as alucinações.

### 4. Self Evolution e Autoconsciência
A auto-evolução só deve ser habilitada quando os pilares acima estiverem extremamente sólidos.

A arquitetura segmentada é muito mais segura do que permitir a geração automática e instalação cega. O fluxo a ser seguido é restrito a:
`Miss` ➔ `SPEC` ➔ `Aprovação Mobile` ➔ `Geração de Código` ➔ `Testes` ➔ `Branch` ➔ `Dry-Run` ➔ `Instalação`.

**Autoconsciência do Sistema:** O Agente/Jarvis deve ter ciência total do próprio sistema (como ele é formado, sua arquitetura técnica, seus protocolos e as ferramentas usadas para rodá-lo), para ser capaz de sustentar e evoluir o ambiente de forma coerente.

---

## 5. Divergências resolvidas em 2026-08-04

Auditoria do documento contra o código. O que estava errado e foi corrigido aqui:

| Divergência | Estado real |
|---|---|
| Event Bus Redis Streams listado como pendente da v2 | Já implementado em `packages/kernel/event_bus/redis_bus.py`, com consumer groups e ack, usado pelo orchestrator e pela API |
| Pipeline de voz STT → LLM → TTS descrito como "antigo"/abandonado | É o pipeline que roda hoje (`apps/api/routers/voice.py` + hooks do web). Gemini Live é meta futura |
| Capabilities úteis tratadas como "3 primeiras a manter ativas" | Nenhuma existe; apenas `exemplo_nas` e `memoria_anotacoes` |
| "3 erros mínimos" do linter | 132 erros no `ruff check .`, incluindo um `F821` em `packages/shared/settings.py` |
| Mobile descrito só como plano futuro | Cliente fino Expo RN já funcional (auth, chat WS, Goals, Brain, History, Settings); falta push/Gate 1 |
| `apps/mobile/plan_mobile.md` lido como plano corrente | É visão v3 (RunAnywhere SDK, LLM local), não implementada e incompatível com Expo Go |

Confirmados como **pendentes de fato**: capabilities úteis, papéis Planner/Executor/Reviewer, self-evolution (inexistente), rotação do token do Tunnel e decisão de host `:5173` vs nginx `:5174`.

*Nota: As ramificações de planejamento foram documentadas inteiramente. Ao realizar pesquisas e criar planos daqui para a frente, este documento ditará a realidade sobre o estado do projeto.*
