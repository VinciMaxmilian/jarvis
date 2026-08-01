# Graph Report - jarvis  (2026-08-01)

## Corpus Check
- 213 files · ~286,255 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 3333 nodes · 7368 edges · 177 communities (150 shown, 27 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 446 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `7f4ff5fc`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- test_registry.py
- GeminiProvider
- ollama_provider.py
- deps.py
- src/App.tsx
- CapabilityManifest
- Settings
- TestClient
- InMemoryGoalStore
- test_architecture.py
- ToolExecutor
- system.py
- goals.py
- test_cf_access.py
- Goal
- What You Must Do When Invoked
- Jarvis — Sistema Operacional Cognitivo Pessoal
- FakeLLMProvider
- CapabilityPermissions
- FakeJwksEndpoint
- test_model_profiles.py
- PgGoalStore
- compilerOptions
- test_providers.py
- jobs.py
- 1. Stack por camada
- routers/settings.py
- contracts.py
- get_settings
- What You Must Do When Invoked
- compilerOptions
- dependencies
- devDependencies
- Jarvis — Plano de execução v1 → v3
- InMemoryEventBus
- CloudflareAccessMiddleware
- TavilyToolExecutor
- ChatMessageRow
- AccessTokenError
- get_llm_provider
- Runbook da infraestrutura
- conftest.py
- package.json
- manifest.json
- NeuralEngine
- ToolSpec
- GoalStore
- graphify reference: extra exports and benchmark
- test_memory_working.py
- env.py
- Mapa do Repositório e Política de Documentação
- RSAPrivateKey
- .claude/CLAUDE.md
- graphify reference: query, path, explain
- README.md
- caveman.md
- React + TypeScript + Vite
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- graphify reference: incremental update and cluster-only
- agents/README.md
- Capability SDK
- tsconfig.json
- graphify reference: GitHub clone and cross-repo merge
- graphify reference: transcribe video and audio
- test_memory_knowledge.py
- Capability
- Problema
- CapabilityHarness
- CLAUDE.md
- extraction-spec.md
- packages/__init__.py
- tests/__init__.py
- unit/__init__.py
- jarvis
- Handoff — trabalho interrompido no meio (2026-07-30)
- FileExplorer.tsx
- test_capability_sdk_manifest.py
- graphify reference: extra exports and benchmark
- react
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
- dependencies
- runtime/base.py
- memory/__init__.py
- stores.py
- PermissionPolicy
- registry.py
- CapabilityRegistry
- InMemoryKnowledgeIndex
- test_backup.py
- handlers.py
- ExecutionRequest
- ExperienceRecord
- CleanupService
- test_memory_experience.py
- GoalStatus
- AsyncSubprocessRunner
- ChatScreen.tsx
- InProcEventBus
- expo
- PythonRuntime
- SchedulerConfig
- SettingsScreen.tsx
- useChatStore.ts
- kernel/errors.py
- mobile/App.tsx
- schemas/__init__.py
- capabilities/manifest.py
- matching.py
- CapabilityRecord
- HistoryScreen.tsx
- BackupService
- .from_dsn
- graph.ts
- _child.py
- KnowledgeIndex
- FakeCapabilityStore
- GoalsScreen.tsx
- KnowledgeBase
- LanceDBVectorStore
- Plano de Implementação: Jarvis Mobile (React Native + Expo)
- O que precisa de validação manual
- 20260731T235635Z/manifest.json
- 20260801T000118Z/manifest.json
- Kernel
- Handoff — 31/07/2026 (madrugada de 01/08)
- entrypoint
- chat.py
- useAuthStore.ts
- compute_capability_digest
- 2. Interface (UI) e Estabilidade Corrigidas
- build_memory_system
- GoalBlocker
- ChatPage.tsx
- exemplo_nas — capability de exemplo do SDK
- .update_goal_status
- tools.py
- mobile/tsconfig.json
- restore.sh
- .escopo_de_escrita
- capability_id
- test_resolve_miss_publica_gap_no_bus_sem_levantar
- cap_loop.py
- cap_ok.py
- cap_rede.py
- test_evento_de_gap_carrega_intencao_contexto_e_goal
- .list_indexed
- .upsert
- remark-math
- tailwind-merge
- autoprefixer
- typescript
- backend/__init__.py
- backup.sh
- test_adaptador_postgres_implementa_a_porta
- test_docs_e_openapi_ficam_atras_do_gate
- test_websocket_sem_token_e_recusado

## God Nodes (most connected - your core abstractions)
1. `ToolSpec` - 90 edges
2. `CapabilityPermissions` - 70 edges
3. `CapabilityRegistry` - 67 edges
4. `Event` - 66 edges
5. `InMemoryGoalStore` - 62 edges
6. `Goal` - 57 edges
7. `Task` - 55 edges
8. `FakeLLMProvider` - 47 edges
9. `CapabilityHarness` - 46 edges
10. `GoalStatus` - 45 edges

## Surprising Connections (you probably didn't know these)
- `FakeJwksEndpoint` --uses--> `AccessTokenError`  [INFERRED]
  tests/unit/test_cf_access.py → apps/api/cf_access.py
- `FakeJwksEndpoint` --uses--> `CloudflareAccessMiddleware`  [INFERRED]
  tests/unit/test_cf_access.py → apps/api/cf_access.py
- `Base` --uses--> `CapabilityHealth`  [INFERRED]
  apps/api/db/models.py → packages/registry/records.py
- `GoalRow` --uses--> `CapabilityHealth`  [INFERRED]
  apps/api/db/models.py → packages/registry/records.py
- `TaskRow` --uses--> `CapabilityHealth`  [INFERRED]
  apps/api/db/models.py → packages/registry/records.py

## Import Cycles
- None detected.

## Communities (177 total, 27 thin omitted)

### Community 0 - "test_registry.py"
Cohesion: 0.11
Nodes (37): escrever_capability(), Path, `discover()`, `get_active()`, `resolve()` e a persistência do Capability…, Nome do diretório é a chave em disco; divergência é capability ambígua., Aprovada mas não ativa não executa: o gate 2 não terminou., Quem chama não sabe o nome da capability — é esse o ponto do D-1., `trigger_intent` é o campo que `plan.md` §6 cita e o contrato ainda não tem., Errar para o lado do miss é decisão de projeto: acerto errado escreve em disco. (+29 more)

### Community 1 - "GeminiProvider"
Cohesion: 0.08
Nodes (38): _as_dict(), _as_int(), _as_list(), _as_str(), _attach_images(), _bare_model(), _conforms_to_protocol(), _error_detail() (+30 more)

### Community 2 - "ollama_provider.py"
Cohesion: 0.09
Nodes (32): _as_dict(), _as_int(), _as_str(), _attach_images(), _conforms_to_protocol(), _error_detail(), _looks_like_embedding_unsupported(), OllamaProvider (+24 more)

### Community 3 - "deps.py"
Cohesion: 0.08
Nodes (35): _build_anthropic(), FastAPI Depends wiring. Todas as dependências do sistema passam por aqui.…, AnthropicProvider, Provider Anthropic — implementação concreta de LLMProvider. Usado pelo Chief AI…, LLMProvider concreta para API Anthropic. Suporta complete, stream e NÃO embed., ContentBlocked, LLMError, ProviderRequestError (+27 more)

### Community 4 - "src/App.tsx"
Cohesion: 0.27
Nodes (6): App(), GUARDRAILS, ProviderOption, RulesPage(), ToolInfo, ToolsPage()

### Community 5 - "CapabilityManifest"
Cohesion: 0.06
Nodes (38): CapabilityManifest, Any, field_validator, model_validator, Serializa exatamente o `manifest.yaml` no disco da capability., Mapeia a chave legada `trigger_intent` para o campo do contrato. Só quando o…, Aceita string solta e descarta entrada em branco. Uma intenção só é o caso…, Aceita o nome antigo e devolve o canônico. Vazio volta ao default. (+30 more)

### Community 6 - "Settings"
Cohesion: 0.07
Nodes (23): _build_gemini(), _build_lmstudio(), _build_ollama(), _build_openai_compatible(), Entrada separada de `local` de propósito: o Ollama é servido pela API nativa…, LM Studio na LAN. Mesma classe do `openai` — o LM Studio serve a API OpenAI —…, Serve tanto `openai` quanto `local` — LM Studio, vLLM e Koboldcpp falam a mesma…, LLMProvider (+15 more)

### Community 7 - "TestClient"
Cohesion: 0.12
Nodes (33): TestClient, client(), _hdr(), make_token(), FastAPI, A mesma conta Zero Trust assina token para todas as suas aplicações. Sem…, Token assinado, no prazo e para esta aplicação — e ainda assim recusado.…, `kid` conhecido, formato perfeito, chave errada — o caso que só a verificação… (+25 more)

### Community 8 - "InMemoryGoalStore"
Cohesion: 0.17
Nodes (27): InMemoryGoalStore, `GoalStore` em dicionário, com a mesma semântica do `PgGoalStore`. Guarda e…, `ToolExecutor` que registra chamadas em vez de executar. O Chief AI e o…, RecordingToolExecutor, _goal_meio_caminho(), _montar(), Goal, Task (+19 more)

### Community 9 - "test_architecture.py"
Cohesion: 0.13
Nodes (29): arquivos_python(), coletar_imports(), ImportRef, nomes_importados(), _pacote_do_arquivo(), _proibido_para_o_chief(), parametrize, Path (+21 more)

### Community 10 - "ToolExecutor"
Cohesion: 0.16
Nodes (7): ChiefAI, UUID, Chief AI — núcleo mínimo da v0. Recebe mensagem do usuário, envia para LLM com…, Chief AI v0: LLM loop com tool calling., Processa mensagem do usuário. Yield StreamChunks para streaming., Catálogo executável de tools. Na v0 são tools nativas; na v1 vira o Capability…, ToolExecutor

### Community 11 - "system.py"
Cohesion: 0.08
Nodes (19): Goal Manager — orquestra goals → tasks com checkpoint. Responsabilidades: -…, Any, Nível `short` — turnos recentes da conversa corrente (`plan.md` §10). Vida…, Working memory for active tasks and goals using Redis., Stores arbitrary state with a TTL., Retrieves stored state., Deletes stored state., ShortTermMemory (+11 more)

### Community 12 - "goals.py"
Cohesion: 0.18
Nodes (22): create_goal(), CreateGoalRequest, execute_goal(), get_goal(), list_goals(), list_tasks(), AsyncSession, BaseModel (+14 more)

### Community 13 - "test_cf_access.py"
Cohesion: 0.11
Nodes (27): extract_token(), Token do header do Access; na falta dele, do cookie `CF_Authorization`., Any, parametrize, Gate do Cloudflare Access: verificação do JWT na origem. A suíte assina os…, O HEALTHCHECK do Dockerfile bate aqui de dentro do container e não tem como…, O default não pode quebrar `127.0.0.1:8000`, onde não existe Access e portanto…, Quem preencheu as três variáveis já montou o Access. Exigir um segundo passo… (+19 more)

### Community 14 - "Goal"
Cohesion: 0.13
Nodes (30): Goal, Unidade de trabalho do sistema. Sobrevive ao fechamento da janela., Passo executável de um Goal. Executado por uma capability, nunca pelo Chief AI., Task, _concluir(), _goal_com_cadeia(), Goal, Task (+22 more)

### Community 15 - "What You Must Do When Invoked"
Cohesion: 0.07
Nodes (26): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+18 more)

### Community 16 - "Jarvis — Sistema Operacional Cognitivo Pessoal"
Cohesion: 0.07
Nodes (26): 10. Memória, 11. Eventos, scheduler e agentes contínuos, 12. Modelos, 13. Cliente PWA, 14. Roadmap, 15. Decisões resolvidas, 16. Fora de escopo, 1. Objetivo (+18 more)

### Community 17 - "FakeLLMProvider"
Cohesion: 0.11
Nodes (24): cosine(), FakeLLMProvider, Quantas respostas roteirizadas ainda não foram consumidas., Vetor unitário derivado de SHA-256 do texto. `hash()` embutido é semeado por…, Similaridade de cosseno. Usada para afirmar ranking de `embed()`., `LLMProvider` roteirizado. Sem rede, sem aleatoriedade. `complete()` consome a…, stable_embedding(), Os dublês são testados como código de produção. Dublê que sai da porta… (+16 more)

### Community 18 - "CapabilityPermissions"
Cohesion: 0.05
Nodes (68): F, Ensaio, BaseModel, Pares `(kind, target)` de tudo que a tool exige, para conferência., O que a tool faria, sem ter feito. Retorno de `call(dry_run=True)`. `executado`…, Marca um método como tool da capability. O método continua sendo um método…, `permissions` é a concessão do manifest. Ausente = nada concedido. O default…, A concessão sob a qual esta instância roda. (+60 more)

### Community 19 - "FakeJwksEndpoint"
Cohesion: 0.12
Nodes (23): CloudflareAccessVerifier, JwksCache, Verifica assinatura, `aud`, `iss`, validade e identidade do dono., Chaves públicas do Access, em memória, indexadas por `kid`. Duas pressões…, MockTransport, app(), FakeJwksEndpoint, `/cdn-cgi/access/certs` em memória, com contador de acessos. O contador é o que… (+15 more)

### Community 20 - "test_model_profiles.py"
Cohesion: 0.05
Nodes (73): build_llm_provider_for_profile(), profile_override(), Collection, Override do dono para (provider, perfil), ou "" se não declarado. `getattr`…, Perfil → modelo para o provider dado. Não vai à rede e não levanta. `served` é…, Provider já apontado para o modelo do perfil. Nunca levanta por perfil. É a…, resolve_profile_model(), _async() (+65 more)

### Community 21 - "PgGoalStore"
Cohesion: 0.14
Nodes (10): PgConversationStore, PgGoalStore, AsyncSession, ChatMessage, Goal, GoalStatus, Task, UUID (+2 more)

### Community 22 - "compilerOptions"
Cohesion: 0.08
Nodes (23): compilerOptions, allowArbitraryExtensions, allowImportingTsExtensions, erasableSyntaxOnly, jsx, lib, module, moduleDetection (+15 more)

### Community 23 - "test_providers.py"
Cohesion: 0.14
Nodes (23): build_llm_provider(), provider_default_model(), Providers atendíveis agora, em ordem de preferência (não alfabética). Fonte…, Modelo default de um provider, ou "" se o provider não existe., Resolve o provider pelo mapa. Desconhecido falha nomeando os válidos. Fora do…, valid_provider_ids(), parametrize, Contrato do mapa de providers de LLM (`apps/api/deps.py`). Cobre a fronteira… (+15 more)

### Community 24 - "jobs.py"
Cohesion: 0.05
Nodes (49): Backup: `pg_dump` do Postgres + snapshot do diretório do LanceDB. O risco R-5…, Lê e valida o `manifest.json` de um backup. Usado por ferramenta e teste., Confere os digests do manifesto contra o disco. Devolve a lista de problemas —…, read_manifest(), verify_backup(), Limpeza: arquivos de log velhos e chaves de short-term memory que vazaram. Duas…, Scheduler package — os três jobs recorrentes da v1.4. Nada aqui importa…, Scheduler: os três jobs recorrentes da v1.4 (`plan-execution.md` §3, D-11).… (+41 more)

### Community 25 - "1. Stack por camada"
Cohesion: 0.09
Nodes (22): 1.1 Frontend web (PWA), 1.2 Backend, 1.3 LLM e inferência, 1.4 Dados, 1.5 RAG e parsing de documentos, 1.6 Busca web, controle do computador, mídia, 1.7 Observabilidade, 1.8 Containers e qualidade (+14 more)

### Community 26 - "routers/settings.py"
Cohesion: 0.12
Nodes (26): Ids que o provider diz servir agora, ou `None` se não deu para saber. `None`…, served_models(), get_settings(), list_profiles(), list_providers(), ProfileAssignment, ProfileCatalog, ProviderCatalog (+18 more)

### Community 27 - "contracts.py"
Cohesion: 0.06
Nodes (42): Executive Function — loop assíncrono que processa goals. Consome goals ativos,…, Tavily web search — primeira tool real da v0. Implementa ToolExecutor…, Barramento de eventos em processo, sobre `asyncio.Queue`. Primeiro uso real da…, O `Kernel`: escolhe o adapter, executa, e conta o que aconteceu. É a peça que…, Montagem dos níveis a partir de configuração. O backend de vetores é escolhido…, KnowledgeIndex, LongTermMemory, Nível `long` — fatos duráveis sobre o dono e o ambiente. `plan.md` §10:… (+34 more)

### Community 28 - "get_settings"
Cohesion: 0.18
Nodes (15): _http_transport(), install_cloudflare_access(), FastAPI, Verificação, na origem, da asserção assinada pelo Cloudflare Access. O Access…, Instala o gate se ele estiver ligado. Devolve se instalou. A decisão de ligar…, Transporte do cliente que busca o JWKS. `None` = pilha real do httpx. É função…, _configure_logging(), create_app() (+7 more)

### Community 29 - "What You Must Do When Invoked"
Cohesion: 0.07
Nodes (26): For /graphify add and --watch, For /graphify query, For the commit hook and native AGENTS.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+18 more)

### Community 30 - "compilerOptions"
Cohesion: 0.10
Nodes (19): compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, lib, module, moduleDetection, noEmit, noFallthroughCasesInSwitch (+11 more)

### Community 31 - "dependencies"
Cohesion: 0.11
Nodes (19): dependencies, clsx, react, react-dom, react-markdown, react-router, rehype-katex, remark-gfm (+11 more)

### Community 32 - "devDependencies"
Cohesion: 0.11
Nodes (19): devDependencies, oxlint, postcss, tailwindcss, @types/node, @types/react, @types/react-dom, vite (+11 more)

### Community 33 - "Jarvis — Plano de execução v1 → v3"
Cohesion: 0.09
Nodes (21): 1. Estado real hoje (auditado, não declarado), 2. Triagem das sugestões estruturais, 2b. Triagem da segunda rodada de sugestões (2026-07-30), 3. v1 — Sistema utilizável de verdade, 4. v2 — Capabilities escritas à mão, 5. v3 — Self-evolution, 6. Ordem e dependências, 7. Invariantes (+13 more)

### Community 34 - "InMemoryEventBus"
Cohesion: 0.07
Nodes (39): BackupError, Backup não terminou. O evento `backup.completed` **não** é emitido., Starts the APScheduler and registers jobs., Backup do Postgres (`pg_dump`) e do diretório do LanceDB. Emite…, Log antigo e chaves de short-term memory sem TTL., Reindexação incremental do knowledge., Publica no bus. Bus ausente ou com defeito não invalida o job feito., Registra e roda os jobs periódicos do sistema. (+31 more)

### Community 35 - "CloudflareAccessMiddleware"
Cohesion: 0.33
Nodes (6): CloudflareAccessMiddleware, Gate ASGI puro: nega por default, libera `/health` por exceção. **Por que…, ASGIApp, Receive, Scope, Send

### Community 36 - "TavilyToolExecutor"
Cohesion: 0.28
Nodes (4): _as_int(), Converte argumento de tool call em int, caindo no default se não der. Os…, ToolExecutor com a tool `web_search` (Tavily API)., TavilyToolExecutor

### Community 37 - "ChatMessageRow"
Cohesion: 0.25
Nodes (18): ChatMessageRow, ConversationRow, ChatMessageResponse, ChatPreview, get_chat_messages(), get_chats(), get_stats(), ModelStats (+10 more)

### Community 38 - "AccessTokenError"
Cohesion: 0.23
Nodes (8): AccessTokenError, Any, Exception, Chave pública do `kid`, buscando o JWKS só quando necessário., Chave em cache, se o cache ainda está dentro do TTL., Rebusca o JWKS, respeitando o cooldown. Chamado sob `self._lock`., Claims do token, ou `AccessTokenError` nomeando o que reprovou., Motivo técnico da recusa. Vai para o log, nunca para a resposta.

### Community 39 - "get_llm_provider"
Cohesion: 0.11
Nodes (25): dispose_engine(), get_engine(), get_session_factory(), AsyncSession, Async SQLAlchemy engine e session factory. Única fonte de `AsyncSession` no…, effective_provider_and_model(), get_chief_ai(), get_conversation_store() (+17 more)

### Community 40 - "Runbook da infraestrutura"
Cohesion: 0.05
Nodes (37): 1. Pré-requisito único: o `.env`, 2. Subir tudo, 3. Migrations (Alembic), 4. Inferência: fora do Docker, de propósito, 5. Portas expostas, 6. Derrubar, 7. Quando algo não sobe, 8.1 A decisão: conector como serviço do Windows, no host (+29 more)

### Community 41 - "conftest.py"
Cohesion: 0.07
Nodes (24): conversation_store(), event_bus(), fake_embeddings(), fake_llm(), goal_id(), goal_store(), hashed_embedding(), InMemoryConversationStore (+16 more)

### Community 42 - "package.json"
Cohesion: 0.20
Nodes (9): name, private, scripts, build, dev, lint, preview, type (+1 more)

### Community 43 - "manifest.json"
Cohesion: 0.20
Nodes (9): background_color, description, display, icons, name, orientation, short_name, start_url (+1 more)

### Community 45 - "ToolSpec"
Cohesion: 0.10
Nodes (25): ChatCompletionMessageToolCall, Any, Converte ToolSpec → formato Anthropic tool_use., Separa system prompt e converte Messages → formato Anthropic., _to_anthropic_messages(), _to_anthropic_tools(), Completion, Message (+17 more)

### Community 46 - "GoalStore"
Cohesion: 0.15
Nodes (10): ConversationStore, GoalStore, ChatMessage, Goal, GoalStatus, Task, UUID, Persistência de objetivos e tarefas. Implementado em `apps/api/db`. (+2 more)

### Community 47 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 48 - "test_memory_working.py"
Cohesion: 0.06
Nodes (54): Estado da task em execução: plano, parciais e o que já foi tentado. Vida útil =…, A tentativa que ficou `STARTED` sem desfecho — a que o kill pegou., WorkingMemoryState, InMemoryWorkingMemoryStore, JsonFileWorkingMemoryStore, `WorkingMemoryStore` em dicionário. Não sobrevive ao processo, de propósito., `WorkingMemoryStore` em disco: um arquivo por task. Um arquivo por task, e não…, Task (+46 more)

### Community 49 - "env.py"
Cohesion: 0.36
Nodes (7): get_sync_url(), Alembic env.py — usa os ORM models de apps.api.db.models. O `target_metadata`…, Esconde a senha de um DSN antes de ele ir para log. O DSN carrega credencial.…, Lê a URL do settings (async) e converte para sync., _redact(), run_migrations_offline(), run_migrations_online()

### Community 50 - "Mapa do Repositório e Política de Documentação"
Cohesion: 0.25
Nodes (7): Documentação sob demanda, Documentos permitidos, Estrutura do monorepo, Git, Layout de uma capability em disco, Mapa do Repositório e Política de Documentação, Sincronização casa ↔ trabalho

### Community 51 - "RSAPrivateKey"
Cohesion: 0.17
Nodes (16): RSAPrivateKey, app_real(), _generate_key(), _jwk(), jwks(), key_alheia(), keypair(), fixture (+8 more)

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

### Community 61 - "Capability SDK"
Cohesion: 0.33
Nodes (5): Capability SDK, Escrever uma capability, Gerar o manifest, Superfície, Testar

### Community 67 - "test_memory_knowledge.py"
Cohesion: 0.05
Nodes (54): chunk_id(), chunk_text(), Formata os trechos recuperados para o prompt, com a fonte junto de cada um., Divide o texto em pedaços de até `size` caracteres, com sobreposição. A…, Id estável do chunk. Reingerir o mesmo documento reescreve as mesmas linhas., render_knowledge_context(), InMemoryVectorStore, `VectorStore` em dicionário, com cosseno em Python puro. É o adapter… (+46 more)

### Community 68 - "Capability"
Cohesion: 0.07
Nodes (47): alvos_nao_concedidos(), Capability, _coletar(), concedido(), _conferir_assinatura(), _conferir_identidade(), _dentro(), especificacoes() (+39 more)

### Community 69 - "Problema"
Cohesion: 0.07
Nodes (31): formatar(), Problema, BaseModel, Um defeito localizado: onde está e o que há de errado. `campo` usa o caminho…, Lista de problemas em bloco legível de mensagem de exceção., _avisos_de_cobertura(), CasoDeTool, _conferir_espera() (+23 more)

### Community 70 - "CapabilityHarness"
Cohesion: 0.11
Nodes (50): CapabilityHarness, Verifica e exercita uma capability instalada em disco. A instância recebida é a…, capability(), concessao(), FalarEntrada, GravarEntrada, GravarSaida, instalar() (+42 more)

### Community 81 - "Handoff — trabalho interrompido no meio (2026-07-30)"
Cohesion: 0.12
Nodes (15): 0. Estado da árvore, 1. Como rodar qualquer coisa, 2. Placar agora, 3. Agente A — Cloudflare Tunnel (infraestrutura), 4. Agente B — validação do JWT do Access na origem, 5. Ordem sugerida para retomar, 6. O que o dono precisa fazer no dashboard, Entregue e no disco (+7 more)

### Community 83 - "FileExplorer.tsx"
Cohesion: 0.29
Nodes (6): GraphNode, FileExplorer, FileExplorerProps, TreeNode, NeuralMap(), BrainPage()

### Community 84 - "test_capability_sdk_manifest.py"
Cohesion: 0.11
Nodes (51): ManifestInvalido, `manifest.yaml` ou `permissions.yaml` fora do contrato. Traz **todos** os…, carregar_arquivos(), manifest_de(), permissoes_declaradas(), Capability, Path, Lê e valida `manifest.yaml` + `permissions.yaml` de uma capability. Raises:… (+43 more)

### Community 85 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 86 - "react"
Cohesion: 0.20
Nodes (9): plugins, rules, react/only-export-components, react/rules-of-hooks, $schema, oxc, react, typescript (+1 more)

### Community 87 - "Layout.tsx"
Cohesion: 0.31
Nodes (7): Layout(), LayoutProps, MOBILE_TABS, PageId, NAV_ITEMS, Sidebar(), SidebarProps

### Community 88 - "Engine.ts"
Cohesion: 0.27
Nodes (8): col(), GraphLink, grayRgba(), hex2rgb(), LOBES, PAL, RGB, rgba()

### Community 89 - "HistoryPage.tsx"
Cohesion: 0.22
Nodes (8): ChatPreview, GoalSummary, HistoryPage(), ModelStats, StatsResponse, STATUS_MAP, TaskSummary, ToolUsage

### Community 90 - "GoalManager"
Cohesion: 0.12
Nodes (14): Executive, Loop de controle sobre goals ativos., Boot: resume interrupted goals, then enter poll loop., Enfileira goal para processamento., Main loop: processa goals da fila + poll por novos., GoalManager, Goal, Task (+6 more)

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

### Community 99 - "dependencies"
Cohesion: 0.04
Nodes (46): dependencies, axios, expo, expo-constants, expo-crypto, expo-secure-store, expo-status-bar, react (+38 more)

### Community 100 - "runtime/base.py"
Cohesion: 0.08
Nodes (34): ExecutionLimits, ExecutionResult, ExecutionStatus, BaseModel, Protocol, StrEnum, Contrato de execução: o que entra num runtime, o que sai, e quem executa.…, O que volta ao Executive. Nunca levanta: falha é campo, não exceção.… (+26 more)

### Community 101 - "memory/__init__.py"
Cohesion: 0.09
Nodes (33): Nível `experience` — padrões extraídos de execução. `plan.md` §10: "é o nível…, Formata os padrões para o prompt de planejamento. O bloco diz o que fazer com a…, render_experience_context(), Os cinco níveis de memória de `plan.md` §10. | Nível | Módulo | Tempo de vida |…, Nível `knowledge` — documentos indexados para busca semântica (RAG). `plan.md`…, Busca semântica sobre os fatos., Attempt, AttemptOutcome (+25 more)

### Community 103 - "stores.py"
Cohesion: 0.09
Nodes (13): _escrever_atomico(), InMemoryKnowledgeIndex, JsonFileExperienceStore, JsonFileKnowledgeIndex, _ler_json(), IndexedDocument, Path, UUID (+5 more)

### Community 104 - "PermissionPolicy"
Cohesion: 0.08
Nodes (30): IO, _envolver_caminhos(), _host_de(), _instalar_filesystem(), _instalar_processo(), _instalar_rede(), install(), _liberado() (+22 more)

### Community 105 - "registry.py"
Cohesion: 0.09
Nodes (30): CapabilityGapDetected, InvalidCapabilityStateError, ManifestLoadError, Exception, Erros do Capability Registry., Lacuna de capacidade. **Não é mais levantada por `resolve()`** (D-2): desde a…, `manifest.yaml` ausente, ilegível ou fora do schema., Capability não está no estado exigido pela operação. (+22 more)

### Community 106 - "CapabilityRegistry"
Cohesion: 0.07
Nodes (21): CapabilityRegistry, Capability, datetime, Path, UUID, D-3: o código em disco tem de ser o que passou pelo gate., Entrada mínima e `disabled` para uma capability que não carregou. O nome do…, Raiz do catálogo em disco. Público desde a v1.2: o kernel precisa do diretório… (+13 more)

### Community 107 - "InMemoryKnowledgeIndex"
Cohesion: 0.13
Nodes (29): InMemoryKnowledgeIndex, InMemoryKnowledgeIndex, datetime, IndexedDocument, KnowledgeDocument, KnowledgeIndex, Path, Motivo legível, ou string vazia quando dá para trabalhar. Pular é **logado em… (+21 more)

### Community 108 - "test_backup.py"
Cohesion: 0.15
Nodes (35): FakePgDump, make_service(), make_target(), datetime, Path, `BackupService` — o que o job escreve no disco e quando ele se recusa. R-5…, O digest é o contrato com o restore: se mentir, o restore recusa backup bom., Um byte trocado tem de reprovar — senão o digest é decoração. (+27 more)

### Community 109 - "handlers.py"
Cohesion: 0.08
Nodes (30): construir(), NasArquivos, Capability, Path, Protocol, O que a capability `exemplo_nas` faz. Molde das capabilities reais da v2. Esta…, A pasta concedida. Sem concessão não há onde trabalhar. Levantar…, A capability sob a concessão que está no manifest em disco. É a fábrica que o… (+22 more)

### Community 110 - "ExecutionRequest"
Cohesion: 0.14
Nodes (28): ExecutionRequest, Uma chamada de tool prestes a acontecer., BusDeTeste, kernel_com_bus(), manifesto(), Path, Os três aceites da v1.2, exercidos contra subprocesso de verdade. `plan-…, A contraprova do teste de negação: o que foi declarado tem de passar. Um guarda… (+20 more)

### Community 111 - "ExperienceRecord"
Cohesion: 0.10
Nodes (15): ExperienceMemory, UUID, Como o dono costuma decidir — o terceiro conteúdo do nível (`plan.md` §10)., Registros que já passaram do limiar, do mais recorrente ao menos. É a **única**…, Acumula e promove padrões de execução., Registra (ou incrementa) a falha de uma capability/tool., Registra que a capability funcionou. Contrapeso das falhas., error_signature() (+7 more)

### Community 112 - "CleanupService"
Cohesion: 0.11
Nodes (23): CleanupService, datetime, Path, Poda arquivos de log por idade e recolhe chaves efêmeras sem TTL., envelhecer(), FakeKeyspace, Path, `CleanupService` — poda de log por idade e recolhimento de chave sem TTL. Os… (+15 more)

### Community 113 - "test_memory_experience.py"
Cohesion: 0.13
Nodes (30): goal(), memoria(), fixture, Goal, Task, Nível `experience` — aceite 3 da v1.3 (`plan-execution.md` §3). > "Falha…, Acidente não é padrão. Sem esta linha, o nível vira log de erros no prompt., `memory=None` mantém o comportamento anterior à v1.3, byte a byte. (+22 more)

### Community 114 - "GoalStatus"
Cohesion: 0.16
Nodes (26): Base, CapabilityRow, GoalRow, SQLAlchemy ORM tables derivados dos contratos Pydantic. Regra: contracts.py é a…, Catálogo de capabilities (v1.1). Espelha…, Base declarativa. Alembic importa daqui., SystemSettingsRow, TaskRow (+18 more)

### Community 115 - "AsyncSubprocessRunner"
Cohesion: 0.13
Nodes (26): AsyncSubprocessRunner, `CommandRunner` sobre `asyncio`. Herda o ambiente e acrescenta o que veio.…, MonkeyPatch, python_c(), `AsyncSubprocessRunner` — a única peça do scheduler que fala com o SO. Todo o…, Sem isto, um `pg_dump` pendurado segura o job até o backup do dia seguinte., `errors="replace"`: saída suja de um binário não pode virar exceção., `PGPASSWORD` é passado por `env`, nunca por `argv` (ver `PostgresTarget`). (+18 more)

### Community 116 - "ChatScreen.tsx"
Cohesion: 0.15
Nodes (20): GoalCard, styles, InputBar(), InputBarProps, styles, MessageBubble, styles, BrainScreen() (+12 more)

### Community 117 - "InProcEventBus"
Cohesion: 0.09
Nodes (13): EventHandler, InProcEventBus, Eventos aceitos e ainda não entregues., Entrega tudo que já está na fila e devolve quantos foram entregues.…, Sobe o laço de despacho em segundo plano. Idempotente., Drena o que sobrou e encerra o laço. Idempotente., Um consumidor e os tipos de evento que ele quer. `types=None` é "tudo" — usado…, Nome legível do consumidor, para o log de falha dizer quem quebrou. (+5 more)

### Community 118 - "expo"
Cohesion: 0.07
Nodes (26): backgroundColor, backgroundImage, foregroundImage, monochromeImage, adaptiveIcon, package, predictiveBackGestureEnabled, expo (+18 more)

### Community 119 - "PythonRuntime"
Cohesion: 0.12
Nodes (15): Any, Path, PythonRuntime, raiz_do_repo(), Roda a tool em subprocesso e devolve o desfecho. Não levanta., O contrato de entrada de `_child.py`, em JSON., O envelope do filho, ou `None` se ele não chegou a escrevê-lo., Mensagem para o caso em que o filho morreu antes de responder. (+7 more)

### Community 120 - "SchedulerConfig"
Cohesion: 0.12
Nodes (17): BaseSettings, Path, Configuração dos jobs, lida do ambiente com prefixo `JARVIS_`. Por que **não**…, Caminho absoluto; relativo é resolvido contra a raiz do repositório., Onde cada job escreve, quanto guarda e a que horas roda., resolve_path(), SchedulerConfig, _lancedb_dir() (+9 more)

### Community 121 - "SettingsScreen.tsx"
Cohesion: 0.14
Nodes (17): api, SessionProbe, getSystemSettings(), listProfiles(), listProviders(), ProfileAssignment, ProfileCatalog, ProviderCatalog (+9 more)

### Community 122 - "useChatStore.ts"
Cohesion: 0.12
Nodes (13): ChatChunk, ChatHttpResponse, ChatSocket, ChatSocketHandlers, RECONNECT_DELAYS_MS, RNWebSocket, sendChatOverHttp(), ToolCallPayload (+5 more)

### Community 123 - "kernel/errors.py"
Cohesion: 0.13
Nodes (16): ExecutionFailed, ExecutionTimeout, KernelError, PermissionDenied, Exception, Erros do kernel de execução. Todos derivam de `KernelError` para que quem chama…, Base dos erros do kernel., `manifest.runtime` não tem adapter registrado. Erro de configuração, não de… (+8 more)

### Community 124 - "mobile/App.tsx"
Cohesion: 0.15
Nodes (15): App(), navigationTheme, Stack, styles, Tab, TAB_GLYPH, probeSession(), RootStackParamList (+7 more)

### Community 125 - "schemas/__init__.py"
Cohesion: 0.19
Nodes (15): Schemas de entrada e saída da capability `exemplo_nas`., ArquivoInfo, caminho_seguro(), GravarEntrada, GravarSaida, ListarEntrada, ListarSaida, BaseModel (+7 more)

### Community 126 - "capabilities/manifest.py"
Cohesion: 0.14
Nodes (20): _conferir_chaves(), _conferir_entrypoint(), _conferir_permissions_yaml(), escrever_arquivos(), _intents(), _ler_mapa(), _problemas_de_validacao(), Any (+12 more)

### Community 127 - "matching.py"
Cohesion: 0.17
Nodes (17): _avisar_ambiguidade(), build_index(), casa(), CatalogIndex, frase(), match_intent(), normalizar(), Casamento determinístico de intenção contra o catálogo (D-1). `plan.md` §6:… (+9 more)

### Community 128 - "CapabilityRecord"
Cohesion: 0.18
Nodes (7): PgCapabilityStore, datetime, `CapabilityStore` (packages/registry/ports.py) sobre Postgres. Casa por `name`,…, Grava a capability, casando por `name` — a chave estável em disco., CapabilityRecord, BaseModel, Uma linha da tabela `capabilities`.

### Community 129 - "HistoryScreen.tsx"
Cohesion: 0.20
Nodes (14): describeError(), ChatPreview, getStats(), listChatMessages(), listChats(), ModelStats, StatsResponse, StoredChatMessage (+6 more)

### Community 130 - "BackupService"
Cohesion: 0.21
Nodes (8): BackupService, datetime, Path, Executa o backup completo. Levanta `BackupError` se algo falhar., Cópia do diretório de vetores. Ausência é caso normal, não erro. Nunca importa…, Carimbo UTC; sufixo `-N` se dois backups caírem no mesmo segundo., Backups **íntegros**, do mais antigo ao mais novo. Íntegro = tem…, Produz um diretório de backup autoconferível. Layout resultante::…

### Community 131 - ".from_dsn"
Cohesion: 0.19
Nodes (14): Aceita `postgresql://`, `postgresql+asyncpg://` e `postgresql+psycopg://`., parametrize, `PostgresTarget` — a tradução do DSN da aplicação para argumentos do libpq.…, asyncpg na app, psycopg no Alembic, cru no psql. Os três apontam para o mesmo…, `@` na senha vira `%40` no DSN. Passar `%40` para o pg_dump autenticaria com a…, PGPASSWORD vazio e PGPASSWORD ausente são coisas diferentes para o libpq: o…, test_aceita_os_tres_dsn_que_circulam_no_repo(), test_dsn_invalido_falha_dizendo_o_que_falta() (+6 more)

### Community 132 - "graph.ts"
Cohesion: 0.18
Nodes (12): BrainGraph, BrainLink, BrainNode, downsample(), fetchBrainGraph(), RawLink, RawNode, BrainCanvas() (+4 more)

### Community 133 - "_child.py"
Cohesion: 0.23
Nodes (14): negados(), Alvos negados até agora, na ordem: `["fs:/etc/passwd", "net:1.1.1.1:80"]`., _aceita_dry_run(), _ensaio_minimo(), _envelope(), main(), Any, Bootstrap do subprocesso de uma capability `python`. Roda como `python -P -B -m… (+6 more)

### Community 134 - "KnowledgeIndex"
Cohesion: 0.17
Nodes (7): KnowledgeIndex, IndexedDocument, Protocol, UUID, Persistência do estado vivo da task. O adapter default é arquivo JSON (um por…, Catálogo do que já foi indexado: `doc_id` → hash + ids dos chunks. É o que…, WorkingMemoryStore

### Community 135 - "FakeCapabilityStore"
Cohesion: 0.15
Nodes (9): FakeCapabilityStore, Any, O motivo de a tabela existir: dicionário em memória morre no `restart`., Se some da tabela, o dashboard de saúde da v1.5 não tem o que mostrar., `CapabilityStore` em dicionário, com a semântica do `PgCapabilityStore`. Guarda…, test_capability_quebrada_tambem_e_persistida_como_disabled(), test_estado_operacional_sobrevive_ao_restart(), test_fake_store_implementa_a_porta() (+1 more)

### Community 136 - "GoalsScreen.tsx"
Cohesion: 0.26
Nodes (11): createGoal(), executeGoal(), Goal, GoalStatus, listGoals(), listTasks(), Task, TaskStatus (+3 more)

### Community 137 - "KnowledgeBase"
Cohesion: 0.20
Nodes (8): KnowledgeBase, KnowledgeDocument, RAG incremental sobre a porta `VectorStore`., Indexa o documento. Conteúdo inalterado sai sem calcular embedding., Reindexação incremental de um lote — o que o job da v1.4 chama., Remove o documento e todos os chunks dele. `plan.md` §10: até a fonte sumir., Busca semântica. O vetor da consulta sai da mesma porta da ingestão., IngestResult

### Community 138 - "LanceDBVectorStore"
Cohesion: 0.23
Nodes (5): LanceDBVectorStore, Any, `VectorStore` sobre LanceDB embarcado. **Não roda em CPU sem AVX2.** Escrito e…, Abre (ou cria) a tabela. Síncrono: chamado sempre via `to_thread`., _validar_namespace()

### Community 139 - "Plano de Implementação: Jarvis Mobile (React Native + Expo)"
Cohesion: 0.15
Nodes (12): 1. Inicialização e Dependências, 2. Estrutura de Diretórios (dentro de `apps/mobile`), 3. Fluxo de Autenticação e Cloudflare Access, 4. Integração com a API, Adendo:, Etapas de Validação Local, Plano de Implementação: Jarvis Mobile (React Native + Expo), Proposed Changes (+4 more)

### Community 140 - "O que precisa de validação manual"
Cohesion: 0.15
Nodes (12): 1. Login no Cloudflare Access (o item de maior risco), 2. Chat, 3. Brain, 4. Metas, 5. Ajustes, Autenticação — os dois modos, Fora de escopo, registrado, Jarvis Mobile (+4 more)

### Community 141 - "20260731T235635Z/manifest.json"
Cohesion: 0.15
Nodes (12): backup_id, created_at, database, lancedb, manifest_version, postgres, bytes, files (+4 more)

### Community 142 - "20260801T000118Z/manifest.json"
Cohesion: 0.15
Nodes (12): backup_id, created_at, database, lancedb, manifest_version, postgres, bytes, files (+4 more)

### Community 143 - "Kernel"
Cohesion: 0.18
Nodes (7): Kernel do Jarvis — a infraestrutura de execução, abaixo dos agentes.…, Kernel, Publica no bus, se houver bus. Sem bus configurado o kernel executa igual: um…, Despacha execuções para o adapter do `runtime` declarado no manifest., Runtimes atendíveis nesta instalação, em ordem estável., Adapter do runtime, ou `RuntimeNotSupported` dizendo quais existem., Executa uma tool. Devolve o desfecho; não levanta por falha dela. Levanta…

### Community 144 - "Handoff — 31/07/2026 (madrugada de 01/08)"
Cohesion: 0.20
Nodes (9): Ambiente, Bugs achados por execução (não por leitura), EM ABERTO — bolhas de chat vazias (não resolvido), Estado medido, não declarado, Handoff — 31/07/2026 (madrugada de 01/08), Pendências do dono (fora do código), Restrição desta máquina, Também em aberto (+1 more)

### Community 145 - "entrypoint"
Cohesion: 0.22
Nodes (9): Handler, entrypoint(), O chamável que o kernel invoca: `atributo(tool, arguments) -> dict`. Recebe uma…, O kernel chama `atributo(tool, arguments)` e espera um mapa JSON., Construir lê o manifest do disco; o import do módulo tem de ser barato., test_entrypoint_so_constroi_na_primeira_chamada(), test_entrypoint_tem_a_assinatura_que_o_kernel_chama(), Request (+1 more)

### Community 146 - "chat.py"
Cohesion: 0.31
Nodes (8): chat_post(), ChatRequest, ChatResponse, AsyncSession, BaseModel, post, Rota de chat com streaming via WebSocket. O fluxo real: WebSocket → Chief AI →…, Chat síncrono (sem streaming). Útil para testes rápidos.

### Community 147 - "useAuthStore.ts"
Cohesion: 0.28
Nodes (8): ACCESS_COOKIE, ACCESS_HEADER, AuthState, AuthStatus, base64UrlDecode(), isTokenExpired(), jwtExpiry(), SessionMode

### Community 148 - "compute_capability_digest"
Cohesion: 0.25
Nodes (9): arquivos_do_digest(), compute_capability_digest(), Path, Arquivos que compõem o digest, em ordem estável. A ordem é a do caminho…, SHA-256 do conteúdo do diretório da capability, exceto o `manifest.yaml`. O…, A porta da automodificação silenciosa (`plan.md` §6), fechada e testada., O manifest guarda o próprio digest; incluí-lo tornaria o valor impossível.…, test_digest_ignora_o_manifest_e_o_pycache() (+1 more)

### Community 149 - "2. Interface (UI) e Estabilidade Corrigidas"
Cohesion: 0.25
Nodes (7): 1. Conexão do Agente e Cloudflare Access Resolvidos, 2. Interface (UI) e Estabilidade Corrigidas, A. Comunicação Síncrona do Chat, B. Histórico (HistoryPage), C. Neural Map (BrainPage) Otimizado, Relatório da Sessão: Jarvis & Infraestrutura, Status Atual

### Community 150 - "build_memory_system"
Cohesion: 0.32
Nodes (8): build_memory_system(), build_vector_store(), Path, Lê o backend da configuração. Valor desconhecido falha nomeando os válidos., Constrói o adapter escolhido. Nada de `lancedb` é importado no caminho `memory`., Os cinco níveis prontos para injeção, com persistência em disco. `short_term`…, vector_backend(), VectorBackend

### Community 151 - "GoalBlocker"
Cohesion: 0.25
Nodes (6): GoalBlocker, Consumidor de `capability.gap_detected`: move o goal pai para `blocked`. Assine…, O aceite da v1.1 inteiro em um teste (`plan-execution.md` §3). (a)…, Miss vindo do chat solto não tem goal pai — e não pode inventar um., test_gap_sem_goal_nao_bloqueia_nada(), test_miss_publica_gap_bloqueia_o_goal_e_nao_sobe_excecao()

### Community 152 - "ChatPage.tsx"
Cohesion: 0.47
Nodes (5): aplicarTexto(), ChatMessage, ChatPage(), useChat(), WsChunk

### Community 153 - "exemplo_nas — capability de exemplo do SDK"
Cohesion: 0.33
Nodes (5): Credenciais e ambiente, Estado, exemplo_nas — capability de exemplo do SDK, O que copiar daqui, O que faz

### Community 155 - "tools.py"
Cohesion: 0.40
Nodes (4): list_tools(), get, Rota de tools — lista tools registradas., Retorna lista de tools disponíveis.

### Community 156 - "mobile/tsconfig.json"
Cohesion: 0.40
Nodes (4): compilerOptions, strict, extends, expo/tsconfig.base

### Community 157 - "restore.sh"
Cohesion: 0.60
Nodes (3): die(), info(), restore.sh script

### Community 158 - ".escopo_de_escrita"
Cohesion: 0.40
Nodes (3): Capability, Path, Onde a capability poderia escrever: o diretório dela mais a concessão.

### Community 159 - "capability_id"
Cohesion: 0.40
Nodes (5): capability_id(), Id estável derivado do nome — a chave da capability em disco. `uuid4()` a cada…, Id derivado do nome: sem isso cada boot criaria uma linha nova na tabela., test_id_da_capability_e_estavel_entre_descobertas(), test_persist_grava_o_catalogo_descoberto()

### Community 160 - "test_resolve_miss_publica_gap_no_bus_sem_levantar"
Cohesion: 0.30
Nodes (5): parametrize, O miss é um fato publicado, não um erro propagado., `status` é decisão humana, `health` é consequência medida — não se misturam., test_health_e_estado_medido_e_nao_status(), test_resolve_miss_publica_gap_no_bus_sem_levantar()

### Community 161 - "cap_loop.py"
Cohesion: 0.50
Nodes (3): handler(), Any, Capability que nunca termina. Existe para provar que o supervisor a mata. Laço…

### Community 162 - "cap_ok.py"
Cohesion: 0.50
Nodes (3): handler(), Any, Capability de exemplo que funciona. Roda de verdade, em subprocesso. Mora sob…

### Community 163 - "cap_rede.py"
Cohesion: 0.50
Nodes (3): handler(), Any, Capability que tenta sair para a rede. Existe para provar que ela não sai. Usa…

### Community 164 - "test_evento_de_gap_carrega_intencao_contexto_e_goal"
Cohesion: 0.33
Nodes (4): A v3.0 escreve a SPEC a partir deste payload; campo faltando é SPEC cega., Registry sem barramento continua sendo registry: o miss vira log., test_evento_de_gap_carrega_intencao_contexto_e_goal(), test_miss_sem_bus_configurado_nao_levanta()

## Knowledge Gaps
- **455 isolated node(s):** `Stack`, `Tab`, `TAB_GLYPH`, `navigationTheme`, `styles` (+450 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **27 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ToolSpec` connect `ToolSpec` to `GeminiProvider`, `ollama_provider.py`, `deps.py`, `Settings`, `InMemoryGoalStore`, `ToolExecutor`, `FakeLLMProvider`, `CapabilityPermissions`, `contracts.py`, `InMemoryEventBus`, `TavilyToolExecutor`, `conftest.py`, `GoalStore`, `test_memory_knowledge.py`, `Capability`, `Problema`, `runtime/base.py`, `ExecutionRequest`, `GoalStatus`, `capabilities/manifest.py`?**
  _High betweenness centrality (0.066) - this node is a cross-community bridge._
- **Why does `Event` connect `contracts.py` to `test_registry.py`, `FakeCapabilityStore`, `InMemoryGoalStore`, `KnowledgeBase`, `ToolExecutor`, `Kernel`, `FakeLLMProvider`, `GoalBlocker`, `jobs.py`, `InMemoryEventBus`, `conftest.py`, `GoalStore`, `test_memory_working.py`, `test_memory_knowledge.py`, `memory/__init__.py`, `registry.py`, `CapabilityRegistry`, `ExecutionRequest`, `ExperienceRecord`, `GoalStatus`, `InProcEventBus`, `SchedulerConfig`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Why does `CapabilityPermissions` connect `CapabilityPermissions` to `CapabilityRecord`, `Capability`, `Problema`, `CapabilityHarness`, `PermissionPolicy`, `registry.py`, `handlers.py`, `ExecutionRequest`, `GoalStatus`, `test_capability_sdk_manifest.py`, `contracts.py`, `capabilities/manifest.py`?**
  _High betweenness centrality (0.035) - this node is a cross-community bridge._
- **Are the 41 inferred relationships involving `ToolSpec` (e.g. with `TavilyToolExecutor` and `Capability`) actually correct?**
  _`ToolSpec` has 41 INFERRED edges - model-reasoned connections that need verification._
- **Are the 22 inferred relationships involving `CapabilityPermissions` (e.g. with `NasArquivos` and `Sonda`) actually correct?**
  _`CapabilityPermissions` has 22 INFERRED edges - model-reasoned connections that need verification._
- **Are the 9 inferred relationships involving `CapabilityRegistry` (e.g. with `ManifestLoadError` and `CatalogIndex`) actually correct?**
  _`CapabilityRegistry` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Are the 27 inferred relationships involving `Event` (e.g. with `InProcEventBus` and `Subscription`) actually correct?**
  _`Event` has 27 INFERRED edges - model-reasoned connections that need verification._