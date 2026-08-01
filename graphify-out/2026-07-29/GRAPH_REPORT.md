# Graph Report - jarvis  (2026-07-29)

## Corpus Check
- 79 files · ~40,094 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 719 nodes · 1300 edges · 48 communities (41 shown, 7 thin omitted)
- Extraction: 88% EXTRACTED · 12% INFERRED · 0% AMBIGUOUS · INFERRED: 150 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `f0d2aa4e`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- ToolSpec
- ports.py
- deps.py
- App.tsx
- contracts.py
- GoalManager
- dependencies
- compilerOptions
- PgGoalStore
- devDependencies
- compilerOptions
- ToolNotFound
- manifest.json
- tsconfig.json
- packages/__init__.py
- jarvis
- ShortTermMemory
- What You Must Do When Invoked
- Jarvis — Sistema Operacional Cognitivo Pessoal
- 1. Stack por camada
- Task
- SchedulerManager
- Goal
- chief.py
- history.py
- graphify reference: extra exports and benchmark
- Mapa do Repositório e Política de Documentação
- .claude/CLAUDE.md
- graphify reference: query, path, explain
- Jarvis
- caveman.md
- React + TypeScript + Vite
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- graphify reference: incremental update and cluster-only
- agents/README.md
- capabilities/README.md
- graphify reference: GitHub clone and cross-repo merge
- graphify reference: transcribe video and audio
- CLAUDE.md
- extraction-spec.md

## God Nodes (most connected - your core abstractions)
1. `ToolSpec` - 38 edges
2. `PgGoalStore` - 37 edges
3. `Goal` - 34 edges
4. `Task` - 34 edges
5. `GoalStatus` - 32 edges
6. `GoalManager` - 25 edges
7. `GoalStore` - 25 edges
8. `Message` - 24 edges
9. `TaskStatus` - 23 edges
10. `LLMProvider` - 20 edges

## Surprising Connections (you probably didn't know these)
- `PgGoalStore` --uses--> `ChatMessage`  [INFERRED]
  apps/api/db/repository.py → packages/shared/contracts.py
- `PgGoalStore` --uses--> `Conversation`  [INFERRED]
  apps/api/db/repository.py → packages/shared/contracts.py
- `PgGoalStore` --uses--> `Goal`  [INFERRED]
  apps/api/db/repository.py → packages/shared/contracts.py
- `PgGoalStore` --uses--> `GoalStatus`  [INFERRED]
  apps/api/db/repository.py → packages/shared/contracts.py
- `PgGoalStore` --uses--> `Task`  [INFERRED]
  apps/api/db/repository.py → packages/shared/contracts.py

## Import Cycles
- None detected.

## Communities (48 total, 7 thin omitted)

### Community 0 - "ToolSpec"
Cohesion: 0.09
Nodes (39): ChatCompletionMessageToolCall, AnthropicProvider, Any, Provider Anthropic — implementação concreta de LLMProvider. Usado pelo Chief AI…, Converte ToolSpec → formato Anthropic tool_use., Separa system prompt e converte Messages → formato Anthropic., LLMProvider concreta para API Anthropic. Suporta complete, stream e NÃO embed., _to_anthropic_messages() (+31 more)

### Community 1 - "ports.py"
Cohesion: 0.19
Nodes (8): Event, Fato ocorrido. Na v0 trafega por asyncio.Queue; na v2 por Redis Streams., EventBus, Protocol, Portas (Protocols) entre camadas. `packages/` define a porta; `apps/` fornece o…, Catálogo executável de tools. Na v0 são tools nativas; na v1 vira o Capability…, asyncio.Queue na v0; Redis Streams na v2. O contrato não muda., ToolExecutor

### Community 2 - "deps.py"
Cohesion: 0.05
Nodes (60): get_sync_url(), Alembic env.py — usa os ORM models de apps.api.db.models. O `target_metadata`…, Lê a URL do settings (async) e converte para sync., run_migrations_offline(), run_migrations_online(), dispose_engine(), get_engine(), get_session_factory() (+52 more)

### Community 3 - "App.tsx"
Cohesion: 0.06
Nodes (33): plugins, rules, react/only-export-components, react/rules-of-hooks, $schema, App(), PAGES, LayoutProps (+25 more)

### Community 4 - "contracts.py"
Cohesion: 0.06
Nodes (59): Base, ChatMessageRow, ConversationRow, GoalRow, SQLAlchemy ORM tables derivados dos contratos Pydantic. Regra: contracts.py é a…, Base declarativa. Alembic importa daqui., SystemSettingsRow, TaskRow (+51 more)

### Community 5 - "GoalManager"
Cohesion: 0.15
Nodes (11): main(), Orchestrator v0.5 — Executive Function + GoalManager. Instancia o loop de…, Boot: cria deps, resume goals, entra no loop., Executive, Executive Function — loop assíncrono que processa goals. Consome goals ativos,…, Loop de controle sobre goals ativos., Boot: resume interrupted goals, then enter poll loop., Enfileira goal para processamento. (+3 more)

### Community 6 - "dependencies"
Cohesion: 0.06
Nodes (32): dependencies, clsx, react, react-dom, react-markdown, react-router, rehype-katex, remark-gfm (+24 more)

### Community 7 - "compilerOptions"
Cohesion: 0.08
Nodes (23): compilerOptions, allowArbitraryExtensions, allowImportingTsExtensions, erasableSyntaxOnly, jsx, lib, module, moduleDetection (+15 more)

### Community 8 - "PgGoalStore"
Cohesion: 0.14
Nodes (23): PgGoalStore, AsyncSession, UUID, GoalStore backed by Postgres., create_goal(), CreateGoalRequest, execute_goal(), get_goal() (+15 more)

### Community 9 - "devDependencies"
Cohesion: 0.09
Nodes (23): devDependencies, autoprefixer, oxlint, postcss, tailwindcss, @types/node, @types/react, @types/react-dom (+15 more)

### Community 10 - "compilerOptions"
Cohesion: 0.10
Nodes (19): compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, lib, module, moduleDetection, noEmit, noFallthroughCasesInSwitch (+11 more)

### Community 11 - "ToolNotFound"
Cohesion: 0.21
Nodes (6): Tavily web search — primeira tool real da v0. Implementa ToolExecutor…, ToolExecutor com a tool `web_search` (Tavily API)., TavilyToolExecutor, Exception, Miss no catálogo de tools. Na v1 vira `CapabilityGapDetected`., ToolNotFound

### Community 12 - "manifest.json"
Cohesion: 0.20
Nodes (9): background_color, description, display, icons, name, orientation, short_name, start_url (+1 more)

### Community 22 - "ShortTermMemory"
Cohesion: 0.08
Nodes (17): Memory management package., LongTermMemory, Any, Long Term Memory. Stores and retrieves durable facts using LanceDB (vector…, Interface for long-term memory using vector search., Connects to the LanceDB instance., Stores a fact in the long-term memory., # TODO: Implement LanceDB table insert with embeddings (+9 more)

### Community 23 - "What You Must Do When Invoked"
Cohesion: 0.07
Nodes (26): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+18 more)

### Community 24 - "Jarvis — Sistema Operacional Cognitivo Pessoal"
Cohesion: 0.07
Nodes (26): 10. Memória, 11. Eventos, scheduler e agentes contínuos, 12. Modelos, 13. Cliente PWA, 14. Roadmap, 15. Decisões resolvidas, 16. Fora de escopo, 1. Objetivo (+18 more)

### Community 25 - "1. Stack por camada"
Cohesion: 0.09
Nodes (22): 1.1 Frontend web (PWA), 1.2 Backend, 1.3 LLM e inferência, 1.4 Dados, 1.5 RAG e parsing de documentos, 1.6 Busca web, controle do computador, mídia, 1.7 Observabilidade, 1.8 Containers e qualidade (+14 more)

### Community 26 - "Task"
Cohesion: 0.13
Nodes (8): UUID, Goal Manager — orquestra goals → tasks com checkpoint. Responsabilidades: -…, Executa próxima task pendente. Retorna task executada ou None., Processa goal completo: executa tasks até acabar ou falhar., Resume após restart: busca goals ACTIVE e retoma processamento., Usa LLM para decompor goal em tasks., Passo executável de um Goal. Executado por uma capability, nunca pelo Chief AI., Task

### Community 27 - "SchedulerManager"
Cohesion: 0.12
Nodes (10): Scheduler jobs. Handles periodic background tasks for the Jarvis OS using…, Manages periodic jobs for the system., Starts the APScheduler and registers jobs., Backup Postgres and LanceDB., # TODO: Implement pg_dump and LanceDB snapshot, Clean up old logs and expired short-term memory., # TODO: Implement cleanup logic, Incremental re-indexing of the knowledge base. (+2 more)

### Community 28 - "Goal"
Cohesion: 0.18
Nodes (6): Goal, Unidade de trabalho do sistema. Sobrevive ao fechamento da janela., GoalStore, UUID, Persistência de objetivos e tarefas. Implementado em `apps/api/db`., Primeira tarefa `pending` cujas dependências já estão `done`.

### Community 29 - "chief.py"
Cohesion: 0.19
Nodes (10): ChiefAI, UUID, Chief AI — núcleo mínimo da v0. Recebe mensagem do usuário, envia para LLM com…, Chief AI v0: LLM loop com tool calling., Processa mensagem do usuário. Yield StreamChunks para streaming., ChatMessage, Turno de conversa persistido. A `Message` de `packages.llm` é o formato de wire., ConversationStore (+2 more)

### Community 30 - "history.py"
Cohesion: 0.27
Nodes (12): ChatPreview, get_chats(), get_stats(), ModelStats, AsyncSession, BaseModel, get, Router para histórico de chats e estatísticas de uso. (+4 more)

### Community 31 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 32 - "Mapa do Repositório e Política de Documentação"
Cohesion: 0.25
Nodes (7): Documentação sob demanda, Documentos permitidos, Estrutura do monorepo, Git, Layout de uma capability em disco, Mapa do Repositório e Política de Documentação, Sincronização casa ↔ trabalho

### Community 33 - ".claude/CLAUDE.md"
Cohesion: 0.33
Nodes (5): Auto-Clarity, graphify, Intensity, Persistence, Rules

### Community 34 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 35 - "Jarvis"
Cohesion: 0.33
Nodes (5): Frontend em dev, Jarvis, Sincronização casa ↔ trabalho, Subir o sistema, Testes

### Community 36 - "caveman.md"
Cohesion: 0.40
Nodes (4): Auto-Clarity, Intensity, Persistence, Rules

### Community 37 - "React + TypeScript + Vite"
Cohesion: 0.50
Nodes (3): Expanding the Oxlint configuration, React Compiler, React + TypeScript + Vite

### Community 38 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 39 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 40 - "graphify reference: incremental update and cluster-only"
Cohesion: 0.50
Nodes (3): For --cluster-only, For --update (incremental re-extraction), graphify reference: incremental update and cluster-only

### Community 41 - "agents/README.md"
Cohesion: 0.50
Nodes (3): ... documentação inicial do módulo de agentes ..., Este pacote deve conter a lógica dos agentes (Chief AI, Planner, etc.), README para o pacote de Agentes

### Community 42 - "capabilities/README.md"
Cohesion: 0.50
Nodes (3): ... documentação inicial do módulo de capacidades ..., Documentação sobre como as capacidades devem ser definidas (manifest.yaml, etc.), README para o pacote de Capacidades (Capability SDK)

## Knowledge Gaps
- **205 isolated node(s):** `$schema`, `typescript`, `oxc`, `react/rules-of-hooks`, `warn` (+200 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ToolSpec` connect `ToolSpec` to `ports.py`, `contracts.py`, `GoalManager`, `ToolNotFound`, `Task`, `Goal`, `chief.py`?**
  _High betweenness centrality (0.028) - this node is a cross-community bridge._
- **Why does `Task` connect `Task` to `ports.py`, `contracts.py`, `GoalManager`, `PgGoalStore`, `ToolNotFound`, `Goal`, `chief.py`?**
  _High betweenness centrality (0.018) - this node is a cross-community bridge._
- **Why does `Goal` connect `Goal` to `ports.py`, `contracts.py`, `GoalManager`, `PgGoalStore`, `ToolNotFound`, `Task`, `chief.py`?**
  _High betweenness centrality (0.016) - this node is a cross-community bridge._
- **Are the 18 inferred relationships involving `ToolSpec` (e.g. with `GoalManager` and `TavilyToolExecutor`) actually correct?**
  _`ToolSpec` has 18 INFERRED edges - model-reasoned connections that need verification._
- **Are the 12 inferred relationships involving `PgGoalStore` (e.g. with `ChatMessageRow` and `ConversationRow`) actually correct?**
  _`PgGoalStore` has 12 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `Goal` (e.g. with `PgConversationStore` and `PgGoalStore`) actually correct?**
  _`Goal` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `Task` (e.g. with `PgConversationStore` and `PgGoalStore`) actually correct?**
  _`Task` has 10 INFERRED edges - model-reasoned connections that need verification._