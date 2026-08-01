# Jarvis — Sistema Operacional Cognitivo Pessoal

Documento de visão, arquitetura conceitual e roadmap.

Escopo dos documentos irmãos:
- `tools.md` — stack, bibliotecas, versões e os contratos de dados (`Goal`, `Task`, `Event`, `CapabilityManifest`).
- `plan-scheme.md` — estrutura de pastas do repositório e layout em disco de cada capability.

Este arquivo não repete nenhum dos dois.

---

## 1. Objetivo

O Jarvis é um sistema operacional cognitivo pessoal: um processo permanente que recebe **objetivos**, não prompts. O dono declara o que quer alcançado; o sistema planeja, divide em tarefas, executa através de agentes e capabilities, persiste estado e retoma dias depois de onde parou.

A diferença central em relação a um assistente de chat: o objetivo é a unidade de trabalho e sobrevive ao fechamento da janela. O chat é apenas **um cliente** entre outros — o mesmo objetivo pode ser criado por um evento do sistema, pelo scheduler ou por outra capability.

A segunda diferença: quando falta uma ferramenta, o sistema não desiste nem improvisa. Ele detecta a lacuna, propõe a criação da capacidade que falta e, com aprovação humana, escreve e instala essa capacidade em si mesmo.

---

## 2. Premissas e restrições

Estas premissas justificam praticamente todos os cortes de escopo deste documento. Se alguma mudar, o roadmap muda junto.

| Premissa | Consequência de projeto |
|---|---|
| Dono solo, sem equipe | Nada de processo de contribuição, code owners, review de terceiros. Complexidade operacional é custo direto de tempo do dono. |
| Single-user real — só o dono acessa | Sem RBAC, multi-tenancy, signup, reset de senha, rotação de refresh token, device registry, audit de compliance. |
| Tempo parcial, noites e fins de semana | Milestones pequenos com critério de aceite binário. Nada que só funcione depois de três meses de construção. |
| Duas máquinas (casa e trabalho) | Git é o canal de sincronização. Estado durável em Postgres/LanceDB com backup, não em disco solto. |
| GPU local disponível | Inferência barata local vale a pena para tarefas simples, mas não para planejamento. |
| Sem redundância humana | Se o Postgres ou o LanceDB corromper, a memória do sistema morre. Backup entra na v1, não "depois". |

**Identidade fica na borda; a verificação, não.** Cloudflare Access (Zero Trust, free tier) na frente do Cloudflare Tunnel resolve login, MFA e revogação de sessão sem um IdP próprio. A camada de segurança própria (auth, zero trust formal, audit, sandbox, risk model) sai da v1 inteira — em `ia.atmosintelli.com.br`, o Jarvis publicado.

O que **não** sai é a verificação na origem. O backend não "assume que quem chegou até ele é o dono": ele valida a asserção que o Access assina (JWT em `Cf-Access-Jwt-Assertion`, assinatura contra o JWKS do time, `aud` da aplicação e e-mail do dono conferidos). A diferença importa porque o modo de falha da versão confiante é silencioso — um segundo túnel, um hostname mal configurado ou uma regra de ingress velha entregam a origem inteira sem que nada no log pareça errado. Validar custa uma dependência e um middleware; não validar custa tudo, uma vez.

---

## 3. Arquitetura em bloco

```
                          Dono
                            │
                    ┌───────┴────────┐
                    │  Cliente PWA   │  (chat, aprovações, dashboard)
                    └───────┬────────┘
                            │ HTTPS + WebSocket
                            │
              Cloudflare Access  (identidade, MFA)
                            │
              Cloudflare Tunnel  (sem porta aberta no roteador)
                            │
                  ┌─────────┴──────────┐
                  │   API Gateway      │  streaming, WS, push, rate limit
                  └─────────┬──────────┘
                            │
                  ┌─────────┴──────────┐
                  │      Chief AI      │  entende, planeja, delega, monitora
                  └─────────┬──────────┘
                            │
        ┌───────────────────┴───────────────────┐
        │      Event Bus  (Redis Streams)       │
        └───┬───────────┬───────────┬───────────┘
            │           │           │           │
        Agentes    Capability    Memória    Scheduler
                    Registry
            │           │           │           │
        └───────────────┴───────────┴───────────┘
                            │
              ┌─────────────┴──────────────┐
              │   Camada de LLM (provider) │
              │  API remota  |  local GGUF │
              └────────────────────────────┘
```

Todo componente abaixo do Event Bus é substituível sem tocar no Chief AI. O Chief AI fala com o barramento e com o registry, nunca com uma integração concreta.

---

## 4. Chief AI

O Chief AI **nunca executa nada**. Ele não abre arquivo, não chama API, não roda comando. Papel de CTO: decide o que precisa ser feito e por quem.

Responsabilidades: entender o objetivo declarado (inclusive fazer a pergunta de esclarecimento quando o objetivo é ambíguo), produzir um plano em tarefas, ordenar por dependência e prioridade, escolher o agente ou capability para cada tarefa, acompanhar execução, reagir a falha e registrar o resultado na memória de experiência.

A separação é o que torna o sistema auditável: toda ação com efeito no mundo passa por uma capability registrada, com permissões declaradas e log próprio. Se o Chief AI pudesse executar direto, não haveria onde aplicar permissão.

Por isso o Chief AI roda no modelo mais forte disponível (ver seção 12): planejamento e escolha de ferramenta são exatamente as tarefas onde modelo fraco falha de forma cara e silenciosa.

---

## 5. Executive Function e Goal Manager

O Goal Manager guarda objetivos como entidades persistentes com ciclo de vida próprio (`Goal` e `Task` estão especificados em `tools.md`). Um objetivo criado hoje pode ser retomado na semana que vem, da outra máquina, no ponto exato onde parou.

A Executive Function é a camada de controle sobre esses objetivos: fila de tarefas, dependências entre tarefas, prioridade, o que está bloqueado esperando aprovação humana, e o que fazer quando uma tarefa falha.

**v1 entrega:** objetivo persistido, decomposição em tarefas, fila serial, dependências simples (tarefa B espera tarefa A), retry com limite, checkpoint por tarefa concluída, resume após restart do processo, e estado `blocked` para tarefa esperando o dono.

**Depois da v1:** execução paralela de tarefas independentes, interrupção e repriorização de objetivo em andamento, objetivos de longa duração em background (modo pesquisa autônoma: o sistema trabalha uma semana num tema e entrega relatório consolidado).

Sem Temporal. O ganho do Temporal — workflow durável com retomada automática — é real, mas cobrado em um serviço a mais para operar, um SDK a mais para aprender e um modelo mental a mais para depurar. Com fila em Postgres e checkpoint por tarefa, uma pessoa sozinha alcança 80% disso em uma fração do tempo.

---

## 6. Capability Registry

A pergunta que o sistema faz mudou. Não é mais "tenho a ferramenta X?", é "tenho a capacidade de fazer isto? se não tenho, posso criá-la?".

O registry mantém o catálogo de tudo que o sistema sabe fazer. Cada entrada tem manifest, permissões, versão, dependências, estado e log. O contrato do `CapabilityManifest` está em `tools.md`; o layout em disco está em `plan-scheme.md`.

### resolve() e o miss determinístico

```
CapabilityRegistry.resolve(intent) -> Capability | MISS
```

`resolve()` casa a intenção da tarefa contra as capabilities `active` do registry. É código determinístico — matching sobre o catálogo, não julgamento do modelo.

Quando dá **MISS**:

1. A tarefa **para**. Não há fallback improvisado, não há "tenta com shell", não há o modelo inventando um caminho alternativo.
2. O registry emite o evento `CapabilityGapDetected` com a intenção que falhou e o contexto da tarefa.
3. O objetivo pai vai para `blocked`.

Essa é a **única** porta de entrada da auto-evolução. O LLM nunca decide sozinho que precisa criar uma capability nova — se decidisse, geraria uma capability duplicada por semana, cada uma com nome diferente para a mesma coisa, e o registry viraria lixo em um mês. O gatilho é sempre o miss, e o miss é sempre determinístico.

O registry também recusa carregar uma capability cujo código no disco não bate com o `approved_commit` do manifest (ver seção 8). Isso fecha a porta da auto-modificação silenciosa: o sistema não consegue editar uma capability já aprovada sem passar de novo pelos gates.

---

## 7. Capability SDK e ciclo de vida

Cada capability é um mini software com fronteira explícita: manifest, permissões declaradas, schema de entrada e saída, implementação, testes.

**MCP é o padrão de tools.** O Capability SDK **envolve e expõe** MCP, não o substitui. Uma capability pode consumir um servidor MCP existente ou expor as próprias ferramentas via MCP. O SDK adiciona o que o MCP não cobre para este caso: manifest com estado e aprovação, permissões declaradas com enforcement local, e o ciclo de vida abaixo. Adotar MCP evita reescrever integrações que a comunidade já mantém.

Ciclo de vida:

| Operação | O que acontece |
|---|---|
| Instalar | Código entra por merge da branch `capability/<name>`; registry carrega o manifest e valida `approved_commit`. |
| Atualizar | Nova versão passa pelos mesmos dois gates. Sem exceção para "mudança pequena". |
| Desativar | `status: disabled`. Código continua no repo, `resolve()` ignora. Reversível em um comando. |
| Remover | `git revert` do merge. Desinstalar é uma operação de git, não um estado de banco. |

Não há marketplace, publicação nem compartilhamento. O sistema tem um usuário; uma loja de capabilities seria construir infraestrutura de distribuição para uma pessoa. O efeito colateral bom do modelo baseado em git: casa e trabalho sincronizam sozinhos, sem nenhum código de sync.

---

## 8. Self-Evolution

Esta é a funcionalidade central do projeto e é um **objetivo confirmado e desejado**, não um experimento. Ela fica na v3 por **dependência técnica**, não por receio: o registry, o SDK, o schema de tool, a suíte de pytest e a automação de git precisam existir e estar estáveis antes, porque a geração automática escreve exatamente contra esses contratos. Gerar código contra um contrato que ainda muda toda semana produz capability quebrada e retrabalho.

### Fluxo completo

```
CapabilityGapDetected
        │
        ▼
  Geração da SPEC          (yaml curto, barato, sem código ainda)
        │
        ▼
  GATE 1 — aprovação da spec        [celular, push]
        │  reprovado → objetivo fica blocked, fim
        ▼
  Geração do código em branch capability/<name>
        │
        ▼
  pytest + dry_run
        │
        ▼
  GATE 2 — aprovação do código      [desktop]
        │  reprovado → branch descartada
        ▼
  merge em main
        │
        ▼
  Registro no registry (status: approved, approved_commit gravado)
        │
        ▼
  Primeira execução obrigatoriamente em dry_run
        │
        ▼
  status: active — capability disponível para resolve()
```

### Por que dois gates

Um gate só seria uma escolha ruim nos dois sentidos. Se o gate ficasse antes da geração, o dono aprovaria código que ainda não existe — assinando em branco. Se ficasse depois, o sistema teria gastado tokens gerando uma capability que talvez fosse rejeitada por ser uma má ideia desde o começo, e o dono estaria lendo diff no celular.

**Gate 1 — spec.** Curto o bastante para ser aprovado por push notification, no celular, em dez segundos. Responde: isto deveria existir?

```yaml
name: nas_smb
description: Ler, listar e gravar arquivos no NAS de casa via SMB.
trigger_intent: "acessar arquivos do NAS"
permissions:
  filesystem: []                  # nenhum acesso ao disco local
  network:
    - host: 192.168.1.50          # IP fixo do NAS, nada além disso
      ports: [445]
  subprocess: false
dependencies:
  - smbprotocol
estimated_effort: 15min
```

O que interessa na spec: o nome, o que faz, **o que ela vai poder tocar**, do que depende e quanto custa. `filesystem: []` e uma rede restrita a um IP são exatamente o tipo de coisa que se lê numa tela de celular e se avalia sem contexto adicional.

**Gate 2 — código.** Só no desktop. Diff não se lê em tela de celular, e aprovar diff mal lido é pior do que não ter gate. Mostra, obrigatoriamente:

1. O `git diff` completo da branch `capability/<name>`.
2. O resultado do `pytest` (verde é pré-requisito para o gate ser oferecido).
3. A lista de imports presentes no código que **não** estavam declarados no spec — é aqui que aparece a capability que pediu SMB e importou `requests`.
4. O log do `dry_run`: exatamente quais operações ela executaria, com quais argumentos.

Aprovação em Gate 2 dispara merge, gravação do `approved_commit` no manifest e registro. Reprovação descarta a branch.

### Estado do manifest

| status | Significado |
|---|---|
| `pending_approval` | Spec aprovada, código gerado, aguardando Gate 2. Não carregável. |
| `approved` | Merged e registrada, ainda não passou pelo dry_run inicial. |
| `active` | Disponível para `resolve()`. |
| `disabled` | Desligada manualmente; código presente, ignorada pelo registry. |

`approved_commit` guarda o hash do commit aprovado. O registry compara o código em disco contra esse hash na carga; divergência é recusa, não aviso.

---

## 9. Permissões e enforcement

**O alvo do modelo de ameaça é erro, não malícia.** Quem escreve a capability é um LLM sob supervisão do dono, na máquina do dono. O risco real não é código hostil: é a capability de backup que resolve escrever em `C:\` inteiro por um bug de path, ou a de scraping que acerta o endpoint de produção porque o modelo trocou uma URL. Contra isso, sandbox em container é caro e desproporcional — resolve a ameaça errada e cobra em complexidade de rede, volumes e depuração.

Três mecanismos, baratos e proporcionais:

1. **Isolamento de processo.** Cada capability roda em subprocesso próprio. Crash, loop infinito ou consumo de memória não derrubam o orquestrador; o supervisor mata o processo e marca a tarefa como falha.
2. **Enforcement em runtime.** `permissions.yaml` não é documentação. Um wrapper sobre as chamadas de filesystem e rede levanta exceção quando a capability tenta sair do escopo declarado. Se `filesystem: []`, qualquer `open()` de escrita falha. Se a rede está restrita a um host, qualquer outro destino falha. A exceção sobe como falha de tarefa, com o alvo negado no log.
3. **`dry_run` na primeira execução.** Sempre. A capability registra o que faria — qual arquivo, qual host, qual payload — e não faz. O log vai para o dono. Só depois de um dry_run revisado ela passa a `active` e executa de verdade.

Os três juntos pegam o modo de falha que importa: o bug que só aparece na primeira execução real.

---

## 10. Memória

Cinco níveis, com propósitos distintos. Conceito aqui; implementação em `tools.md`.

| Nível | Conteúdo | Tempo de vida |
|---|---|---|
| Short | Turnos recentes da conversa corrente. | Sessão. |
| Working | Estado da tarefa em execução: plano, resultados parciais, o que já foi tentado. | Duração da tarefa; persistido no checkpoint. |
| Long | Fatos duráveis sobre o dono e o ambiente: máquinas, caminhos, contas, preferências fixas. | Permanente, editável. |
| Knowledge | Documentos ingeridos e indexados para busca semântica (RAG). | Permanente até remoção da fonte. |
| Experience | Padrões extraídos de execuções passadas: o que funcionou, o que falhou, como o dono costuma decidir. | Permanente, cresce por acúmulo. |

Experience é o nível que diferencia o sistema de um chat com RAG. Ele guarda coisas como "capability X falha quando o NAS está em standby, acordar antes" ou "o dono rejeita spec que pede acesso amplo a filesystem". Alimenta o planejamento do Chief AI e a geração de spec.

---

## 11. Eventos, scheduler e agentes contínuos

O barramento é **Redis Streams**. Redis já está no compose para cache e fila; Streams dá consumer group, ack e replay — o suficiente para o volume de um sistema de uma pessoa. NATS resolve problemas de escala que este sistema não tem.

O que vira evento na v1: `GoalCreated`, `GoalCompleted`, `TaskStarted`, `TaskFailed`, `CapabilityGapDetected`, `CapabilityInstalled`, `ApprovalRequested`, `ApprovalGranted`, `BackupCompleted`. O contrato de `Event` está em `tools.md`.

Quem reage: o orquestrador consome eventos de tarefa e move a fila; o serviço de notificação consome `ApprovalRequested` e falhas e manda push; capabilities podem declarar subscrição a eventos e virar reativas em vez de chamadas.

**Scheduler v1** roda três jobs e nada mais: backup (`pg_dump` + snapshot do LanceDB), reindexação incremental do Knowledge, e limpeza de logs e memória short expirada. Automações do dono entram como objetivos agendados, não como código no scheduler.

**Agentes contínuos** ficam para depois da v1 — filesystem watcher, monitor de GPU, watcher de email, health check de capability. Cada um é um processo permanente a operar e depurar; nenhum é pré-requisito de nada. Entram quando um deles resolver um problema concreto que já apareceu.

---

## 12. Modelos

Primeiro a **camada de abstração de provider**, antes de qualquer escolha de modelo. Ela é pequena (completar, streaming, tool calling, embeddings) e é o que permite trocar de modelo sem tocar nos agentes.

Divisão de trabalho:

- **Chief AI e geração de capability**: modelo forte via API. Planejamento longo e tool calling multi-agente são justamente onde um 8B quantizado quebra — entra em loop, emite tool call malformado, perde contexto no meio do plano. O custo de um plano ruim (uma capability errada gerada e revisada) é maior que o custo do token.
- **Tarefas baratas**: Qwen3 8B local — classificação, extração, resumo curto, reescrita, roteamento. Volume alto, tolerância a erro alta, custo marginal zero.

**LM Studio é o provider principal** (`lmstudio`, modelo `google/gemma-4-e2b`), com **Gemini como alternativa remota**. A inferência local voltou — não por a arquitetura ter mudado, mas por a máquina ter mudado: o servidor roda numa máquina da LAN e o container fala com ele pelo IP.

A sequência completa foi: KoboldCpp saiu porque o i5-3470 é pré-AVX2; Ollama entrou e não sustentou o `Qwen3-VL-8B-Instruct` nos 4 GB da 1050 Ti; Gemini assumiu como principal por API; LM Studio assumiu quando apareceu máquina que o comporta. **Quatro trocas de provider, cada uma custando um adapter e uma entrada num mapa de fábricas, com zero mudança em agente** — é exatamente o retorno que a camada de abstração desta seção existe para dar. A escolha é `chief_provider` em runtime, nunca build.

O adapter do Ollama continua no repositório, selecionável em runtime e **desligado** — é o último recurso da lista. O que saiu foi o *container*: ver §"O que roda em container" nas decisões fechadas.

Com inferência local de volta, **a divisão de trabalho desta seção deixa de estar colapsada**: tarefa barata pode voltar a ter custo marginal zero. O que ainda não existe é o roteamento automático entre o modelo local e o remoto — hoje é uma escolha só, global, e não por tipo de tarefa.

Providers falam a **API nativa** de cada serviço quando ela entrega mais — vale para Gemini (`:generateContent`, `:streamGenerateContent`, `:embedContent`) e para Ollama (`/api/chat`, `/api/embed`). A compatível omite tool calling completo e as contagens reais de token (`usageMetadata`, `prompt_eval_count`/`eval_count`), e sem contagem real o accounting da v1 seria estimativa apresentada como medição.

O LM Studio é a exceção deliberada: sua API **é** a da OpenAI, não uma camada de compatibilidade por cima de outra coisa. Verificado contra o servidor real, ela entrega o que a regra acima exige — `tool_calls` completo (`finish_reason: "tool_calls"` com argumentos JSON) e `usage` com `prompt_tokens`/`completion_tokens`. Por isso `lmstudio` reusa o `OpenAIProvider` em vez de ganhar adapter próprio.

---

## 13. Cliente PWA

Um PWA responsivo, servido pelo mesmo gateway, atrás do mesmo Cloudflare Access. Funciona no desktop e no celular com uma base de código.

Recursos: chat com streaming; upload de arquivos para o RAG; fila de aprovações (Gate 1 com layout compacto para celular, Gate 2 com diff em largura de desktop); dashboard de saúde (CPU, GPU, RAM, modelo carregado, agentes ativos, capabilities); lista de tarefas e objetivos em andamento com estado e último checkpoint; consulta ao histórico e à memória.

**iOS nativo fica para depois.** Custa conta de Apple Developer, um Mac para build, o ciclo de review e uma segunda base de código em Swift. Em troca entrega, sobre o PWA, basicamente push notification confiável, Face ID e integração de voz do sistema. O PWA entrega quase todo o valor de "controle remoto" primeiro e sem nenhum desses custos. Reavaliar quando o sistema estiver em uso diário e a falta de push nativo doer de verdade.

---

## 14. Roadmap

Cada milestone tem um critério de aceite verificável. "Pronto" é o critério passar, não a sensação de estar perto.

### v0 — Esqueleto que responde

Gateway, Chief AI mínimo, um provider de LLM, Postgres, Redis, uma tool real ligada por MCP.

**Aceite:** `docker compose up` sobe tudo sem intervenção manual; o chat responde com streaming usando **uma tool real** de ponta a ponta; um `Goal` e suas `Task` ficam persistidos em Postgres e sobrevivem a restart; `pytest` verde.

### v0.5 — Objetivos que sobrevivem

Goal Manager e Executive Function com fila, dependências, checkpoint e resume. PWA básico com chat e lista de objetivos.

**Aceite:** um objetivo com três tarefas dependentes executa até o fim; matar o processo no meio e subir de novo retoma da última tarefa concluída, sem repetir trabalho feito; o PWA mostra o estado ao vivo.

### v1 — Sistema utilizável de verdade

Capability Registry com `resolve()` e miss determinístico. Cloudflare Tunnel + Access publicando o PWA. Backup automatizado. Memória nos cinco níveis. Scheduler com os três jobs.

**Aceite:** o sistema é acessível do celular pela internet, com login pelo Access e sem porta aberta no roteador; um `resolve()` que falha emite `CapabilityGapDetected` e bloqueia o objetivo em vez de improvisar; o backup roda sozinho e um **restore é testado com sucesso** em base limpa; `pytest` verde.

### v2 — Capabilities escritas à mão

Duas ou três capabilities reais, escritas manualmente contra o SDK, em uso diário.

**Aceite:** cada capability tem manifest, `permissions.yaml` com escopo mínimo, testes e passou por um dry_run revisado; o enforcement em runtime foi verificado negando um acesso fora do escopo declarado; as três são usadas em objetivos reais por pelo menos duas semanas.

**A v2 é o que faz a v3 dar certo.** Escrever capability à mão é o que revela o formato certo de manifest, de permissões, de testes e de erro. Depois disso o SDK é um template validado pelo uso, e o LLM só precisa preencher um molde que já provou funcionar. Pular a v2 significa pedir ao modelo que invente a abstração e a implementação ao mesmo tempo — o caminho mais curto para uma pilha de capabilities inconsistentes.

### v3 — Self-evolution

Fluxo completo da seção 8: gap, spec, Gate 1, geração em branch, testes, Gate 2, merge, registro, dry_run, ativo.

**Aceite:** partindo de um pedido real que dá miss no registry, o sistema entrega uma capability funcionando sem edição manual de código; ambos os gates foram exercidos, incluindo pelo menos uma reprovação que descartou a branch corretamente; o registry recusa carregar uma capability cujo código foi alterado após o `approved_commit`.

---

## 15. Decisões resolvidas

Contradições da versão anterior deste documento, agora fechadas.

| Questão | Decisão | Motivo |
|---|---|---|
| Event bus: Redis pub/sub ou NATS? | **Redis Streams**, entrando na v2. NATS só se doer. | Redis já está no compose; Streams tem consumer group, ack e replay. NATS resolve escala inexistente aqui. |
| Temporal como motor de workflow? | **Não na v1.** | Fila em Postgres com checkpoint entrega o essencial sem um serviço, um SDK e um modelo mental a mais. |
| MCP ou Capability SDK? | **MCP é o padrão de tools**; o SDK envolve e expõe MCP. | Aproveita o ecossistema e ainda assim aplica manifest, permissões e ciclo de vida locais. |
| Auth própria (Argon2, JWT, TOTP, device registry)? | **Não.** Cloudflare Access na borda — mas a origem **valida** a asserção. | Single-user: manter um IdP para uma pessoa é desproporcional. Confiar cegamente na borda, porém, é outra coisa — a origem verifica o JWT do Access (assinatura, `aud`, e-mail) porque o modo de falha de não verificar é silencioso. |
| Onde o Jarvis é publicado? | **`ia.atmosintelli.com.br`** — subdomínio, não caminho. | O apex já é o site do dono. Caminho (`/jarvis`) poria a política do Access sobre o mesmo hostname do site público, e obrigaria `base` no Vite e reescrita no túnel. Subdomínio isola zona, aplicação Access e regra de ingress. |
| Sandbox em container por capability? | **Não.** Subprocesso + enforcement em runtime + dry_run. | O alvo é bug do modelo, não malícia. Container resolve a ameaça errada a um custo alto. |
| Quem dispara a criação de capability? | **Miss determinístico em `resolve()`.** Nunca o LLM. | LLM decidindo sozinho geraria capability duplicada por semana. |
| Um gate ou dois? | **Dois**: spec e código. | Um gate significa aprovar código inexistente ou queimar token antes de saber se a ideia presta. |
| Modelo único local? | **Não.** Modelo forte por API para o Chief AI; 8B local para tarefas baratas. | 8B quantizado falha em planejamento longo e tool calling multi-agente. |
| Qual provider principal? | **LM Studio** (`lmstudio`, `google/gemma-4-e2b`), servido na LAN. Gemini é a alternativa remota. | Local e sem custo por token, na máquina que o comporta. KoboldCpp caiu por AVX2; Ollama caiu porque um 8B não cabe em 4 GB de VRAM; Gemini funciona mas cobra por token (R-7). |
| Descartar o adapter do Ollama? | **Não.** Fica selecionável em runtime, desligado — último da ordem de preferência. | Código pronto e desligado custa quase nada; reescrever quando houver GPU custa caro. |
| API nativa ou camada OpenAI-compatible? | **Nativa**, com uma exceção verificada: o LM Studio. | A compatível costuma omitir tool calling completo e contagem real de token, e sem contagem real o accounting da v1 seria estimativa apresentada como medição. No LM Studio a API da OpenAI **é** a API nativa: testado contra o servidor, entrega `tool_calls` e `usage` completos. Por isso `lmstudio` reusa o `OpenAIProvider`. |
| Tarefas baratas no modelo local? | **Retomado** — o local voltou com o LM Studio. | O que ainda não existe é roteamento por tipo de tarefa: hoje a escolha de provider é global, não por capability. |
| O que roda em container? | **Tudo, menos a inferência**: Postgres, Redis, migrations, API, orchestrator, PWA. | Uma máquina, um operador: `docker compose up` é o contrato de "sobe sem intervenção manual" do aceite da v0. O runtime de inferência é a exceção porque containerizar modelo de vários GB com passthrough de GPU custa muito mais do que apontar uma URL para um servidor que já roda no host ou na LAN — e foi a reserva NVIDIA no compose que derrubava o `up` inteiro em máquina sem o toolkit. Sem serviço de inferência, o problema deixa de existir em vez de ficar atrás de profile. |
| App iOS nativo primeiro? | **Não.** PWA responsivo. | Apple Developer, Mac para build e review, por pouco ganho sobre o PWA. |

---

## 16. Fora de escopo

| Item | Motivo |
|---|---|
| Capability Store / marketplace | Um usuário. Distribuição para uma pessoa é infraestrutura sem demanda. |
| Multiusuário, RBAC, multi-tenancy | Single-user por premissa fixa. |
| Signup, reset de senha, rotação de refresh token, device registry | Resolvidos pelo Cloudflare Access na borda. |
| App iOS nativo | Adiado; custo alto e ganho marginal sobre o PWA. Reavaliar após uso diário. |
| Temporal | Fila com checkpoint cobre o caso; um serviço a menos para operar. |
| NATS | Redis Streams basta no volume de uma pessoa. |
| Zero Trust formal e audit de compliance | Sem terceiros acessando, não há a quem prestar contas. |
| Sandbox em container | Desproporcional ao modelo de ameaça (erro, não malícia). |
| Voz (STT/TTS), agentes contínuos, execução paralela | Bons, mas não pré-requisito de nenhum milestone. Entram quando um problema real pedir. |
