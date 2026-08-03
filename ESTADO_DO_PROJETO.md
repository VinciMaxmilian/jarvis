# Jarvis — Estado Definitivo do Projeto (Agosto 2026)

Este documento unifica e substitui os relatórios anteriores de planejamento e execução (`plan.md`, `plan-execution.md`, `plan-scheme.md`, `HANDOFF.md`, `31-07-handoff.md`, `jarvis_report.md` e `plano_voz.md`). Ele reflete **o que realmente está implementado** no código hoje e quais são as próximas metas da arquitetura.

## 1. O que já está PRONTO e FUNCIONANDO (Fase v1 Completa)

A fundação do Jarvis como Sistema Operacional Cognitivo (v1) está 100% testada e em operação (cobertura total de `pytest` e tipagem estrita com `mypy`):

### 🧠 Kernel e Orquestração
- **Chief AI e Executive Function:** Entende objetivos, decompõe em tarefas (Tasks) persistentes no Postgres, e retoma exatamente de onde parou após reinícios.
- **Capability Registry e Miss Determinístico:** Resolve as intenções perfeitamente. Se o Jarvis não sabe fazer algo, em vez de inventar, ele bloqueia a tarefa e levanta o evento `CapabilityGapDetected`.
- **Isolamento de Runtime:** As capabilities rodam em subprocessos separados. O enforcement de limites de disco (`filesystem`) e rede (`network`) foi testado em tempo real e bloqueia chamadas não autorizadas.
- **Capability SDK:** Completamente estruturado, testado e capaz de gerar manifestos limpos para a criação de novas capacidades.

### 💾 Memória de 5 Níveis
Todos os níveis da arquitetura operam em conjunto:
- **Short:** O contexto da sessão atual.
- **Working:** Checkpoints das tarefas em andamento.
- **Long:** Fatos duráveis do sistema e usuário.
- **Knowledge:** RAG incremental rápido construído no LanceDB.
- **Experience:** Extrato comportamental retirado de falhas anteriores.

### ⚙️ Infraestrutura e Rede Segura
- **Banco e Fila:** Postgres e Redis operacionais subindo automáticos com migrations validadas via Docker Compose.
- **Zero Trust:** Cloudflare Tunnel configurado localmente. O Cloudflare Access filtra as requisições externamente e a API valida ativamente os JWTs assinados (validando o `aud` e domínio), fechando portas locais vulneráveis.
- **Scheduler e Automações:** Jobs agendados nativos efetuam a reindexação do conhecimento, limpeza de logs e o processo de backup e restore, sem a necessidade de scripts externos.

### 🖥️ Frontend (PWA Web)
- Interface empacotada no Vite + React com alto desempenho de renderização (React.memo usado pesadamente no Neural Map/Graphify).
- **Conexões WS Resilientes:** Vazamento de WebSockets do chat eliminado; reconexão imediata e sem abas zumbis.
- Histórico operante e limpo, integrado ao banco.

---

## 2. O que está EM ANDAMENTO ou PENDENTE (O Futuro — v2 e v3)

O foco do projeto mudou de "criar o motor" para "ensinar o motor a andar" e deixá-lo evoluir:

### 🛠️ Fase v2: Capabilities e Event Bus
- **Capabilities Escritas à Mão:** Desenvolver e manter ativas as 3 primeiras capabilities úteis no SDK. *Passo obrigatório antes da automação.*
- **Event Bus Definitivo:** Migrar o transporte interno para `Redis Streams` visando garantir *consumer groups*, *acks* e re-entrega de eventos robusta.
- **Papéis de Agentes Dinâmicos:** Distribuir o "Chief AI" em perfis (Planner, Executor, Reviewer) carregando prompts especialistas de arquivos, permitindo o uso de ferramentas específicas para cada modelo (ex: o Planner não roda código).

### 🧬 Fase v3: Self-Evolution (A Grande Fronteira)
- **Criação Autônoma:** Quando ocorre um "miss" e o objetivo trava, o Jarvis irá elaborar uma SPEC.
- **Aprovação Dual:** 
  1. *Mobile (Gate 1):* Uma notificação para aprovar a ideia superficialmente.
  2. *Desktop (Gate 2):* Aprovação detalhada da branch de código e visualização dos testes. O dry run obrigatório acontece na primeira execução da capability finalizada.

### 🎙️ Fase Sensorial: Voz com Gemini 3.1 Live API
- **Arquitetura A2A (Audio-to-Audio):** Em vez do antigo pipeline (STT → LLM Texto → TTS), a conversa será uma via única de baixa latência utilizando WebSocket com a `Live API` do Google. Jarvis ouvirá e responderá com voz nativa interpretando inclusive entonações e gerindo suas próprias interrupções.
- **Visão Computacional Multimodal:** Durante a conversação por voz, o agente será capaz de **enxergar as telas** do usuário.
- **Agência em Tempo Real com Histórico:** Com um histórico de contexto de 5 minutos, o Jarvis poderá atuar ativamente no computador a partir de um comando verbal, podendo:
  - Criar, editar, excluir e mover arquivos e pastas de forma orgânica.
  - Criar e editar diretamente documentos formatados como **DOCX, PDF, XLSX e CSV**.
- **Ingestão e Vetorização Contínua:** O agente ganhará uma ferramenta para receber arquivos ou **links** (ex: artigos completos da Wikipedia), vetorizá-los sob demanda e arquivá-los diretamente na pasta `data`, transformando a fonte em uma memória permanente e consultável.

### 📱 Fase Mobile (Companion App)
- O aplicativo de bolso. Tratará as submissões e navegação, atuando como o verdadeiro comunicador push para gerir o *Gate 1* da geração de capacidades.

---

## 3. Débitos Técnicos Residuais a Resolver
As tarefas menores que ficaram pendentes no último handoff:

1. Executar no bash: `graphify update .` para reconstruir o estado atualizado do conhecimento arquitetural.
2. Corrigir os 3 erros mínimos sintáticos pendentes apontados pelo Linter (`ruff check .`).
3. **Decisão pendente de Host:** Alterar o target do Cloudflare Tunnel de `:5173` (Vite dev server aberto) para uma versão empacotada de produção com Nginx (`:5174`).
4. Rotacionar e reinstalar o token do Tunnel que foi exposto publicamente no chat em iterações antigas.

---

## 4. Planos Possíveis e Diretrizes de Foco

### 1. Capabilities (Prioridade Máxima)
Sem capabilities úteis, o Kernel apenas orquestra. O esforço deve ser concentrado em construir as seguintes "mãos" para o Jarvis atuar:
- **Filesystem**
- **Python Runner**
- **Git**
- **Shell**
- **Browser**
- **HTTP**
- **RAG Search**
- **Memory Writer**
- **Planner Utilities**

### 2. Event Bus
Migrar completamente para **Redis Streams**. Isso abre espaço arquitetural para:
- Retries automáticos
- Consumer groups
- Múltiplos workers
- Distribuição futura de carga

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

*Nota: As ramificações de planejamento foram documentadas inteiramente. Ao realizar pesquisas e criar planos daqui para a frente, este documento ditará a realidade sobre o estado do projeto.*
