# Handoff — 31/07/2026 (madrugada de 01/08)

Sessão de fechamento da v1. Nada foi commitado; tudo está na árvore de trabalho.

## Estado medido, não declarado

```
pytest          492 passed, 0 failed
mypy packages/  Success: no issues found in 67 source files
ruff check .    3 erros restantes (lista abaixo)
```

## v1 — 6 de 6 fatias fechadas

| Fatia | Prova |
|---|---|
| v1.1 Registry | resolve intenção sem LLM; miss vira `capability.gap_detected` + goal `blocked`; hash confere `approved_commit`; tabela `capabilities` persiste. Os 4 `xfail(strict)` foram removidos e os testes invertidos |
| v1.2 Kernel | `tests/unit/test_kernel_execucao.py`, 10 testes com **subprocesso real**: executa ponta a ponta, sem `network` o socket é negado (`DENIED`), laço infinito morto no timeout com `task.failed` no bus. Contraprovas juntas (host declarado passa, escrita declarada passa, `dry_run` não deixa arquivo) |
| v1.3 Memória | 5 níveis. `test_memory_experience.py` (12 testes) prova o aceite 3 ponta a ponta: a falha entra por `on_task_failed` e sai inspecionando a mensagem `system` que o `GoalManager` real montou |
| v1.4 Scheduler | 3 jobs + **restore executado de verdade** em base descartável: goals/tasks/FK/`alembic_version=0003` voltaram idênticos. R-5 fechado |
| v1.5 Publicação | validado de fora com o túnel no ar: `302` pro Access no apex e em `/api/health`, `cf-ray`, cert válido, zero porta em `0.0.0.0`, apex e `www` do ATMOS intactos |
| Capability SDK | 78 testes, `mypy --strict`, capability de exemplo completa, manifest gerado em vez de digitado |

## Bugs achados por execução (não por leitura)

1. **`env_file:` do Compose não corta comentário inline.** Mordeu duas vezes:
   - `CORS_ORIGINS` → `SettingsError` em 77 testes de uma vez;
   - `POSTGRES_PASSWORD` → senha divergente de `DATABASE_URL` → **orchestrator em laço
     de reinício** com `InvalidPasswordError`. Corrigido no `.env` + `ALTER USER`.
   **Regra: nenhuma linha do `.env` pode ter comentário depois do valor.**
2. **Git Bash quebrava backup e restore.** MSYS reescreve argumento que parece caminho
   Unix: `/usr/lib/postgresql/16/bin/pg_dump` virava `C:/Program Files/Git/usr/...`.
   Guarda `MINGW*|MSYS*|CYGWIN*` nos dois scripts.
3. **Backup dependia de `apt-get` + rede a cada execução.** `postgresql-client-16` agora
   vem na imagem (`apps/api/Dockerfile`, estágios `runtime` e `test`);
   `INSTALL_CLIENT` default virou `0`. Backup caiu para 5,5 s.
4. **JWKS não rebuscava em `kid` desconhecido** — sentinela `0.0` comparada com
   `time.monotonic()`, cuja origem é o boot da máquina. Falhava depois de todo reboot.
   Junto veio um `500` no lugar de `401` com payload não-UTF-8.
5. **Testes não herméticos** liam o `.env` do dono montado em `/app`. Padrão adotado:
   `with mock.patch.dict(os.environ, {}, clear=True): Settings(_env_file=None, **base)`.

## Restrição desta máquina

**`import lancedb` derruba o processo com SIGILL (exit 132).** CPU i5-3470 (Ivy Bridge):
flags `avx f16c sse4_2`, sem AVX2/FMA/BMI2, que o binário Rust exige. Mesma causa que
tirou o KoboldCpp. Por isso o LanceDB vive atrás da porta `VectorStore`, com
`InMemoryVectorStore` como default e import preguiçoso no adapter. **Nunca importe
`lancedb` no topo de um módulo.**

## EM ABERTO — bolhas de chat vazias (não resolvido)

Sintoma: a resposta do assistente aparece como bolha vazia no PWA.

**Já provado que o backend está correto** (três camadas):
- Postgres tem as respostas: `assistant len=98 · 168 · 55 · 248`
- `llm.complete output_tokens=20 · 36 · 13 · 53`
- `ChiefAI.respond()` chamado direto, sem HTTP, em duas rodadas da mesma conversa:
  `chunk[1] type='text' len=66` / `chunk[2] done` — idêntico nos dois turnos.

O texto chega ao banco e ao socket. Some entre o socket e a tela.

**O que já foi feito em `apps/web/src/pages/ChatPage.tsx`:**
- a função `aplicarTexto()` nunca descarta texto: tenta o id da bolha, depois a última
  bolha do assistente em streaming, e por último **cria** uma bolha. Antes fazia
  `return prev` — descarte silencioso;
- `done` fecha todas as bolhas em streaming, não só a de id conhecido;
- guarda contra socket duplicado no `connect()`.

**Pista mais forte, ainda não explorada:** os logs da API mostram **dois**
`WebSocket /api/chat/ws [accepted]` por carregamento de página e **nenhum**
`connection closed`. Dois sockets vivos, e `send()` fala com apenas um.

**Próximo passo sugerido:** abrir o DevTools do navegador na aba Network → WS e ler os
frames que chegam. É o único ponto da cadeia que ainda não foi observado diretamente.
Suspeita secundária: bundle velho servido pelo service worker do PWA (exige
Ctrl+Shift+R) ou dessincronização de estado por HMR do Vite.

## Também em aberto

- **`ruff check .` — 3 erros**: `apps/api/db/repository.py`, `apps/api/routers/chat.py`
  (import desordenado, auto-fixável com `--fix`), `packages/shared/settings.py`.
- **Mobile**: 6 screens + components + Brain em disco; `tsc --noEmit` nunca rodou.
  Falta navegação/App.tsx conferidos.
- **`graphify update .`** não rodou; o grafo está desatualizado.
- **Banco órfão `jarvis_restore_src`** (7,9 MB), sobra de um agente interrompido.
  Não removi sem autorização.

## Pendências do dono (fora do código)

1. **Rotacionar o token do túnel.** O `.env.example` na árvore está limpo, mas o token
   vivo está no histórico do git (commit `c0d7f8f`). Dashboard → Networking → Tunnels →
   JARVIS_TUNNEL → Refresh token, depois `cloudflared.exe service uninstall` +
   `service install <TOKEN-NOVO>` como Administrador.
2. **Apontar a rota do dashboard para `127.0.0.1:5174`** (nginx prod). Hoje o que está
   exposto à internet é o **dev server do Vite** em 5173 — HMR, WebSocket de
   desenvolvimento, bundle não otimizado. O `allowedHosts` que adicionei em
   `vite.config.ts` é remendo para depurar pelo celular, não a configuração final.
3. Conector do túnel: confirmar que só o desta máquina
   (`259901f5-8378-457f-9eb6-4efccadc9a48`) está registrado. Se o do outro PC ainda
   estiver, a Cloudflare balanceia entre os dois e o site fica intermitente.

## Ambiente

- `.wslconfig` criado com `guiApplications=false` — mata os popups de RDP
  (`msrdc.exe` do WSLg falhando). Vale no próximo restart do Docker.
- Docker caiu duas vezes durante a sessão; se `docker info` falhar, reabra o
  Docker Desktop antes de qualquer coisa.
- Comandos que valem a pena ter à mão:
  ```
  docker compose -f infrastructure/docker/docker-compose.yml --env-file .env --profile test run --rm -T test pytest -q
  docker compose -f infrastructure/docker/docker-compose.yml --env-file .env --profile test run --rm -T test mypy packages/
  sh infrastructure/scripts/backup.sh
  sh infrastructure/scripts/restore.sh data/backups/<id> --database <descartavel> --yes
  ```
