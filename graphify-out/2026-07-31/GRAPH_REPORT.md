# Graph Report - jarvis  (2026-07-30)

## Corpus Check
- 114 files · ~187,451 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1533 nodes · 3133 edges · 103 communities (81 shown, 22 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 242 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `14f42a11`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- CapabilityRegistry
- GeminiProvider
- OllamaProvider
- ToolSpec
- App.tsx
- test_contracts.py
- deps.py
- RSAPrivateKey
- FakeLLMProvider
- test_architecture.py
- ChatMessage
- ShortTermMemory
- Goal
- test_cf_access.py
- InMemoryGoalStore
- What You Must Do When Invoked
- Jarvis — Sistema Operacional Cognitivo Pessoal
- test_fixtures.py
- TestClient
- FakeJwksEndpoint
- resolve_profile_model
- GoalStatus
- compilerOptions
- test_providers.py
- test_model_profiles.py
- 1. Stack por camada
- routers/settings.py
- contracts.py
- cf_access.py
- What You Must Do When Invoked
- compilerOptions
- dependencies
- devDependencies
- Jarvis — Plano de execução v1 → v3
- SchedulerManager
- CloudflareAccessMiddleware
- TavilyToolExecutor
- history.py
- AccessTokenError
- api/main.py
- Runbook da infraestrutura
- conftest.py
- package.json
- manifest.json
- NeuralEngine
- Message
- Task
- graphify reference: extra exports and benchmark
- .__init__
- env.py
- Mapa do Repositório e Política de Documentação
- app_real
- .claude/CLAUDE.md
- graphify reference: query, path, explain
- README.md
- caveman.md
- React + TypeScript + Vite
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- graphify reference: incremental update and cluster-only
- agents/README.md
- capabilities/README.md
- tsconfig.json
- graphify reference: GitHub clone and cross-repo merge
- graphify reference: transcribe video and audio
- resolve_model
- @tanstack/react-query
- oxlint
- @vitejs/plugin-react
- CLAUDE.md
- extraction-spec.md
- packages/__init__.py
- tests/__init__.py
- unit/__init__.py
- jarvis
- Handoff — trabalho interrompido no meio (2026-07-30)
- FileExplorer.tsx
- _FakeSession
- graphify reference: extra exports and benchmark
- plugins
- Layout.tsx
- Engine.ts
- HistoryPage.tsx
- GoalManager
- graphify reference: query, path, explain
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- graphify reference: incremental update and cluster-only
- graphify reference: GitHub clone and cross-repo merge
- graphify reference: transcribe video and audio
- AGENTS.md
- .agents/skills/graphify/references/extraction-spec.md
- clsx
- .__init__
- .pending

## God Nodes (most connected - your core abstractions)
1. `Goal` - 63 edges
2. `ToolSpec` - 62 edges
3. `Task` - 59 edges
4. `InMemoryGoalStore` - 58 edges
5. `Message` - 52 edges
6. `FakeLLMProvider` - 47 edges
7. `GoalStatus` - 44 edges
8. `PgGoalStore` - 36 edges
9. `Completion` - 36 edges
10. `Settings` - 35 edges

## Surprising Connections (you probably didn't know these)
- `FakeJwksEndpoint` --uses--> `AccessTokenError`  [INFERRED]
  tests/unit/test_cf_access.py → apps/api/cf_access.py
- `FakeJwksEndpoint` --uses--> `CloudflareAccessVerifier`  [INFERRED]
  tests/unit/test_cf_access.py → apps/api/cf_access.py
- `FakeJwksEndpoint` --uses--> `CloudflareAccessMiddleware`  [INFERRED]
  tests/unit/test_cf_access.py → apps/api/cf_access.py
- `SystemSettingsRow` --uses--> `GoalStatus`  [INFERRED]
  apps/api/db/models.py → packages/shared/contracts.py
- `SystemSettingsRow` --uses--> `MessageRole`  [INFERRED]
  apps/api/db/models.py → packages/shared/contracts.py

## Import Cycles
- None detected.

## Communities (103 total, 22 thin omitted)

### Community 0 - "CapabilityRegistry"
Cohesion: 0.07
Nodes (53): CapabilityGapDetected, InvalidCapabilityStateError, ManifestLoadError, Exception, Exceptions for Capability Registry., Raised when resolve() misses. Triggers auto-evolution., Raised when a manifest.yaml cannot be loaded or is invalid., Raised when a capability is not in the expected state for an operation. (+45 more)

### Community 1 - "GeminiProvider"
Cohesion: 0.08
Nodes (38): _as_dict(), _as_int(), _as_list(), _as_str(), _attach_images(), _bare_model(), _conforms_to_protocol(), _error_detail() (+30 more)

### Community 2 - "OllamaProvider"
Cohesion: 0.08
Nodes (33): _as_dict(), _as_int(), _as_str(), _attach_images(), _conforms_to_protocol(), _error_detail(), _looks_like_embedding_unsupported(), OllamaProvider (+25 more)

### Community 3 - "ToolSpec"
Cohesion: 0.09
Nodes (38): ChatCompletionMessageToolCall, AnthropicProvider, Any, Provider Anthropic — implementação concreta de LLMProvider. Usado pelo Chief AI…, Converte ToolSpec → formato Anthropic tool_use., Separa system prompt e converte Messages → formato Anthropic., LLMProvider concreta para API Anthropic. Suporta complete, stream e NÃO embed., _to_anthropic_messages() (+30 more)

### Community 4 - "App.tsx"
Cohesion: 0.18
Nodes (12): App(), PAGES, ChatMessage, ChatPage(), useChat(), WsChunk, GUARDRAILS, ProviderOption (+4 more)

### Community 5 - "test_contracts.py"
Cohesion: 0.08
Nodes (31): CapabilityManifest, CapabilityStatus, Serializa exatamente o `manifest.yaml` no disco da capability., O registry só carrega capability `active` (regra da seção 6 de plan.md)., _manifest(), parametrize, Invariantes dos contratos de `packages/shared/contracts.py`. Os contratos são a…, `can_retry` fora de FAILED reagendaria task em andamento. (+23 more)

### Community 6 - "deps.py"
Cohesion: 0.06
Nodes (31): _build_anthropic(), _build_gemini(), _build_lmstudio(), _build_ollama(), _build_openai_compatible(), effective_provider_and_model(), FastAPI Depends wiring. Todas as dependências do sistema passam por aqui.…, Entrada separada de `local` de propósito: o Ollama é servido pela API nativa… (+23 more)

### Community 7 - "RSAPrivateKey"
Cohesion: 0.13
Nodes (28): RSAPrivateKey, _generate_key(), _hdr(), _jwk(), jwks(), key_alheia(), keypair(), make_token() (+20 more)

### Community 8 - "FakeLLMProvider"
Cohesion: 0.17
Nodes (25): FakeLLMProvider, `ToolExecutor` que registra chamadas em vez de executar. O Chief AI e o…, `LLMProvider` roteirizado. Sem rede, sem aleatoriedade. `complete()` consome a…, RecordingToolExecutor, _goal_meio_caminho(), _montar(), Resume após restart (`plan.md` §5). O critério é o do checkpoint: matar o…, Decompor de novo duplicaria a fila a cada restart. (+17 more)

### Community 9 - "test_architecture.py"
Cohesion: 0.13
Nodes (29): arquivos_python(), coletar_imports(), ImportRef, nomes_importados(), _pacote_do_arquivo(), _proibido_para_o_chief(), parametrize, Path (+21 more)

### Community 10 - "ChatMessage"
Cohesion: 0.10
Nodes (20): ChiefAI, UUID, Chief AI — núcleo mínimo da v0. Recebe mensagem do usuário, envia para LLM com…, Chief AI v0: LLM loop com tool calling., Processa mensagem do usuário. Yield StreamChunks para streaming., Tavily web search — primeira tool real da v0. Implementa ToolExecutor…, ChatMessage, Turno de conversa persistido. A `Message` de `packages.llm` é o formato de wire. (+12 more)

### Community 11 - "ShortTermMemory"
Cohesion: 0.08
Nodes (17): Memory management package., LongTermMemory, Any, Long Term Memory. Stores and retrieves durable facts using LanceDB (vector…, Interface for long-term memory using vector search., Connects to the LanceDB instance., Stores a fact in the long-term memory., # TODO: Implement LanceDB table insert with embeddings (+9 more)

### Community 12 - "Goal"
Cohesion: 0.12
Nodes (33): PgGoalStore, GoalStore backed by Postgres., get_chief_ai(), get_conversation_store(), get_db(), get_goal_store(), get_llm_provider(), get_tool_executor() (+25 more)

### Community 13 - "test_cf_access.py"
Cohesion: 0.13
Nodes (25): extract_token(), Token do header do Access; na falta dele, do cookie `CF_Authorization`., Any, parametrize, Gate do Cloudflare Access: verificação do JWT na origem. A suíte assina os…, O default não pode quebrar `127.0.0.1:8000`, onde não existe Access e portanto…, Quem preencheu as três variáveis já montou o Access. Exigir um segundo passo…, O caso que este default existe para impedir: a origem de pé, publicada, sem… (+17 more)

### Community 14 - "InMemoryGoalStore"
Cohesion: 0.12
Nodes (25): InMemoryGoalStore, `GoalStore` em dicionário, com a mesma semântica do `PgGoalStore`. Guarda e…, _concluir(), _goal_com_cadeia(), UUID, Contrato de `GoalStore.next_pending_task`. A porta documenta uma frase:…, Sem dependência, a fila é serial e estável — não arbitrária., Dependência órfã bloqueia em vez de rodar sem o pré-requisito. (+17 more)

### Community 15 - "What You Must Do When Invoked"
Cohesion: 0.07
Nodes (26): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+18 more)

### Community 16 - "Jarvis — Sistema Operacional Cognitivo Pessoal"
Cohesion: 0.07
Nodes (26): 10. Memória, 11. Eventos, scheduler e agentes contínuos, 12. Modelos, 13. Cliente PWA, 14. Roadmap, 15. Decisões resolvidas, 16. Fora de escopo, 1. Objetivo (+18 more)

### Community 17 - "test_fixtures.py"
Cohesion: 0.08
Nodes (23): cosine(), InMemoryEventBus, Vetor unitário derivado de SHA-256 do texto. `hash()` embutido é semeado por…, Similaridade de cosseno. Usada para afirmar ranking de `embed()`., `EventBus` que grava tudo em `published`. Evento é o único canal entre módulos…, stable_embedding(), Os dublês são testados como código de produção. Dublê que sai da porta…, A consulta idêntica ao documento é sempre o primeiro colocado. (+15 more)

### Community 18 - "TestClient"
Cohesion: 0.12
Nodes (22): TestClient, client(), FastAPI, O HEALTHCHECK do Dockerfile bate aqui de dentro do container e não tem como…, `alg: none` é o ataque de manual: payload legítimo, assinatura vazia., Confusão de algoritmo: o atacante assina em HMAC esperando que a chave pública…, Rota que ninguém registrou à mão também é coberta — é a razão de o gate ser…, `BaseHTTPMiddleware` só é chamado para scope `http`; o canal principal do… (+14 more)

### Community 19 - "FakeJwksEndpoint"
Cohesion: 0.12
Nodes (21): JwksCache, Chaves públicas do Access, em memória, indexadas por `kid`. Duas pressões…, MockTransport, FakeJwksEndpoint, Request, Response, `/cdn-cgi/access/certs` em memória, com contador de acessos. O contador é o que…, Cache frio com 20 requisições simultâneas: o lock tem de deixar UMA passar. Sem… (+13 more)

### Community 20 - "resolve_profile_model"
Cohesion: 0.08
Nodes (38): build_llm_provider_for_profile(), profile_override(), Collection, Override do dono para (provider, perfil), ou "" se não declarado. `getattr`…, Perfil → modelo para o provider dado. Não vai à rede e não levanta. `served` é…, Provider já apontado para o modelo do perfil. Nunca levanta por perfil. É a…, resolve_profile_model(), parametrize (+30 more)

### Community 21 - "GoalStatus"
Cohesion: 0.18
Nodes (17): Base, ChatMessageRow, ConversationRow, GoalRow, SQLAlchemy ORM tables derivados dos contratos Pydantic. Regra: contracts.py é a…, Base declarativa. Alembic importa daqui., TaskRow, PgConversationStore (+9 more)

### Community 22 - "compilerOptions"
Cohesion: 0.08
Nodes (23): compilerOptions, allowArbitraryExtensions, allowImportingTsExtensions, erasableSyntaxOnly, jsx, lib, module, moduleDetection (+15 more)

### Community 23 - "test_providers.py"
Cohesion: 0.12
Nodes (25): build_llm_provider(), provider_default_model(), Providers atendíveis agora, em ordem de preferência (não alfabética). Fonte…, Modelo default de um provider, ou "" se o provider não existe., Resolve o provider pelo mapa. Desconhecido falha nomeando os válidos. Fora do…, valid_provider_ids(), A ponta solta que faria tudo acima ser teoria: a fábrica do `deps.py` tem de…, test_fabrica_do_lmstudio_aponta_embed_para_o_modelo_de_embedding() (+17 more)

### Community 24 - "test_model_profiles.py"
Cohesion: 0.12
Nodes (24): _mock_provider(), Request, Response, Perfil de tarefa → modelo, e o `embed()` do provider OpenAI-compatible. O que…, Provider com transporte falso. Devolve também as requisições vistas: o que…, Resposta com a MESMA forma medida no LM Studio, inclusive `index`., O bug que isto trava: `embed()` indo para o modelo de conversa. No LM Studio os…, Alguns backends respondem 400 a `input: []`; um erro fantasma por lista vazia é… (+16 more)

### Community 25 - "1. Stack por camada"
Cohesion: 0.09
Nodes (22): 1.1 Frontend web (PWA), 1.2 Backend, 1.3 LLM e inferência, 1.4 Dados, 1.5 RAG e parsing de documentos, 1.6 Busca web, controle do computador, mídia, 1.7 Observabilidade, 1.8 Containers e qualidade (+14 more)

### Community 26 - "routers/settings.py"
Cohesion: 0.15
Nodes (24): SystemSettingsRow, get_settings(), list_profiles(), list_providers(), ProfileAssignment, ProfileCatalog, ProviderCatalog, ProviderOption (+16 more)

### Community 27 - "contracts.py"
Cohesion: 0.17
Nodes (16): datetime, Capability, CapabilityPermissions, Conversation, Event, EventType, FileAccessRule, BaseModel (+8 more)

### Community 28 - "cf_access.py"
Cohesion: 0.15
Nodes (12): CloudflareAccessVerifier, _http_transport(), install_cloudflare_access(), FastAPI, Verificação, na origem, da asserção assinada pelo Cloudflare Access. O Access…, Verifica assinatura, `aud`, `iss`, validade e identidade do dono., Instala o gate se ele estiver ligado. Devolve se instalou. A decisão de ligar…, Transporte do cliente que busca o JWKS. `None` = pilha real do httpx. É função… (+4 more)

### Community 29 - "What You Must Do When Invoked"
Cohesion: 0.07
Nodes (26): For /graphify add and --watch, For /graphify query, For the commit hook and native AGENTS.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+18 more)

### Community 30 - "compilerOptions"
Cohesion: 0.10
Nodes (19): compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, lib, module, moduleDetection, noEmit, noFallthroughCasesInSwitch (+11 more)

### Community 31 - "dependencies"
Cohesion: 0.11
Nodes (19): dependencies, react, react-dom, react-markdown, react-router, rehype-katex, remark-gfm, remark-math (+11 more)

### Community 32 - "devDependencies"
Cohesion: 0.11
Nodes (19): devDependencies, autoprefixer, postcss, tailwindcss, @types/node, @types/react, @types/react-dom, typescript (+11 more)

### Community 33 - "Jarvis — Plano de execução v1 → v3"
Cohesion: 0.09
Nodes (21): 1. Estado real hoje (auditado, não declarado), 2. Triagem das sugestões estruturais, 2b. Triagem da segunda rodada de sugestões (2026-07-30), 3. v1 — Sistema utilizável de verdade, 4. v2 — Capabilities escritas à mão, 5. v3 — Self-evolution, 6. Ordem e dependências, 7. Invariantes (+13 more)

### Community 34 - "SchedulerManager"
Cohesion: 0.12
Nodes (10): Scheduler jobs. Handles periodic background tasks for the Jarvis OS using…, Manages periodic jobs for the system., Starts the APScheduler and registers jobs., Backup Postgres and LanceDB., # TODO: Implement pg_dump and LanceDB snapshot, Clean up old logs and expired short-term memory., # TODO: Implement cleanup logic, Incremental re-indexing of the knowledge base. (+2 more)

### Community 35 - "CloudflareAccessMiddleware"
Cohesion: 0.48
Nodes (5): CloudflareAccessMiddleware, Gate ASGI puro: nega por default, libera `/health` por exceção. **Por que…, Receive, Scope, Send

### Community 36 - "TavilyToolExecutor"
Cohesion: 0.28
Nodes (4): _as_int(), Converte argumento de tool call em int, caindo no default se não der. Os…, ToolExecutor com a tool `web_search` (Tavily API)., TavilyToolExecutor

### Community 37 - "history.py"
Cohesion: 0.27
Nodes (12): ChatPreview, get_chats(), get_stats(), ModelStats, AsyncSession, BaseModel, get, Router para histórico de chats e estatísticas de uso. (+4 more)

### Community 38 - "AccessTokenError"
Cohesion: 0.23
Nodes (8): AccessTokenError, Any, Exception, Chave pública do `kid`, buscando o JWKS só quando necessário., Chave em cache, se o cache ainda está dentro do TTL., Rebusca o JWKS, respeitando o cooldown. Chamado sob `self._lock`., Claims do token, ou `AccessTokenError` nomeando o que reprovou., Motivo técnico da recusa. Vai para o log, nunca para a resposta.

### Community 39 - "api/main.py"
Cohesion: 0.09
Nodes (27): dispose_engine(), get_engine(), get_session_factory(), AsyncSession, Async SQLAlchemy engine e session factory. Única fonte de `AsyncSession` no…, _configure_logging(), create_app(), lifespan() (+19 more)

### Community 40 - "Runbook da infraestrutura"
Cohesion: 0.06
Nodes (33): 1. Pré-requisito único: o `.env`, 2. Subir tudo, 3. Migrations (Alembic), 4. Inferência: fora do Docker, de propósito, 5. Portas expostas, 6. Derrubar, 7. Quando algo não sobe, 8.1 A decisão: conector como serviço do Windows, no host (+25 more)

### Community 41 - "conftest.py"
Cohesion: 0.12
Nodes (17): conversation_store(), event_bus(), fake_llm(), goal_id(), goal_store(), InMemoryConversationStore, make_tool_spec(), ChatMessage (+9 more)

### Community 42 - "package.json"
Cohesion: 0.20
Nodes (9): name, private, scripts, build, dev, lint, preview, type (+1 more)

### Community 43 - "manifest.json"
Cohesion: 0.20
Nodes (9): background_color, description, display, icons, name, orientation, short_name, start_url (+1 more)

### Community 45 - "Message"
Cohesion: 0.18
Nodes (7): Completion, Message, Formato de wire para o provider. Persistência de conversa usa `ChatMessage`., Any, Enfileira uma `Completion` montada à mão (tokens, finish_reason)., Enfileira uma resposta de texto puro. Retorna `self` para encadear., Enfileira uma resposta que pede execução de tool.

### Community 46 - "Task"
Cohesion: 0.15
Nodes (7): Passo executável de um Goal. Executado por uma capability, nunca pelo Chief AI., Task, GoalStore, UUID, Persistência de objetivos e tarefas. Implementado em `apps/api/db`., Primeira tarefa `pending` cujas dependências já estão `done`., test_tasks_de_outro_goal_nao_vazam()

### Community 47 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 49 - "env.py"
Cohesion: 0.36
Nodes (7): get_sync_url(), Alembic env.py — usa os ORM models de apps.api.db.models. O `target_metadata`…, Esconde a senha de um DSN antes de ele ir para log. O DSN carrega credencial.…, Lê a URL do settings (async) e converte para sync., _redact(), run_migrations_offline(), run_migrations_online()

### Community 50 - "Mapa do Repositório e Política de Documentação"
Cohesion: 0.25
Nodes (7): Documentação sob demanda, Documentos permitidos, Estrutura do monorepo, Git, Layout de uma capability em disco, Mapa do Repositório e Política de Documentação, Sincronização casa ↔ trabalho

### Community 51 - "app_real"
Cohesion: 0.40
Nodes (5): app_real(), MonkeyPatch, Variável CF_* exportada na máquina não pode mudar o resultado do teste., `create_app()` de verdade, com Access ligado e JWKS servido em memória. O app…, _sem_cf_no_ambiente()

### Community 52 - ".claude/CLAUDE.md"
Cohesion: 0.33
Nodes (5): Auto-Clarity, graphify, Intensity, Persistence, Rules

### Community 53 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 55 - "caveman.md"
Cohesion: 0.40
Nodes (4): Auto-Clarity, Intensity, Persistence, Rules

### Community 56 - "React + TypeScript + Vite"
Cohesion: 0.50
Nodes (3): Expanding the Oxlint configuration, React Compiler, React + TypeScript + Vite

### Community 57 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 58 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 59 - "graphify reference: incremental update and cluster-only"
Cohesion: 0.50
Nodes (3): For --cluster-only, For --update (incremental re-extraction), graphify reference: incremental update and cluster-only

### Community 60 - "agents/README.md"
Cohesion: 0.50
Nodes (3): ... documentação inicial do módulo de agentes ..., Este pacote deve conter a lógica dos agentes (Chief AI, Planner, etc.), README para o pacote de Agentes

### Community 61 - "capabilities/README.md"
Cohesion: 0.50
Nodes (3): ... documentação inicial do módulo de capacidades ..., Documentação sobre como as capacidades devem ser definidas (manifest.yaml, etc.), README para o pacote de Capacidades (Capability SDK)

### Community 67 - "resolve_model"
Cohesion: 0.18
Nodes (13): _log(), ModelResolution, profile_env_var(), BaseModel, Collection, Perfil de tarefa → modelo. Um modelo por tipo de trabalho, não um por sistema.…, O modelo escolhido para um perfil, com a razão da escolha. `reason` não é…, Nome da variável de ambiente que sobrescreve um perfil. Fonte única: `Settings`… (+5 more)

### Community 81 - "Handoff — trabalho interrompido no meio (2026-07-30)"
Cohesion: 0.12
Nodes (15): 0. Estado da árvore, 1. Como rodar qualquer coisa, 2. Placar agora, 3. Agente A — Cloudflare Tunnel (infraestrutura), 4. Agente B — validação do JWT do Access na origem, 5. Ordem sugerida para retomar, 6. O que o dono precisa fazer no dashboard, Entregue e no disco (+7 more)

### Community 83 - "FileExplorer.tsx"
Cohesion: 0.29
Nodes (6): GraphNode, FileExplorer(), FileExplorerProps, TreeNode, NeuralMap(), BrainPage()

### Community 84 - "_FakeSession"
Cohesion: 0.18
Nodes (9): _async(), _FakeResult, _FakeSession, Any, MonkeyPatch, Só o suficiente para `effective_provider_and_model`. Sem Postgres: o assunto do…, LM Studio desligado não pode virar 500: o dono consulta esta tela justamente…, test_endpoint_de_perfis_mostra_quem_serve_o_que() (+1 more)

### Community 85 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 86 - "plugins"
Cohesion: 0.22
Nodes (8): plugins, rules, react/only-export-components, react/rules-of-hooks, $schema, oxc, typescript, warn

### Community 87 - "Layout.tsx"
Cohesion: 0.28
Nodes (5): LayoutProps, MOBILE_TABS, PageId, NAV_ITEMS, SidebarProps

### Community 88 - "Engine.ts"
Cohesion: 0.28
Nodes (7): col(), GraphLink, hex2rgb(), LOBES, PAL, RGB, rgba()

### Community 89 - "HistoryPage.tsx"
Cohesion: 0.22
Nodes (8): ChatPreview, GoalSummary, HistoryPage(), ModelStats, StatsResponse, STATUS_MAP, TaskSummary, ToolUsage

### Community 90 - "GoalManager"
Cohesion: 0.10
Nodes (17): main(), Orchestrator v0.5 — Executive Function + GoalManager. Instancia o loop de…, Boot: cria deps, resume goals, entra no loop., Executive, Executive Function — loop assíncrono que processa goals. Consome goals ativos,…, Loop de controle sobre goals ativos., Boot: resume interrupted goals, then enter poll loop., Enfileira goal para processamento. (+9 more)

### Community 91 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 92 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 93 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 94 - "graphify reference: incremental update and cluster-only"
Cohesion: 0.50
Nodes (3): For --cluster-only, For --update (incremental re-extraction), graphify reference: incremental update and cluster-only

## Knowledge Gaps
- **302 isolated node(s):** `$schema`, `typescript`, `oxc`, `react/rules-of-hooks`, `warn` (+297 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **22 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ToolSpec` connect `ToolSpec` to `GeminiProvider`, `OllamaProvider`, `TavilyToolExecutor`, `deps.py`, `FakeLLMProvider`, `conftest.py`, `ChatMessage`, `Message`, `Task`, `InMemoryGoalStore`, `test_fixtures.py`, `contracts.py`?**
  _High betweenness centrality (0.042) - this node is a cross-community bridge._
- **Why does `Settings` connect `deps.py` to `test_cf_access.py`, `resolve_profile_model`, `test_providers.py`, `test_model_profiles.py`, `contracts.py`, `cf_access.py`?**
  _High betweenness centrality (0.031) - this node is a cross-community bridge._
- **Why does `get_settings()` connect `deps.py` to `api/main.py`, `Goal`, `test_cf_access.py`, `env.py`, `test_providers.py`, `routers/settings.py`, `contracts.py`, `cf_access.py`?**
  _High betweenness centrality (0.023) - this node is a cross-community bridge._
- **Are the 15 inferred relationships involving `Goal` (e.g. with `PgConversationStore` and `PgGoalStore`) actually correct?**
  _`Goal` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `ToolSpec` (e.g. with `TavilyToolExecutor` and `AnthropicProvider`) actually correct?**
  _`ToolSpec` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `Task` (e.g. with `PgConversationStore` and `PgGoalStore`) actually correct?**
  _`Task` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `InMemoryGoalStore` (e.g. with `Completion` and `Message`) actually correct?**
  _`InMemoryGoalStore` has 11 INFERRED edges - model-reasoned connections that need verification._