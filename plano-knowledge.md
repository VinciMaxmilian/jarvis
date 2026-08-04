# Plano — Escrita automática no `knowledge`

**Objetivo:** o Jarvis grava fatos e preferências do dono na base de conhecimento durante a conversa, sem passo manual. Hoje ele recusa ("não tenho permissão") porque nenhuma tool de escrita existe no catálogo.

---

## 1. Diagnóstico — o que existe hoje

### Escrita automática que funciona
| Namespace | Gatilho | Caminho |
|---|---|---|
| `chat_history` | toda mensagem de chat | [chat.py:48](apps/api/routers/chat.py#L48) → [`index_conversation_message`](packages/memory/indexer.py) → embed → `upsert` |

### Escrita no `knowledge` — só manual
Fonte de verdade é arquivo em `data/knowledge/*.md`. Dali sai:

- [`ReindexService`](packages/scheduler/reindex.py) faz diff SHA-256 e reindexa só o que mudou.
- Job `jarvis.reindex_knowledge` às 05:00 ([jobs.py:153](packages/scheduler/jobs.py#L153)) roda **só** no orchestrator ([orchestrator/main.py:83](orchestrator/main.py#L83)) — a API não sobe scheduler.
- E mesmo lá o job é inócuo: `from_database_url` sem `knowledge_index` cai no `InMemoryKnowledgeIndex` ([jobs.py:117](packages/scheduler/jobs.py#L117)) — dict volátil, sem vetorização, morre no restart. Job loga `completed`, base não muda.
- O que de fato popula: `python scripts/force_reindex.py`, manual, com `KnowledgeBaseAdapter` real (KB + Agno).

### Por que o agente recusa
`SystemToolExecutor` expõe só `web_search`, `search_memory`, `criar_servidor_mcp` ([executor.py:129](packages/agents/tools/executor.py#L129)). Sem tool de escrita, o LLM inventa desculpa de permissão.

A capability [`memory_writer`](capabilities/memory_writer/backend/handlers.py) está pronta (tool `memory_save`, appenda em `preferencias_usuario.md`) mas: `status: pending_approval` no manifest, e **zero call sites** — nada a registra num registry que o Chief enxergue. O Chief fala com `SystemToolExecutor`, não com o Kernel.

### Defeito colateral encontrado
O fallback não-Agno busca `namespace="memory"` ([chief.py:157](packages/agents/chief.py#L157), [executor.py:272](packages/agents/tools/executor.py#L272)), mas `KnowledgeBase` grava em `namespace="knowledge"` ([knowledge.py:44](packages/memory/knowledge.py#L44)). Sem Agno no ar, o RAG de conhecimento **nunca acha nada**. Precisa entrar no plano — senão a escrita nova fica invisível quando o Agno cai.

---

## 2. Decisão de arquitetura

**Tool nativa no `SystemToolExecutor`, não a capability.** Ligar `memory_writer` exigiria Kernel + registry + aprovação no caminho do Chief — trabalho grande para o mesmo efeito. A capability fica como migração futura (§7).

**Disco é a fonte, índice é derivado.** A tool escreve o `.md` em `data/knowledge/` **e** indexa. Só indexar deixaria o fato fora do `force_reindex` e do backup; só escrever no disco deixaria o fato invisível até a próxima reindexação.

**Agno é o índice primário**, espelhando o que `search_memory` já prefere ([executor.py:250](packages/agents/tools/executor.py#L250)). `add_knowledge(replace=True)` usa `name` como chave real — mesmo contrato do `force_reindex`, então escrita por tool e reindexação de arquivo convergem em vez de duplicar vetores.

```
LLM → knowledge_save
        ├─ 1. append em data/knowledge/<arquivo>.md      (fonte)
        ├─ 2. add_knowledge(text, name=path, replace=True) (Agno/PgVector)
        └─ 3. fallback: memory_store.upsert(ns="knowledge") (Agno fora do ar)
```

---

## 3. Fase 0 — Corrigir o namespace (bloqueante)

Sem isso a Fase 1 entrega escrita que o fallback não lê.

- [ ] [chief.py:157](packages/agents/chief.py#L157): `namespace="memory"` → `"knowledge"`
- [ ] [executor.py:272](packages/agents/tools/executor.py#L272): idem
- [ ] Conferir se algo grava em `"memory"` hoje (grep). Se sim, migrar os registros ou aceitar os dois namespaces na busca por um ciclo.

---

## 4. Fase 1 — Tool `knowledge_save`

### 1.1 Spec ([executor.py](packages/agents/tools/executor.py), junto das outras)

```python
KNOWLEDGE_SAVE_SPEC = ToolSpec(
    name="knowledge_save",
    description=(
        "Grava um fato, preferência ou informação permanente sobre o usuário na base "
        "de conhecimento. Use quando o usuário disser algo sobre si que deva ser lembrado "
        "em conversas futuras (gostos, rotina, decisões, contexto pessoal). "
        "NÃO use para informação efêmera ou para o que já está na base."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "fato": {
                "type": "string",
                "description": "O fato em uma frase, em 3ª pessoa. Ex: 'O usuário gosta de vermelho.'",
                "minLength": 3,
            },
            "categoria": {
                "type": "string",
                "description": "Arquivo temático. Ex: preferencias_usuario, comida, trabalho.",
                "default": "preferencias_usuario",
            },
        },
        "required": ["fato"],
    },
    idempotent=False,
    requires_approval=True,
)
```

`categoria` mapeia para o arquivo → conhecimento fica agrupado por tema em vez de virar um `.md` gigante. Sanitizar: `[a-z0-9_]+`, sem `..`, sem separador de caminho — o valor vem do LLM e vira caminho de arquivo.

### 1.2 Handler

```python
async def _knowledge_save(self, fato: str, categoria: str, dry_run: bool = False):
    # 1. valida + sanitiza categoria  → recusa clara se inválida
    # 2. resolve caminho sob KNOWLEDGE_DIR e confirma que o resolved() está
    #    contido nela (path traversal)
    # 3. dedup barato: se o fato normalizado já está no arquivo, devolve
    #    {"sucesso": True, "duplicado": True} sem escrever nem reindexar
    # 4. append "- [YYYY-MM-DD HH:MM] {fato}"
    # 5. add_knowledge(text=<arquivo inteiro>, name=<doc_id>, replace=True,
    #                  metadata={"doc_id":…, "source":…})
    # 6. fallback sem Agno: embed(fato) → memory_store.upsert(ns="knowledge")
    # 7. devolve {"sucesso": True, "caminho":…, "categoria":…}
```

Pontos que decidem se isso funciona ou apodrece:

- **Reindexar o arquivo inteiro, não só a linha nova.** `add_knowledge(replace=True)` apaga os vetores daquele `name` antes de inserir. Mandar só a linha nova apagaria o resto do arquivo do índice.
- **Erro volta como resultado, não como exceção.** O loop do Chief já trata ([chief.py:283](packages/agents/chief.py#L283)), mas resultado estruturado (`{"sucesso": false, "motivo": …}`) faz o modelo explicar ao dono em vez de travar.
- **Dedup antes de escrever.** Sem isso, "gosto de vermelho" repetido em 3 conversas vira 3 linhas e enviesa o RAG.
- **`KNOWLEDGE_DIR` vem de config**, não hardcoded — `SchedulerConfig.knowledge_dir` já existe ([config.py:84](packages/scheduler/config.py#L84)) e o `.md` precisa cair no mesmo lugar que o `force_reindex` varre. Em Docker isso é `/app/data/knowledge` (ver `source` no [knowledge_index.json](data/memory/knowledge_index.json)).

### 1.3 Registro
- [ ] Adicionar `KNOWLEDGE_SAVE_SPEC` ao dict `self._tools` ([executor.py:129](packages/agents/tools/executor.py#L129))
- [ ] Adicionar branch em `execute()` ([executor.py:157](packages/agents/tools/executor.py#L157))
- [ ] `SystemToolExecutor.__init__` já recebe `agno_knowledge` e `memory_vector_store` — nada novo em [deps.py:389](apps/api/deps.py#L389)

---

## 5. Fase 2 — Política de perfis e prompt

### 2.1 [profiles.py:139](packages/agents/profiles.py#L139)
`knowledge_save` escreve em disco → é **ação**, não leitura:

```python
_ACAO: Final = frozenset({"criar_servidor_mcp", "knowledge_save"})
```

Efeito: `executor` e `chief` (`allow_unlisted=True`) podem; `planner`, `researcher`, `reviewer` são barrados por `deny=_ACAO`. É o comportamento certo — reviewer não escreve.

### 2.2 [chief.md](packages/agents/prompts/chief.md)
Sem instrução explícita o modelo raramente chama tool de escrita por conta própria. Adicionar:

```markdown
- Quando o dono contar algo permanente sobre si (gosto, preferência, rotina,
  decisão, contexto pessoal), grave com `knowledge_save` — não peça permissão,
  apenas confirme depois em uma frase.
- Antes de gravar, use `search_memory` para não duplicar um fato já registrado.
- Não grave conversa fiada, informação efêmera nem coisa que o dono pediu para
  esquecer.
```

---

## 6. Fase 3 — Aprovação (decisão pendente)

`requires_approval=True` **não é honrado hoje**: o loop do Chief ([chief.py:283](packages/agents/chief.py#L283)) executa toda tool call direto. `criar_servidor_mcp` já é `requires_approval=True` e roda sem confirmação — ou seja, o campo é decorativo no caminho do chat.

Três saídas, em ordem de custo:

1. **Aceitar como está** (recomendado p/ v1): escrever no `knowledge` é reversível — arquivo `.md` versionado, dono edita ou apaga. O prompt manda confirmar depois. Marcar `requires_approval=False` para o campo não mentir.
2. **Confirmação no front**: streaming pausa, UI mostra "Jarvis quer gravar: …", dono aprova. Correto, mas exige protocolo novo no SSE + UI.
3. **Undo**: tool `knowledge_forget(doc_id)` usando [`KnowledgeBase.forget`](packages/memory/knowledge.py#L207), que já existe. Barato e cobre o arrependimento sem travar o fluxo.

**Recomendação: 1 + 3.** Deixar 2 para quando houver mais tools destrutivas.

---

## 7. Fase 4 — Consertar o caminho de manutenção

A tool cobre a escrita interativa. O job noturno continua quebrado e é ele que reconcilia edições manuais nos `.md`:

- [ ] `orchestrator/main.py`: passar `knowledge_index=KnowledgeBaseAdapter(memory)` para `SchedulerManager.from_database_url` — o adapter de [scripts/force_reindex.py:20](scripts/force_reindex.py#L20) sai do script e vira módulo (ex.: `packages/scheduler/adapters.py`). Hoje o job cai no `InMemoryKnowledgeIndex` e não indexa nada.
- [ ] Decidir se a API também dispara reindexação sob demanda (endpoint `POST /api/memory/reindex`) — útil para o botão da aba Memory, que hoje só chama `graphify/update`.
- [ ] Migração futura: `knowledge_save` delegar para a capability `memory_writer` quando o Kernel estiver no caminho do Chief. Aí a tool nativa vira adaptador fino e a permissão de filesystem passa a ser declarada em [permissions.yaml](capabilities/memory_writer/permissions.yaml) em vez de implícita.

---

## 8. Fase 5 — Visibilidade

Nada a fazer: a aba Memory já lê `/api/memory/graph.json`, que monta lobos por namespace presente. Todo fato novo aparece na zona `Knowledge` assim que o store tiver o registro. Com `MEMORY_VECTOR_BACKEND=graphify`, o [`GraphifyVectorStore`](packages/memory/graphify_store.py#L30) também espelha o texto em `data/memory_corpus/*.md` para o grafo do Graphify.

Verificar depois de implementar: se a escrita for só via Agno/PgVector (sem passar pelo `memory_store`), o nó **não** aparece no grafo. É motivo suficiente para manter o passo 6 do handler (upsert no vector store) como escrita normal, não só como fallback.

---

## 9. Testes

| Teste | Verifica |
|---|---|
| `test_knowledge_save_escreve_arquivo` | append no `.md` certo, formato da linha |
| `test_knowledge_save_categoria_invalida` | `../`, `/`, vazio → recusa estruturada, nada escrito |
| `test_knowledge_save_dedup` | fato repetido não duplica linha nem reindexa |
| `test_knowledge_save_sem_agno` | Agno indisponível → cai no vector store, `sucesso=True` |
| `test_knowledge_save_agno_falha` | exceção do Agno não derruba o turno |
| `test_perfil_reviewer_nao_grava` | `ToolDenied` para perfis de leitura |
| `test_rag_encontra_fato_recem_gravado` | integração: grava → `search_memory` acha |
| `test_namespace_knowledge_consistente` | Fase 0: escrita e busca no mesmo namespace |

---

## 10. Riscos

| Risco | Mitigação |
|---|---|
| LLM grava lixo em toda conversa | Prompt restritivo + `search_memory` antes + revisão periódica do `.md` |
| Fato errado envenena o RAG permanentemente | `knowledge_forget` (Fase 3.3) + arquivo é texto editável no git |
| `categoria` do LLM vira path traversal | Sanitizar + `resolved()` contido em `KNOWLEDGE_DIR` |
| Escrita concorrente no mesmo `.md` | Append é atômico o bastante em POSIX para linha curta; se virar problema, lock por arquivo |
| Divergência disco × índice | Job noturno consertado (Fase 4) reconcilia por SHA-256 |
| Custo de embedding por gravação | Dedup evita reindexação à toa; arquivo inteiro reindexado só quando muda |

---

## 11. Ordem de execução

1. **Fase 0** — namespace (2 linhas, destrava o resto)
2. **Fase 1** — tool `knowledge_save` + testes
3. **Fase 2** — perfis + prompt
4. Validar ponta a ponta: "adicione ao knowledge que gosto de vermelho" → grava → nova conversa → responde certo → nó aparece na aba Memory
5. **Fase 3.3** — `knowledge_forget`
6. **Fase 4** — adapter no orchestrator

Fases 1–3 entregam o que o dono pediu. Fase 4 é dívida técnica pré-existente que a tool não cria, mas também não resolve.

---

## 12. Arquivos tocados

| Arquivo | Mudança |
|---|---|
| [packages/agents/tools/executor.py](packages/agents/tools/executor.py) | spec + handler + registro + fix de namespace |
| [packages/agents/chief.py](packages/agents/chief.py#L157) | fix de namespace |
| [packages/agents/profiles.py](packages/agents/profiles.py#L139) | `knowledge_save` em `_ACAO` |
| [packages/agents/prompts/chief.md](packages/agents/prompts/chief.md) | regras de quando gravar |
| `packages/scheduler/adapters.py` | **novo** — `KnowledgeBaseAdapter` extraído do script |
| [orchestrator/main.py](orchestrator/main.py#L74) | passar `knowledge_index` real |
| [scripts/force_reindex.py](scripts/force_reindex.py) | importar o adapter em vez de redefinir |
| `tests/unit/test_knowledge_save.py` | **novo** |
