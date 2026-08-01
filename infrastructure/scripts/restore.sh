#!/usr/bin/env sh
# =============================================================================
# restore.sh — restaura um backup do Jarvis em base limpa.
#
# É a metade do R-5 (`plan-execution.md` §8) que costuma não existir: "backup
# existe e restore nunca é testado". O aceite da v1.4 é este script ter rodado
# de verdade, contra um Postgres vazio, e o sistema ter voltado com goals e
# memória intactos.
#
# POSIX sh, e não Python, de propósito: o dia em que o restore é preciso é o dia
# em que talvez não exista mais um venv com as dependências do projeto — e
# depender do sistema que quebrou para consertar o sistema que quebrou é como
# guardar a chave reserva dentro do carro.
#
# USO
#   infrastructure/scripts/restore.sh <diretório-do-backup> [opções]
#
#   --yes                 não pergunta (obrigatório fora de terminal interativo)
#   --container <nome>    container do Postgres (default: jarvis-postgres-1)
#   --database <nome>     banco de destino (default: $POSTGRES_DB ou 'jarvis')
#   --user <nome>         usuário (default: $POSTGRES_USER ou 'jarvis')
#   --lancedb <caminho>   destino do snapshot de vetores (default: $LANCEDB_PATH)
#   --skip-verify         pula a conferência de SHA-256 (NÃO use; existe para
#                         resgatar backup com digest quebrado como último recurso)
#
# COMO CONECTA
#   Usa `pg_restore` do PATH se existir. Se não existir — o caso desta máquina,
#   onde nem o host nem a imagem da app trazem o postgresql-client — copia o
#   dump para dentro do container do Postgres e roda o `pg_restore` de lá. O
#   binário do restore fica sempre na MESMA versão do servidor, que é o que se
#   quer: `pg_restore` mais velho que o dump recusa o arquivo.
#
# VERSÃO DO CLIENTE (medido nesta máquina, não teoria)
#   No modo local, cliente e servidor podem divergir — e a divergência perigosa é
#   o cliente ser MAIS NOVO. Um dump gerado por `pg_dump` 17 restaurado num
#   servidor 16 morre no meio com:
#
#     pg_restore: error: could not execute query: ERROR:
#       unrecognized configuration parameter "transaction_timeout"
#
#   ...e o `--clean` já derrubou os objetos a essa altura. Por isso existe o
#   pré-voo de versão abaixo: ele recusa ANTES de encostar no banco. A origem do
#   dump é fixada em `infrastructure/scripts/backup.sh` (PG_MAJOR).
#
# SEGURANÇA
#   O script só escreve em UM banco, o que for passado em --database, dentro do
#   container nomeado em --container. Ele imprime exatamente o que vai fazer e
#   exige confirmação. Não derruba volume, não roda `docker compose down`, não
#   toca em nenhum outro container.
# =============================================================================
set -eu

# Git Bash / MSYS reescreve todo argumento que PARECE caminho absoluto de Unix
# antes de entregá-lo ao processo. O caminho do dump DENTRO do container
# (`/tmp/jarvis-restore-*.dump`) chegava ao `docker` como
# `C:/Users/.../Temp/jarvis-restore-*.dump`, e o restore morria com
# "could not open input file" — no dia em que ele é preciso. Medido, não suposto:
# a máquina do dono é Windows. No Linux e no macOS este bloco não faz nada.
case "$(uname -s 2>/dev/null || echo desconhecido)" in
  MINGW* | MSYS* | CYGWIN*)
    MSYS_NO_PATHCONV=1
    MSYS2_ARG_CONV_EXCL='*'
    export MSYS_NO_PATHCONV MSYS2_ARG_CONV_EXCL
    ;;
esac

PROG="$(basename "$0")"
CONTAINER="${JARVIS_PG_CONTAINER:-jarvis-postgres-1}"
DATABASE="${POSTGRES_DB:-jarvis}"
PGUSER_NAME="${POSTGRES_USER:-jarvis}"
LANCEDB_DEST="${LANCEDB_PATH:-}"
ASSUME_YES=0
SKIP_VERIFY=0
BACKUP_DIR=""

die() { printf '%s: %s\n' "$PROG" "$1" >&2; exit 1; }
info() { printf '[restore] %s\n' "$1"; }

# --- argumentos --------------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y)      ASSUME_YES=1 ;;
    --skip-verify) SKIP_VERIFY=1 ;;
    --container)   CONTAINER="${2:?--container exige valor}"; shift ;;
    --database)    DATABASE="${2:?--database exige valor}"; shift ;;
    --user)        PGUSER_NAME="${2:?--user exige valor}"; shift ;;
    --lancedb)     LANCEDB_DEST="${2:?--lancedb exige valor}"; shift ;;
    -h|--help)     sed -n '2,40p' "$0"; exit 0 ;;
    -*)            die "opção desconhecida: $1" ;;
    *)             [ -z "$BACKUP_DIR" ] || die "só um diretório de backup por vez"
                   BACKUP_DIR="$1" ;;
  esac
  shift
done

[ -n "$BACKUP_DIR" ] || die "uso: $PROG <diretório-do-backup> [--yes]"
[ -d "$BACKUP_DIR" ] || die "não é um diretório: $BACKUP_DIR"

MANIFEST="$BACKUP_DIR/manifest.json"
DUMP="$BACKUP_DIR/postgres.dump"
LANCEDB_SNAPSHOT="$BACKUP_DIR/lancedb"

[ -f "$MANIFEST" ] || die "sem manifest.json em $BACKUP_DIR — isso não é um backup"
[ -f "$DUMP" ]     || die "sem postgres.dump em $BACKUP_DIR"

# --- leitura do manifesto ----------------------------------------------------
# grep/sed em vez de jq: jq não é garantido em máquina nenhuma, e o manifesto é
# escrito por `BackupManifest.model_dump_json`, cujo formato é estável.
json_field() {
  sed -n 's/.*"'"$1"'"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$MANIFEST" | head -n 1
}

BACKUP_ID="$(json_field backup_id)"
CREATED_AT="$(json_field created_at)"
SOURCE_DB="$(json_field database)"

# O sha256 aparece duas vezes no manifesto (postgres e lancedb); o range
# `/"postgres"/,/}/` isola o primeiro bloco, que é o do dump.
DUMP_SHA="$(sed -n '/"postgres"[[:space:]]*:/,/}/{
  s/.*"sha256"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p
}' "$MANIFEST" | head -n 1)"

[ -n "$BACKUP_ID" ] || die "manifest.json sem backup_id — arquivo corrompido"

# --- conferência de integridade ----------------------------------------------
if [ "$SKIP_VERIFY" -eq 0 ]; then
  if command -v sha256sum >/dev/null 2>&1; then
    ATUAL="$(sha256sum "$DUMP" | cut -d' ' -f1)"
  elif command -v shasum >/dev/null 2>&1; then
    ATUAL="$(shasum -a 256 "$DUMP" | cut -d' ' -f1)"
  else
    ATUAL=""
    info "AVISO: nem sha256sum nem shasum disponíveis — integridade NÃO conferida"
  fi
  if [ -n "$ATUAL" ] && [ -n "$DUMP_SHA" ]; then
    [ "$ATUAL" = "$DUMP_SHA" ] || die "sha256 do dump não bate com o manifesto.
  manifesto: $DUMP_SHA
  arquivo:   $ATUAL
Restaurar um dump corrompido derruba o banco no meio do caminho — abortado."
    info "integridade conferida: sha256 bate com o manifesto"
  fi
fi

# --- como vamos falar com o Postgres ------------------------------------------
if command -v pg_restore >/dev/null 2>&1; then
  MODE="local"
else
  command -v docker >/dev/null 2>&1 \
    || die "sem pg_restore no PATH e sem docker — impossível restaurar daqui"
  docker inspect "$CONTAINER" >/dev/null 2>&1 \
    || die "container '$CONTAINER' não existe. Suba o Postgres antes:
  docker compose -f infrastructure/docker/docker-compose.yml --env-file .env up -d postgres"
  MODE="docker"
fi

# --- pré-voo de versão --------------------------------------------------------
# Só faz sentido no modo local: no modo docker o binário é o do próprio servidor,
# então cliente e servidor são a mesma versão por construção. Ver o cabeçalho.
if [ "$MODE" = "local" ]; then
  DUMPER_MAJOR="$(pg_restore --list "$DUMP" 2>/dev/null \
    | sed -n 's/.*Dumped by pg_dump version: \([0-9][0-9]*\).*/\1/p' | head -n 1)"
  SERVER_NUM="$(psql --username "$PGUSER_NAME" --dbname "$DATABASE" \
    -tAc 'SHOW server_version_num;' 2>/dev/null | tr -d ' ')"
  if [ -n "$DUMPER_MAJOR" ] && [ -n "$SERVER_NUM" ]; then
    SERVER_MAJOR=$((SERVER_NUM / 10000))
    if [ "$DUMPER_MAJOR" -gt "$SERVER_MAJOR" ]; then
      die "dump gerado por pg_dump $DUMPER_MAJOR, destino é PostgreSQL $SERVER_MAJOR.
Um cliente mais novo grava parâmetros que o servidor não reconhece, e o restore
quebraria NO MEIO — com o --clean já tendo derrubado os objetos. Abortado antes
de encostar no banco.
  Gere o backup com um pg_dump $SERVER_MAJOR: PG_MAJOR em
  infrastructure/scripts/backup.sh."
    fi
    info "versões conferidas: dump por pg_dump $DUMPER_MAJOR -> servidor $SERVER_MAJOR"
  fi
fi

DUMP_BYTES="$(wc -c < "$DUMP" | tr -d ' ')"

cat <<EOF

=============================================================
 RESTORE DO JARVIS
   backup .......... $BACKUP_ID  ($CREATED_AT)
   origem .......... banco '$SOURCE_DB'
   dump ............ $DUMP  ($DUMP_BYTES bytes)
   destino ......... banco '$DATABASE' como usuário '$PGUSER_NAME'
   via ............. $MODE
   container ....... $([ "$MODE" = docker ] && echo "$CONTAINER" || echo "(n/a)")
   vetores ......... $([ -d "$LANCEDB_SNAPSHOT" ] && echo "$LANCEDB_SNAPSHOT -> ${LANCEDB_DEST:-<não configurado>}" || echo "nenhum no backup")

 O QUE ISTO APAGA: os objetos do banco '$DATABASE' que existirem com o mesmo
 nome dos do dump (pg_restore --clean --if-exists). Nenhum outro banco, nenhum
 volume, nenhum container.
=============================================================

EOF

if [ "$ASSUME_YES" -eq 0 ]; then
  printf 'Confirma? [digite SIM] '
  read -r RESPOSTA
  [ "$RESPOSTA" = "SIM" ] || die "abortado pelo operador"
fi

# --- Postgres -----------------------------------------------------------------
# --clean --if-exists: derruba o objeto antes de recriar, e não reclama se ele
#   não existia (base limpa). Sem --if-exists, cada DROP de objeto ausente vira
#   erro e o restore termina com código != 0 mesmo tendo dado certo.
# --no-owner --no-privileges: o dump já foi feito assim; repetir aqui protege
#   contra dump antigo feito antes dessa decisão.
# --exit-on-error: o default do pg_restore é SEGUIR APÓS ERRO e terminar com 0.
#   Um restore que "deu certo" com metade das tabelas é a pior saída possível.
RESTORE_FLAGS="--clean --if-exists --no-owner --no-privileges --exit-on-error"

info "restaurando o Postgres..."
if [ "$MODE" = "local" ]; then
  # shellcheck disable=SC2086
  pg_restore $RESTORE_FLAGS --username "$PGUSER_NAME" --dbname "$DATABASE" "$DUMP"
else
  REMOTE="/tmp/jarvis-restore-$BACKUP_ID.dump"
  docker cp "$DUMP" "$CONTAINER:$REMOTE"
  # shellcheck disable=SC2086
  docker exec "$CONTAINER" pg_restore $RESTORE_FLAGS \
    --username "$PGUSER_NAME" --dbname "$DATABASE" "$REMOTE"
  docker exec "$CONTAINER" rm -f "$REMOTE"
fi
info "Postgres restaurado."

# --- LanceDB ------------------------------------------------------------------
if [ -d "$LANCEDB_SNAPSHOT" ]; then
  if [ -z "$LANCEDB_DEST" ]; then
    info "AVISO: o backup tem vetores mas LANCEDB_PATH não está definido."
    info "       Rode de novo com --lancedb <caminho> para restaurá-los."
  else
    if [ -e "$LANCEDB_DEST" ]; then
      ANTIGO="$LANCEDB_DEST.pre-restore.$(date -u +%Y%m%dT%H%M%SZ)"
      mv "$LANCEDB_DEST" "$ANTIGO"
      info "diretório de vetores existente movido para $ANTIGO"
    fi
    mkdir -p "$(dirname "$LANCEDB_DEST")"
    cp -R "$LANCEDB_SNAPSHOT" "$LANCEDB_DEST"
    info "vetores restaurados em $LANCEDB_DEST"
  fi
else
  info "backup sem snapshot de vetores — nada a restaurar do lado do LanceDB."
fi

# --- prova ---------------------------------------------------------------------
# Restore que não mostra o que voltou não é restore verificado, é restore
# declarado. Estas contagens são o aceite da v1.4 em uma linha cada.
info "conferindo o que voltou:"
CONTAGEM="SELECT 'goals' AS tabela, count(*) FROM goals
          UNION ALL SELECT 'tasks', count(*) FROM tasks
          UNION ALL SELECT 'conversations', count(*) FROM conversations
          UNION ALL SELECT 'chat_messages', count(*) FROM chat_messages
          UNION ALL SELECT 'system_settings', count(*) FROM system_settings
          ORDER BY 1;"

if [ "$MODE" = "local" ]; then
  psql --username "$PGUSER_NAME" --dbname "$DATABASE" -c "$CONTAGEM"
else
  docker exec "$CONTAINER" psql --username "$PGUSER_NAME" --dbname "$DATABASE" \
    -c "$CONTAGEM"
fi

info "restore concluído."
