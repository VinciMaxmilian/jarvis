# Atualizar o Docker do Jarvis

Cola-e-roda. Todo comando parte da **raiz do repositório** (`C:\...\jarvis`).

O prefixo é sempre o mesmo, e os dois pedaços são obrigatórios: `-f` porque o
compose não está na raiz, `--env-file` porque o `.env` também não está ao lado do
compose. Esquecer o `--env-file` sobe a stack com variável faltando e o sintoma
aparece longe daqui (API sem chave, tunnel sem token).

```powershell
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env <comando>
```

Se cansar de repetir, defina o atalho uma vez por terminal:

```powershell
function dcj { docker compose -f infrastructure/docker/docker-compose.yml --env-file .env @args }
```

Os exemplos abaixo usam a forma longa para poderem ser colados isolados.

---

## Subir

```powershell
# Sobe tudo (postgres, redis, migrate, api, orchestrator, web, web-prod)
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env up -d

# Sobe e reconstrói as imagens antes
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env up -d --build
```

> `--build` faz o estágio de produção do PWA rodar `npm run build`, que é
> `tsc -b && vite build`. **Erro de TypeScript reprova o `up`.** É o único ponto
> do pipeline onde o TS é obrigatório, e é de propósito.

## Ver o que está acontecendo

```powershell
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env ps
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env logs -f api
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env logs migrate

# Logs sem as cores do structlog (facilita grep)
docker logs jarvis-api-1 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | tail -50
```

## Parar

```powershell
# Para os containers, PRESERVA banco e volumes
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env stop

# Para e REMOVE os containers, ainda preservando os dados
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env down
```

---

## Atualizar depois de mexer no código

| O que você mexeu | O que rodar |
|---|---|
| Código Python (`apps/`, `packages/`, `orchestrator/`) | `restart api orchestrator` — o código é bind mount, basta reiniciar |
| `pyproject.toml` / dependência nova de Python | `up -d --build api orchestrator` |
| Código do PWA (`apps/web/src/`) | nada — o Vite faz HMR sozinho |
| **`apps/web/package.json`** (dependência nova) | `up -d --build --renew-anon-volumes web` ← **ver armadilha abaixo** |
| Migration nova do Alembic | `run --rm migrate` |
| `.env` | `up -d --force-recreate` (variável de ambiente só entra na criação) |
| `docker-compose.yml` | `up -d` (o compose detecta e recria o que mudou) |

```powershell
# Reiniciar só o backend (mudança de código Python)
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env restart api orchestrator

# Rebuild de um serviço só
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env up -d --build api

# Aplicar migrations pendentes
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env run --rm migrate
```

### ⚠️ Armadilha: dependência nova do PWA

O serviço `web` tem um **volume anônimo** montado sobre `node_modules`:

```yaml
- ../../apps/web:/app/apps/web
- /app/apps/web/node_modules      # <- este
```

Ele é populado a partir da imagem **na primeira criação** e depois persiste
sozinho. Isso significa que `--build` **não basta**: a imagem nova é construída,
mas o volume velho continua montado por cima e o pacote novo nunca aparece. O
sintoma é o Vite reclamando `Failed to resolve import "x"` de um pacote que está
no `package.json` e instalado na sua máquina.

```powershell
# O comando certo depois de adicionar dependência no apps/web/package.json
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env up -d --build --renew-anon-volumes web
```

Conferir se um pacote chegou lá dentro:

```powershell
docker exec jarvis-web-1 sh -c "ls /app/apps/web/node_modules | wc -l"
docker exec jarvis-web-1 sh -c "test -d /app/apps/web/node_modules/framer-motion && echo PRESENTE || echo AUSENTE"
```

---

## Excluir

Em ordem crescente de destruição. **Leia antes de colar.**

```powershell
# 1. Remove containers e rede. Banco e Redis INTACTOS.
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env down
```

```powershell
# 2. Remove também os volumes anônimos (node_modules). Banco INTACTO.
#    Use quando o node_modules do container estiver estragado.
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env down -v --volumes
```

> ⚠️ **`down -v` APAGA `pgdata` e `redisdata` junto.** Some o Postgres inteiro:
> conversas, goals, memória, `system_settings` (provider, modelo e o prompt do
> sistema que você escreveu na UI). Não há undo. Faça o backup abaixo antes.

```powershell
# Backup do banco ANTES de qualquer down -v
docker exec jarvis-postgres-1 pg_dump -U jarvis jarvis > backup_jarvis.sql

# Restaurar
Get-Content backup_jarvis.sql | docker exec -i jarvis-postgres-1 psql -U jarvis -d jarvis
```

```powershell
# 3. Zerar UM serviço sem tocar no resto
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env rm -sf web
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env up -d --build web
```

```powershell
# 4. Faxina de disco: imagens órfãs e cache de build (não toca em volume)
docker image prune -f
docker builder prune -f
```

---

## Reset completo (recomeçar do zero)

Só quando a stack estiver irrecuperável. Apaga o banco.

```powershell
# 1. Backup, sempre
docker exec jarvis-postgres-1 pg_dump -U jarvis jarvis > backup_jarvis.sql

# 2. Derruba tudo, inclusive volumes de dados
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env down -v

# 3. Reconstrói do zero
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env build --no-cache

# 4. Sobe
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env up -d

# 5. Confere
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env ps
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env logs migrate
```

Depois do reset, o `system_settings` volta ao default: **reconfigure provider,
modelo e o prompt do sistema na aba Rules**, ou restaure o backup.

---

## O que NÃO está no Docker

Duas peças rodam nativas no Windows e não são afetadas por nada acima:

| Peça | Como subir | Por quê fora do Docker |
|---|---|---|
| **MCP do host** (ver tela, clicar, digitar) | `.\scripts\run_desktop_host.ps1` | Container não tem tela, mouse nem teclado da sessão gráfica |
| **LM Studio** | app do Windows | Precisa da GPU e do modelo local |

Se o Jarvis disser que não consegue ver sua tela, o primeiro lugar a olhar é se o
`run_desktop_host.ps1` está rodando — não o Docker.

## Diagnóstico rápido

```powershell
# Saúde de todos os serviços
docker compose -f infrastructure/docker/docker-compose.yml --env-file .env ps

# A API achou o MCP do host?
docker logs jarvis-api-1 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | Select-String "Jarvis-Windows-Host"

# O container alcança o LM Studio?
docker exec jarvis-api-1 python -c "import urllib.request,json; print([m['id'] for m in json.load(urllib.request.urlopen('http://192.168.11.189:1234/v1/models'))['data']])"

# Provider e modelo em vigor
docker exec jarvis-postgres-1 psql -U jarvis -d jarvis -tAc "select provider, model from system_settings where id=1;"
```
