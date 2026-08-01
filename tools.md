# tools.md — Stack, Contratos e Decisões

Este arquivo define **o que é usado, quando entra e por quê**. A visão e o roadmap
conceitual estão em `plan.md`. A estrutura de pastas do repositório está em `plan-scheme.md`.
Nada aqui repete esses dois.

Sistema **single-user** (dono solo). Toda decisão abaixo assume isso.

Versões-alvo usadas na coluna "entra em":

| Versão | Entrega |
|---|---|
| v0 | Chat web → FastAPI → Chief AI → 1 tool real → Postgres → streaming. Localhost, sem auth. `docker compose up` + `pytest` verde. |
| v0.5 | Objetivos que sobrevivem: Goal Manager, Executive Function, checkpoint/resume. PWA básico. |
| v1 | Capability Registry, exposição externa (Cloudflare Tunnel + Access), memória, scheduler, backup, permissions em runtime, subprocesso, dry_run, Capability SDK. |
| v2 | Event bus (Redis Streams) + 2 a 3 capabilities escritas à mão. |
| v3 | Code Factory / self-evolution com os dois gates de aprovação. |

---

## 1. Stack por camada

### 1.1 Frontend web (PWA)

iOS nativo está **adiado**. O cliente é um PWA responsivo, usado tanto no desktop quanto no celular.

| Tecnologia | Papel | Entra em |
|---|---|---|
| React 19 | UI | v0 |
| Vite | build e dev server | v0 |
| TypeScript | tipagem | v0 |
| TailwindCSS | estilo | v0 |
| shadcn/ui | componentes base | v0 |
| TanStack Query | estado de servidor, cache de fetch | v0 |
| Zustand | estado local de UI | v0 |
| React Router | rotas | v0 |
| WebSocket nativo | streaming de tokens e eventos | v0 |
| Zod | validação de payloads no cliente | v0 |
| React Hook Form | formulários (spec de capability, config) | v1 |
| Manifest PWA + service worker | instalável no celular, offline básico | v0.5 |
| Web Push | notificação de tarefa longa e de aprovação | v2 |
| Framer Motion | animação | v2 |

### 1.2 Backend

| Tecnologia | Papel | Entra em |
|---|---|---|
| Python 3.12+ | runtime | v0 |
| FastAPI | HTTP + WebSocket | v0 |
| Uvicorn | ASGI server | v0 |
| Pydantic v2 | contratos de dados e validação | v0 |
| SQLAlchemy 2.x (async) | ORM sobre Postgres | v0 |
| Alembic | migrations | v0 |
| httpx (async) | cliente HTTP para providers e tools | v0 |
| structlog | log estruturado JSON | v0 |
| pytest + pytest-asyncio | testes, critério de aceite de milestone | v0 |
| asyncio | loop do orchestrator (não thread, não busy-loop) | v0 |
| APScheduler | jobs recorrentes (backup, indexação, limpeza) | v1 |
| python-jose ou pyotp | TOTP, só se Cloudflare Access não bastar | v1 (condicional) |
| Redis Streams (via redis-py) | event bus | v2 |

`Dependency Injector` foi **cortado**. FastAPI `Depends` cobre o caso de um app single-user;
adicionar um container de DI antes de existir dor é peso morto.

### 1.3 LLM e inferência

| Tecnologia | Papel | Entra em |
|---|---|---|
| Camada de abstração de provider (própria) | interface única, escolhida **antes** de qualquer provider | v0 |
| **LM Studio + `google/gemma-4-e2b`** | **provider principal**: Chief AI, planejamento, tool calling. Local, na LAN, fora do Docker | v0 (em uso) |
| Anthropic / OpenAI / Gemini via API | providers remotos atrás da mesma interface | v0 (em uso) |
| ~~KoboldCpp (nativo Windows, GPU)~~ | descartado: i5-3470 é pré-AVX2 | — |
| Ollama | último recurso, desligado. Fora do Docker; adapter pronto no repositório | v0 (selecionável) |
| Qwen2.5-VL 3B | visão: screenshots, PDFs escaneados, imagens | v2 |
| BAAI BGE-M3 | embeddings para LanceDB e memória longa | v1 |

Detalhe da interface na seção 3. Ordem de preferência declarada em
`apps/api/deps.py` — `lmstudio` → `gemini` → `anthropic` → `openai` → `ollama`;
nada consome essa ordem para failover automático ainda.

A premissa original ("o Chief AI roda em modelo forte via API; o local é só o
executor barato") caiu com o hardware: hoje o Chief AI roda no modelo local. Ela
volta a valer quando planejamento longo exigir mais do que o `gemma-4-e2b` entrega
— e a troca é uma entrada de configuração, não um refactor.

### 1.4 Dados

| Tecnologia | Papel | Entra em |
|---|---|---|
| PostgreSQL 16 | verdade transacional: goals, tasks, capabilities, mensagens, config | v0 |
| Redis 7 | cache, estado efêmero, locks | v1 |
| Redis Streams | event bus persistente com consumer groups | v2 |
| LanceDB (embarcado, arquivo local) | vetores: memória longa, RAG | v1 |
| pg_dump + snapshot de diretório LanceDB | backup, agendado via APScheduler | v1 |

Nada de servidor de vetores separado. LanceDB é embarcado, o backup é copiar o diretório.

### 1.5 RAG e parsing de documentos

| Tecnologia | Papel | Entra em |
|---|---|---|
| PyMuPDF | PDF: texto, imagens, metadados | v1 |
| python-docx / openpyxl / python-pptx | Office | v1 |
| Pillow | imagens | v1 |
| Chunking próprio (por heading e token) | segmentação antes do embedding | v1 |
| Unstructured | fallback para formatos exóticos | v2 |
| PaddleOCR | OCR local de imagem e PDF escaneado | v2 |

`Unstructured` entra tarde de propósito: dependência pesada, arrasta modelos e binários.
PyMuPDF cobre a maioria dos casos reais.

### 1.6 Busca web, controle do computador, mídia

| Tecnologia | Papel | Entra em |
|---|---|---|
| Tavily API | busca web (a primeira tool real da v0) | v0 |
| Brave Search / Google CSE | providers alternativos de busca | v3 |
| Playwright | navegação automatizada e testes E2E | v2 |
| psutil | métricas de processo e sistema | v1 |
| watchdog | eventos de filesystem | v2 |
| pywin32 | integração Windows (janelas, shell, registro) | v2 |
| PyAutoGUI | controle de mouse e teclado | v3 |
| ffmpeg (binário) | conversão de áudio e vídeo | v2 |
| LibreOffice headless / Pandoc | conversão de documentos | v2 |
| faster-whisper | STT | v3 |
| Piper TTS | TTS | v3 |

### 1.7 Observabilidade

| Tecnologia | Papel | Entra em |
|---|---|---|
| structlog | log estruturado com `trace_id` e `goal_id` | v0 |
| prometheus-client | métricas expostas em `/metrics` | v1 |
| Prometheus | coleta | v2 |
| Grafana | dashboards: latência, tokens/s, fila, falhas | v2 |
| OpenTelemetry | tracing distribuído | v3 |

Na v0, "observabilidade" é log estruturado e nada mais. Prometheus sem carga real não mede nada.

### 1.8 Containers e qualidade

| Tecnologia | Papel | Entra em |
|---|---|---|
| Docker Compose | postgres, redis e serviços auxiliares | v0 |
| Ruff | lint + import sorting (substitui isort) | v0 |
| Black | formatação | v0 |
| mypy (modo estrito nos pacotes de contrato) | tipos | v0 |
| pytest | testes | v0 |
| Playwright | E2E do PWA | v2 |
| GitHub Actions | CI: lint, mypy, pytest | v1 |

`isort` foi cortado: Ruff faz o mesmo com `--select I`.

---

## 2. Contratos de dados

Fonte única de verdade: modelos Pydantic v2 em `packages/shared/contracts.py`.
As tabelas do Postgres derivam desses modelos; o schema TypeScript do frontend é gerado do OpenAPI.
Nenhum dicionário solto atravessa fronteira de módulo.

```python
from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, Field


class GoalStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    BLOCKED = "blocked"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Goal(BaseModel):
    id: UUID
    title: str
    description: str = ""
    status: GoalStatus = GoalStatus.DRAFT
    priority: int = Field(default=50, ge=0, le=100)
    parent_goal_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class Task(BaseModel):
    id: UUID
    goal_id: UUID
    title: str
    status: TaskStatus = TaskStatus.PENDING
    capability: str | None = None      # nome da capability que executa
    tool: str | None = None            # nome da tool dentro da capability
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    error: str | None = None
    depends_on: list[UUID] = Field(default_factory=list)
    attempts: int = 0
    max_attempts: int = 3
    dry_run: bool = False
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class Event(BaseModel):
    id: UUID
    type: str                          # "task.completed", "capability.installed", ...
    source: str                        # módulo emissor
    payload: dict[str, Any] = Field(default_factory=dict)
    goal_id: UUID | None = None
    task_id: UUID | None = None
    trace_id: str
    created_at: datetime


class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]       # JSON Schema, compatível com MCP
    output_schema: dict[str, Any] | None = None
    idempotent: bool = False
    requires_approval: bool = False


class CapabilityPermissions(BaseModel):
    network: list[str] = Field(default_factory=list)   # hosts ou IPs; [] = sem rede
    filesystem: list[str] = Field(default_factory=list)  # paths absolutos permitidos
    process: bool = False              # pode iniciar subprocessos externos


class CapabilityStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    ACTIVE = "active"
    DISABLED = "disabled"


class CapabilityManifest(BaseModel):
    name: str                          # slug único, ex.: "nas_sync"
    version: str                       # semver
    description: str
    status: CapabilityStatus = CapabilityStatus.PENDING_APPROVAL
    approved_commit: str | None = None # SHA do commit aprovado no Gate 2
    entrypoint: str                    # "capabilities.nas_sync.server:main"
    transport: Literal["mcp_stdio", "python"] = "mcp_stdio"
    permissions: CapabilityPermissions = Field(default_factory=CapabilityPermissions)
    tools: list[ToolSpec] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)  # pacotes pip
    created_at: datetime
    updated_at: datetime
```

Regras que o registry aplica sobre esses contratos:

- `CapabilityRegistry.resolve(intent)` é **determinístico**: casa a intenção contra os `ToolSpec`
  registrados. Miss em `resolve()` é o único gatilho de gap de capacidade. O LLM nunca declara
  "não tenho essa ferramenta".
- Só carrega capability com `status == active`.
- Antes de carregar, recalcula o hash do diretório da capability e compara com `approved_commit`.
  Código alterado depois da aprovação é recusado e a capability volta para `pending_approval`.
- Cada capability nasce na branch `capability/<name>`. Merge só após o Gate 2.
  Desinstalar é `git revert` do merge commit.

Exemplo de `manifest.yaml` no disco (serializa exatamente o modelo acima):

```yaml
name: nas_sync
version: 0.1.0
description: Lista e sincroniza arquivos com o NAS local.
status: pending_approval
approved_commit: null
entrypoint: capabilities.nas_sync.server:main
transport: mcp_stdio
permissions:
  network: ["192.168.1.50"]
  filesystem: ["D:/backup/nas"]
  process: false
tools:
  - name: nas_list
    description: Lista arquivos em um diretório do NAS.
    input_schema:
      type: object
      properties:
        path: { type: string }
      required: [path]
    idempotent: true
    requires_approval: false
dependencies: ["smbprotocol>=1.10"]
```

---

## 3. Camada de abstração de LLM

Escrita **antes** do primeiro provider. Nenhum módulo importa SDK de provider diretamente;
todos dependem de `LLMProvider`.

```python
from typing import Any, AsyncIterator, Literal, Protocol
from pydantic import BaseModel


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class Completion(BaseModel):
    text: str
    tool_calls: list[ToolCall] = []
    input_tokens: int
    output_tokens: int
    model: str
    finish_reason: str


class LLMProvider(Protocol):
    name: str

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> Completion: ...

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
    ) -> AsyncIterator[str]: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

Um provider que não suporta uma operação levanta `UnsupportedOperation`; quem chama decide o fallback.
Tool calling é normalizado para `ToolCall`, que usa o mesmo `input_schema` do MCP.

| Provider | Uso | Entra em |
|---|---|---|
| **LM Studio (`OpenAIProvider`, base_url própria)** | **Chief AI hoje**: planejamento, raciocínio, tool calling | v0 (em uso) |
| Anthropic / OpenAI / Gemini (API) | alternativas remotas, mesma interface | v0 (em uso) |
| Ollama (`/api/chat` nativa) | último recurso; fora do Docker | v0 (selecionável) |
| ~~KoboldCpp~~ | descartado por AVX2 | — |
| BGE-M3 local | `embed()` | v1 |
| Qwen2.5-VL 3B | entrada multimodal | v2 |

`OpenAIProvider.embed()` levanta `UnsupportedOperation` de propósito. O LM Studio
desta máquina serve `text-embedding-nomic-embed-text-v1.5`, então o caminho existe
— o que falta é decidir se o embedding sai do mesmo provider do chat ou de um
dedicado. Decisão da v1.3 (memória `knowledge` + LanceDB), não desta seção.

Roteamento (v1): `complexidade da task → provider`. Planejamento e escrita de código vão para API;
classificação, extração e resumo vão para o local. A escolha fica em config, não no código.

---

## 4. Segurança

### 4.1 Resolvido por configuração, sem código

**Cloudflare Access (Zero Trust, free tier) na frente do Cloudflare Tunnel.** Entra na v1.

| Preocupação | Como fica resolvida |
|---|---|
| Login | Identidade Google/GitHub validada pelo Cloudflare antes de o request chegar na origem |
| Sessão e expiração | Política de sessão do Access |
| MFA | Delegado ao provedor de identidade |
| HTTPS e certificado | Terminado no túnel |
| Exposição de porta | Nenhuma. O túnel é saída, não entrada |
| Rate limiting de borda | Regras do Cloudflare |
| Revogação de acesso | Remover o e-mail da policy |

A origem aceita conexão apenas do conector do túnel, em `127.0.0.1`.
O header `Cf-Access-Authenticated-User-Email` é validado no backend contra o e-mail único do dono —
verificação de uma linha, não uma camada de auth.

### 4.2 Sobra para o código

| Item | O que faz | Entra em |
|---|---|---|
| `permissions.yaml` checado em runtime | wrapper de FS e rede nega qualquer path ou host fora da lista do manifest | v1 |
| Subprocesso por capability | cada capability roda em processo separado, com env mínimo e timeout | v1 |
| `dry_run` na primeira execução | primeira invocação de toda tool nova roda sem efeito colateral e devolve o que faria | v1 |
| Validação do header do Access | confirma o e-mail do dono | v1 |
| TOTP | só se surgir um caminho que não passe pelo Access (webhook, callback) | condicional |
| Gate 1 e Gate 2 | aprovação de capability gerada (ver seção 6) | v3 |

Não há sandbox em container. O enforcement é subprocesso + wrapper de permissões + dry_run.
Container por capability é possível depois, mas custa mais do que resolve num sistema single-user.

### 4.3 Cortado

| Cortado | Motivo |
|---|---|
| Argon2 + fluxo de senha | não há senha; identidade vem do Access |
| JWT próprio + refresh token + rotação | sessão é do Cloudflare |
| Signup, reset de senha, verificação de e-mail | um usuário, criado à mão |
| RBAC e papéis | um usuário, todos os direitos |
| Multi-tenancy | um dono |
| Device registry e aprovação de dispositivo | policy do Access cobre |
| Passkeys | mesma coisa, na borda |
| Audit log de compliance | log estruturado basta; não há auditor |
| Caddy como reverse proxy externo | o túnel já termina TLS; Caddy só se houver acesso LAN direto |

---

## 5. Infraestrutura e docker-compose alvo

**O runtime de inferência fica fora do Compose**, seja qual for. Vale para o LM
Studio (na LAN, alcançado pelo IP) e para o Ollama (no host, alcançado por
`host.docker.internal` — os serviços Python mantêm o `extra_hosts` para isso).
Motivo: modelo de vários GB em volume Docker com passthrough de GPU custa muito
mais do que apontar uma URL, e foi a reserva NVIDIA no compose que derrubava o
`up` inteiro em máquina sem o toolkit.

| Serviço | Entra em | Nota |
|---|---|---|
| postgres:16-alpine | v0 ✅ | porta publicada só em `127.0.0.1:5433`, healthcheck `pg_isready`, senha por `.env` |
| redis:7-alpine | v0 ✅ | `appendonly yes` desde já; cache na v1, Streams na v2 |
| migrate (one-shot) | v0 ✅ | `alembic upgrade head` e morre; `api`/`orchestrator` esperam `service_completed_successfully` |
| api (FastAPI) | v0 ✅ | healthcheck em `/health`; o `web` espera ela ficar *healthy* |
| orchestrator | v0 ✅ | sem healthcheck: não expõe porta, e "processo vivo" sempre passa |
| web (Vite/PWA) | v0 ✅ | proxy `/api` por `VITE_PROXY_TARGET=http://api:8000` |
| test (profile `test`) | v0 ✅ | `pytest`/`mypy`/`ruff`; `run --rm`, nunca `up` |
| cloudflared | v1 | conector do túnel, token por `.env` |
| prometheus | v2 | scrape do `/metrics` da API |
| grafana | v2 | dashboards provisionados por arquivo, versionados |
| caddy | condicional | só se houver acesso LAN direto sem túnel |

### Dívida do compose atual

O arquivo `infrastructure/docker/docker-compose.yml` está com quatro defeitos:

| Defeito | Correção |
|---|---|
| `version: '3.8'` | obsoleto na Compose Spec; remover a chave |
| Nenhuma porta publicada | publicar `127.0.0.1:5432:5432` e `127.0.0.1:6379:6379`, para migration e inspeção local |
| Sem healthcheck | `pg_isready` no postgres e `redis-cli ping` no redis, com `depends_on: condition: service_healthy` |
| Senha hardcoded (`user` / `password`) | mover para `.env` (`POSTGRES_PASSWORD`), versionar apenas `.env.example` |

Também: `postgres:14-alpine` e `redis:6-alpine` estão atrás; subir para 16 e 7.

---

## 6. Qualidade e CI

- **`pytest` verde é o critério de aceite de cada milestone.** Milestone sem teste que prove o
  caminho feliz de ponta a ponta não é entregue. Na v0, o teste é: request no chat → Chief AI →
  chamada de tool → persistência do Goal e da Task → resposta em stream.
- `ruff check` + `ruff format` (ou Black) + `mypy` rodam no pre-commit e na CI.
- `mypy --strict` obrigatório em `packages/shared/contracts.py` e na camada de LLM. O resto é gradual.
- Todo schema muda por **migration Alembic**. `create_all()` não é usado nem em dev; divergência
  entre modelo e banco é bug de produção esperando data.
- `.env.example` é versionado e lista toda variável exigida: `DATABASE_URL`, `REDIS_URL`,
  `ANTHROPIC_API_KEY`, `TAVILY_API_KEY`, `KOBOLD_URL`, `CF_ACCESS_EMAIL`, `LANCEDB_PATH`.
  O `.env` real fica no `.gitignore`. A app falha no boot se faltar variável obrigatória —
  validação por `pydantic-settings`.
- Testes de capability rodam em `dry_run` na CI; nenhum efeito colateral externo em pipeline.

### Gates de aprovação (v3)

| Gate | Onde | O que mostra | Decisão |
|---|---|---|---|
| Gate 1 | celular | spec em yaml: nome, tools, `input_schema`, permissões pedidas, estimativa | aprova a intenção antes de gerar código |
| Gate 2 | desktop | `git diff` completo, saída do `pytest`, imports fora do que o spec declarou, resultado do `dry_run` | aprova o merge; grava `approved_commit` |

---

## 7. Decisões resolvidas (ADR resumido)

| Decisão | Escolha | Motivo | Alternativa descartada |
|---|---|---|---|
| Event bus | Redis Streams (v2) | Redis já está na stack; Streams dá persistência e consumer group sem novo serviço | NATS — só quando Redis doer de verdade |
| Workflow engine | Nenhum na v1; estado em Postgres + retry na Task | Temporal traz server, worker e SDK para orquestrar poucas tarefas por dia | Temporal |
| Padrão de tools | MCP | ecossistema pronto, `input_schema` JSON Schema, transporte stdio | integração proprietária por tool |
| Papel do Capability SDK | envelopa e expõe MCP | o SDK padroniza manifest, permissões e testes; a execução é MCP | SDK como protocolo próprio substituindo MCP |
| Auth | Cloudflare Access na borda | single-user; login, MFA, sessão e TLS viram configuração, não código | Argon2 + JWT + refresh + device registry |
| Isolamento de execução | subprocesso + `permissions.yaml` em runtime + `dry_run` | dá contenção real com custo baixo e debug simples | container por capability, gVisor |
| Modelo do Chief AI | modelo forte via API atrás da abstração | planejamento e geração de código exigem qualidade que 8B local não entrega | Qwen3 8B local como cérebro |
| Modelo local | Qwen3 8B GGUF em KoboldCpp | tarefas de alto volume e baixo valor sem custo por token | tudo via API |
| Cliente mobile | PWA responsivo primeiro | um código, sem App Store, sem Xcode, sem conta de dev | app SwiftUI nativo na v1 |
| Vetores | LanceDB embarcado | arquivo local, backup é copiar diretório | Qdrant, Weaviate, pgvector |
| Trigger de self-evolution | miss determinístico em `CapabilityRegistry.resolve()` | LLM decidindo quando escrever código é gerador de trabalho fantasma | o LLM declarar que falta ferramenta |
| Self-evolution na v3 | depois de o SDK estabilizar | gerar código contra um contrato instável produz lixo | v1 |
| DI framework | FastAPI `Depends` | um app, um dono; container de DI é abstração sem dor correspondente | Dependency Injector |

---

## 8. Dívida técnica conhecida

| # | Onde | Problema | O que fazer |
|---|---|---|---|
| D1 | `orchestrator/main.py` | Importa 4 módulos que não existem: `packages.agents.chief_ai`, `packages.memory`, `packages.goal_manager`, `infrastructure.message_bus`. O arquivo não roda. | Reduzir à v0: um entrypoint asyncio que só instancia o que existe. Módulo inexistente sai do import até ter código. |
| D2 | `orchestrator/main.py` | Busy-loop síncrono com `time.sleep(5)` dentro de `while True`, num sistema declarado event-driven. Latência mínima de 5s, uma thread bloqueada, `import time` dentro do loop. | Reescrever em asyncio: `async def run()` consumindo uma fila (`asyncio.Queue` na v0, Redis Streams na v2). Sem polling; sem sleep no caminho quente. |
| D3 | `orchestrator/main.py` | Comentário afirma NATS como Event Bus, contradizendo a decisão de Redis Streams. | Remover a referência a NATS. |
| D4 | `docker-compose.yml` | `version: '3.8'` obsoleto. | Remover a chave. |
| D5 | `docker-compose.yml` | Nenhuma porta exposta; impossível rodar Alembic ou inspecionar o banco do host. | Publicar `127.0.0.1:5432` e `127.0.0.1:6379`. |
| D6 | `docker-compose.yml` | Sem healthcheck; a API sobe antes de o Postgres aceitar conexão. | `pg_isready` e `redis-cli ping` + `depends_on: condition: service_healthy`. |
| D7 | `docker-compose.yml` | Credenciais hardcoded (`user` / `password`). | Mover para `.env`, versionar `.env.example`. |
| D8 | `docker-compose.yml` | `postgres:14`, `redis:6` desatualizados. | Subir para `postgres:16-alpine` e `redis:7-alpine` antes de existir dado a migrar. |
| D9 | repositório | Não há `contracts.py`; os modelos existem apenas em prosa. | Criar `packages/shared/contracts.py` com a seção 2 e apontar SQLAlchemy e OpenAPI para lá. |
| D10 | repositório | Não há `.env.example` nem validação de config no boot. | Criar `.env.example` e `Settings(BaseSettings)` que falha no boot com variável faltando. |
