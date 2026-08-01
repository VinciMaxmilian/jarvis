#!/usr/bin/env sh
# =============================================================================
# backup.sh — roda o job de backup UMA vez, fora do agendamento.
#
# Chama exatamente o mesmo caminho de código que o APScheduler dispara às 3h
# (`SchedulerManager.run_backup`), então o que este script prova é o job, não uma
# rotina paralela que só existe para o operador. O evento `backup.completed`
# publicado aparece no terminal como uma linha `EVENT {...}`.
#
# USO
#   infrastructure/scripts/backup.sh              # dentro do container `test`
#   JARVIS_BACKUP_PATH=/tmp/b infrastructure/scripts/backup.sh
#
# ONDE RODA
#   Precisa de Python com as dependências do projeto E do binário `pg_dump`.
#   Nesta máquina isso não existe no host, então o default é rodar dentro do
#   serviço `test` do compose, que tem o repositório montado e alcança o serviço
#   `postgres` pela rede do Compose.
#
#   PENDÊNCIA CONHECIDA (fora do escopo desta fatia, ver relatório): nenhuma das
#   imagens do projeto traz `postgresql-client`, então este script o instala no
#   container efêmero antes de rodar. A correção definitiva é instalar
#   `postgresql-client-16` em `apps/api/Dockerfile`, arquivo de outro dono. Com
#   ela, o `INSTALL_CLIENT=0` abaixo passa a ser o default.
#
# POR QUE A VERSÃO DO CLIENTE É FIXADA (isto não é preciosismo — foi medido)
#   A imagem da app é Debian trixie, cujo `postgresql-client` é o **17**. O
#   servidor do compose é `postgres:16-alpine`. Um `pg_dump` 17 contra servidor
#   16 grava no arquivo `SET transaction_timeout = 0`, um parâmetro que só existe
#   a partir do 17 — e o restore morre no meio, com o banco já limpo pelo
#   `--clean`:
#
#     pg_restore: error: could not execute query: ERROR:
#       unrecognized configuration parameter "transaction_timeout"
#
#   Ou seja: o backup era gravado com sucesso e só era descoberto inútil no dia
#   do restore. É exatamente o risco R-5 (`plan-execution.md` §8) se
#   materializando. Por isso o cliente vem do repositório PGDG **fixado no mesmo
#   major do servidor**, e o job é apontado para esse binário via
#   `JARVIS_PG_DUMP_BIN`. Trocou a imagem do Postgres no compose? Troque
#   `PG_MAJOR` junto, ou o restore volta a quebrar sem avisar.
#
# VARIÁVEIS
#   COMPOSE_FILE      default infrastructure/docker/docker-compose.yml
#   SERVICE           default test
#   INSTALL_CLIENT    1 (default) instala postgresql-client-$PG_MAJOR no efêmero
#   PG_MAJOR          default 16 — TEM de casar com a imagem do serviço postgres
#   PGDG_SUITE        default trixie-pgdg (a suite do Debian da imagem da app)
#   DATABASE_URL      DSN usado pelo job; default aponta para o serviço postgres
# =============================================================================
set -eu

# Git Bash / MSYS reescreve todo argumento que PARECE caminho absoluto de Unix
# antes de entregá-lo ao processo. `/usr/lib/postgresql/16/bin/pg_dump` — um
# caminho DENTRO do container — chegava ao `docker` como
# `C:/Program Files/Git/usr/lib/postgresql/16/bin/pg_dump`, e o backup morria com
# "binário não encontrado" em toda execução na máquina do dono, que é Windows.
# Medido, não suposto. No Linux e no macOS este bloco não faz nada.
case "$(uname -s 2>/dev/null || echo desconhecido)" in
  MINGW* | MSYS* | CYGWIN*)
    MSYS_NO_PATHCONV=1
    MSYS2_ARG_CONV_EXCL='*'
    export MSYS_NO_PATHCONV MSYS2_ARG_CONV_EXCL
    ;;
esac

REPO_ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-infrastructure/docker/docker-compose.yml}"
SERVICE="${SERVICE:-test}"
# Default 0 desde que `apps/api/Dockerfile` passou a trazer o postgresql-client-16
# nos estágios `runtime` e `test`. Instalar na hora fazia o backup das 3h depender
# de `apt-get update` e da rede — e a noite em que a rede cai é a noite em que o
# backup importa. `INSTALL_CLIENT=1` continua existindo para rodar contra uma
# imagem antiga, sem rebuild.
INSTALL_CLIENT="${INSTALL_CLIENT:-0}"

cd "$REPO_ROOT"

[ -f .env ] || { echo "backup.sh: .env não encontrado na raiz do repo" >&2; exit 1; }

# Credenciais do .env, sem ecoar nada: o DSN é montado dentro do container.
PGU="$(grep -E '^POSTGRES_USER=' .env | head -n1 | cut -d= -f2- | cut -d'#' -f1 | tr -d ' \r')"
PGP="$(grep -E '^POSTGRES_PASSWORD=' .env | head -n1 | cut -d= -f2- | cut -d'#' -f1 | tr -d ' \r')"
PGD="$(grep -E '^POSTGRES_DB=' .env | head -n1 | cut -d= -f2- | cut -d'#' -f1 | tr -d ' \r')"
DSN="${DATABASE_URL:-postgresql+asyncpg://$PGU:$PGP@postgres:5432/$PGD}"

PG_MAJOR="${PG_MAJOR:-16}"
PGDG_SUITE="${PGDG_SUITE:-trixie-pgdg}"
PG_BIN="/usr/lib/postgresql/$PG_MAJOR/bin"
PGDG_KEY="/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc"

if [ "$INSTALL_CLIENT" = "1" ]; then
  # Uma linha só, encadeada com &&, porque isto vira o argumento de um `sh -c`
  # dentro do container: se qualquer passo falhar, o backup NÃO roda — melhor não
  # ter backup do que ter um que o restore recusa.
  PRE="apt-get update -qq >/dev/null 2>&1 && \
apt-get install -y -qq curl ca-certificates >/dev/null 2>&1 && \
install -d /usr/share/postgresql-common/pgdg && \
curl -sS --fail -o $PGDG_KEY https://www.postgresql.org/media/keys/ACCC4CF8.asc && \
echo 'deb [signed-by=$PGDG_KEY] https://apt.postgresql.org/pub/repos/apt $PGDG_SUITE main' > /etc/apt/sources.list.d/pgdg.list && \
apt-get update -qq >/dev/null 2>&1 && \
apt-get install -y -qq postgresql-client-$PG_MAJOR >/dev/null 2>&1 && "
else
  PRE=""
fi

exec docker compose -f "$COMPOSE_FILE" --env-file .env --profile test \
  run --rm -T -e "DATABASE_URL=$DSN" -e "JARVIS_PG_DUMP_BIN=$PG_BIN/pg_dump" \
  "$SERVICE" \
  sh -c "${PRE}python -m packages.scheduler backup"
