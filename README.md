# Jarvis — Sistema Operacional Cognitivo Pessoal

Um assistente pessoal single-user que recebe **objetivos**, não prompts. Ele
decompõe o objetivo em tarefas persistentes, escolhe as ferramentas, executa em
runtime isolado e retoma exatamente de onde parou depois de um restart.

Roda **na sua máquina**: Postgres, Redis e a API em Docker; inferência local via
LM Studio ou Ollama; a tela, o mouse e o teclado através de um servidor que roda
nativo no Windows. A nuvem é opcional — Gemini e Anthropic existem como provider
alternativo, não como dependência.

> Escrito em português. Código, comentários, commits e documentação seguem o
> mesmo idioma — é decisão de projeto, não descuido.

---

## O que ele faz hoje

| | |
|---|---|
| 🧠 **Objetivos → tarefas** | O Chief AI decompõe, persiste no Postgres e retoma após reinício |
| 🔀 **Event bus real** | Redis Streams com consumer groups, ack e re-entrega |
| 💾 **Memória de 5 níveis** | Short, Working, Long, Knowledge (RAG em LanceDB) e Experience |
| 🛠️ **Capabilities isoladas** | Rodam em subprocesso, com limite de disco e rede *aplicado*, não documentado |
| 🖱️ **Computer use** | Vê a tela, clica e digita quando nenhuma ferramenta dedicada resolve |
| 🎙️ **Voz** | STT (faster-whisper) → LLM → TTS (edge-tts / Gemini), com wake word |
| 👁️ **Multimodal** | Analisa imagens que você anexa e capturas que as próprias tools tiram |
| 🔌 **MCP** | Cliente multi-servidor; o agente pode até criar servidores MCP novos |
| 🔒 **Zero trust** | Cloudflare Tunnel + Access, com validação de JWT na API |

Estado detalhado e honesto do que está pronto versus planejado:
**[ESTADO_DO_PROJETO.md](ESTADO_DO_PROJETO.md)** — é o documento que manda sobre
a realidade do código.

---

## Arquitetura

```
                    ┌───────────────── Docker ─────────────────┐
  PWA (React)  ───► │  API (FastAPI)                           │
  Mobile (Expo) ──► │    ├─ ChiefAI ──► ToolExecutor ──► MCP ──┼──► host Windows
  Desk (Tauri)  ──► │    ├─ Kernel ───► capabilities (sandbox) │     (tela, mouse,
                    │    └─ Memory ──► Postgres + pgvector     │      teclado)
                    │  Orchestrator ─► Redis Streams           │
                    └──────────────────────────────────────────┘
                                     │
                            LM Studio / Ollama (local)
```

**Ports and adapters.** Nada no núcleo importa SDK de provider. Toda dependência
externa entra por uma porta em `packages/shared/ports.py`, e trocar de modelo,
de banco ou de transporte não toca em agente nenhum.

### O repositório

| Pasta | O que tem |
|---|---|
| `apps/api` | FastAPI: chat (WS), voz, memória, goals, tools, settings |
| `apps/web` | PWA em React + Vite — chat, mapa neural, memória, regras |
| `apps/mobile` | Cliente Expo/React Native (cliente fino, sem inferência local) |
| `apps/desk` | Shell desktop em Tauri |
| `packages/kernel` | Execução isolada de capability, permissões, runtime |
| `packages/agents` | ChiefAI, Executive, GoalManager, perfis e prompts |
| `packages/memory` | Os 5 níveis + indexação e RAG |
| `packages/llm` | `LLMProvider` e os adaptadores (Gemini, Anthropic, Ollama, OpenAI/LM Studio) |
| `packages/mcp` | Cliente MCP multi-servidor |
| `packages/registry` | Catálogo de capabilities e o *miss* determinístico |
| `capabilities/` | As "mãos": filesystem, shell, git, http, browser, python_runner, rag_search, memory_writer |
| `mcp/` | Servidores MCP. `main.py` agrega tudo e serve por SSE no host |
| `orchestrator/` | Loop de execução contínua, consumidor do event bus |
| `infrastructure/` | Docker Compose, Cloudflare Tunnel, config do LM Studio |

### Papéis de agente

Cada papel tem **prompt, ferramentas, temperatura e modelo próprios** — e a
restrição é aplicada no caminho da execução (`packages/agents/tool_guard.py`),
não confiada à boa vontade do prompt.

| Papel | Pode |
|---|---|
| `chief` | Tudo. O generalista que conversa com o dono |
| `planner` | Só leitura. Decompõe, não executa |
| `researcher` | Só leitura. Busca e verifica |
| `executor` | Único com ferramentas de ação |
| `reviewer` | Só leitura. Julga o resultado |
| `voice` | Como o chief, sem markdown e com frases curtas |

---

## Subir

**Requisitos:** Docker Desktop, Python 3.12+, e uma chave de LLM *ou* LM Studio
rodando localmente.

```bash
git clone https://github.com/VinciMaxmilian/jarvis && cd jarvis
cp .env.example .env          # preencha provider, modelo e chaves
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env up -d
```

- PWA em modo dev: <http://localhost:5173>
- PWA de produção (é este que o túnel publica): <http://localhost:5174>
- API: <http://localhost:8000/docs>

Parar, atualizar, resetar e as armadilhas conhecidas:
**[atualizar-docker.md](atualizar-docker.md)**.

### Computer use (opcional, roda fora do Docker)

Container não tem tela, mouse nem teclado — então esta parte roda nativa no
Windows e conversa com a API pela ponte SSE da porta 8765.

```powershell
uv sync --extra desktop
$env:DESKTOP_CONTROL_ENABLED='true'   # sem isto ele SÓ ENXERGA, não clica
.\scripts\run_desktop_host.ps1
```

Desligado por padrão de propósito. Com o interruptor ligado, o agente pode operar
sua máquina — as travas (sessão com prazo, lista de janelas proibidas, recusa em
campo de senha, confirmação para ação irreversível, auditoria com screenshot e
aborto pelo canto da tela) estão descritas em
**[plano_computer_use.md](plano_computer_use.md)**.

> **Modelo local precisa de tool calling de verdade.** Vários GGUF multimodais
> vêm com chat template sem bloco de tools, e o servidor descarta as ferramentas
> em silêncio — o agente então responde, com sinceridade, que não tem acesso ao
> seu computador. Diagnóstico e correção em
> [infrastructure/lmstudio/README.md](infrastructure/lmstudio/README.md).

---

## Desenvolvimento

```bash
uv sync --extra dev
uv run pytest tests/ -q          # ~550 testes, sem rede e sem Postgres
uv run ruff check .
uv run mypy packages/
```

A suíte não sobe banco nem chama provider externo: cada adaptador real tem um par
em memória em `tests/conftest.py` que implementa a **mesma porta**, e as portas
são `runtime_checkable` — dublê que sai do contrato falha na suíte, não em
produção.

### Grafo de conhecimento

O repo carrega um grafo em `graphify-out/` com estrutura de comunidades e
relações entre arquivos. Para perguntas sobre o código ele costuma ser mais
barato que grep:

```bash
graphify query "como as capabilities são executadas"
graphify path "ChiefAI" "CapabilityRegistry"
graphify update .        # depois de mexer no código
```

---

## Documentação

| Documento | Para quê |
|---|---|
| [ESTADO_DO_PROJETO.md](ESTADO_DO_PROJETO.md) | **Comece aqui.** O que está pronto, o que não está, e as divergências já resolvidas |
| [atualizar-docker.md](atualizar-docker.md) | Subir, parar, atualizar, resetar |
| [infrastructure/README.md](infrastructure/README.md) | Compose, migrations, Cloudflare Tunnel |
| [plano_computer_use.md](plano_computer_use.md) | Ver a tela, clicar e digitar — desenho e travas |
| [plano_mcp_externos.md](plano_mcp_externos.md) | Aba MCP Ext: Drive, Gmail e afins *(planejado)* |
| [plano-knowledge.md](plano-knowledge.md) | Memória, RAG e indexação |
| [plan.md](plan.md) · [plan-scheme.md](plan-scheme.md) · [tools.md](tools.md) | Visão original, layout e contratos de dados |

---

## Princípios

1. **Sem invenção.** Se o Jarvis não sabe fazer algo, ele bloqueia a tarefa e
   levanta `CapabilityGapDetected` — não improvisa uma resposta plausível.
2. **A restrição mora onde a execução passa.** Perfil que declara e não impede é
   pior que perfil nenhum: passa a sensação de segurança sem a segurança.
3. **Local primeiro.** A nuvem é alternativa, não requisito.
4. **Falha barulhenta.** Erro silencioso é o defeito mais caro deste projeto —
   cada um custou horas de investigação, e o comentário no código costuma contar
   qual foi.
5. **O comentário explica o porquê**, não o quê. Boa parte deles é o registro de
   um bug real que a linha acima resolve.

---

## Estado

Em desenvolvimento ativo, uso pessoal, sem release estável. A v1 (kernel,
memória, event bus, voz, PWA) está de pé; a v2 (capabilities úteis e papéis
especializados) está em curso; a v3 (auto-evolução — o Jarvis escrevendo as
próprias capabilities, com aprovação em dois portões) ainda não tem código.
