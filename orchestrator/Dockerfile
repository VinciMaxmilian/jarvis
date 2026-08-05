# Orchestrator (Executive Function + GoalManager, loop asyncio) — multi-stage.
#
# ATENÇÃO: o contexto de build é a RAIZ do monorepo, não esta pasta —
# a instalação sai do pyproject.toml da raiz, única fonte de verdade das deps.
#   docker build -f orchestrator/Dockerfile .
# O compose já faz isso: `context: ../..`.
#
# O estágio `builder` é idêntico ao de apps/api/Dockerfile de propósito: mesmas
# instruções, mesmo hash de camada, então o segundo build reaproveita o cache do
# primeiro e as deps são baixadas UMA vez. Se mudar um, mude o outro junto.
#
# Sem build-essential: todas as deps da v0 têm wheel manylinux cp312
# (psycopg[binary] já é o wheel com libpq embutida, asyncpg publica cp312).
# Se um dia faltar wheel, o gcc entra no `builder` — nunca no runtime.

# --------------------------------------------------------------------------- #
# Estágio 1 — dependências
# --------------------------------------------------------------------------- #
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PATH="/opt/venv/bin:$PATH"

# venv em /opt/venv, fora de /app: o volume de código do dev não enterra as deps.
RUN python -m venv /opt/venv

# webrtcvad precisa de compilador C
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends gcc g++ python3-dev && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Camada de dependência: só o manifesto, para editar código não reinstalar nada.
COPY pyproject.toml ./

# Smoke test: falha no BUILD se um driver não importar. Linha IDÊNTICA à de
# apps/api/Dockerfile de propósito — é o que faz os dois builds compartilharem a
# camada de dependências em vez de instalar tudo duas vezes.
RUN python -c "import pathlib, tomllib; deps = tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['dependencies']; pathlib.Path('/tmp/requirements.txt').write_text(chr(10).join(deps))" \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && python -c "import fastapi, uvicorn, asyncpg, psycopg, alembic, sqlalchemy, openai, anthropic, structlog, webrtcvad, faster_whisper, edge_tts, pydub, PIL"

# --------------------------------------------------------------------------- #
# Estágio 2 — runtime
# --------------------------------------------------------------------------- #
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

RUN useradd --create-home --uid 10001 jarvis

# Cópia seletiva. O orchestrator importa apps.api.db, apps.api.deps e
# packages.agents.* (ver orchestrator/main.py), então apps/api entra também —
# não é sobra, é dependência real de import.
COPY --chown=jarvis:jarvis pyproject.toml alembic.ini ./
COPY --chown=jarvis:jarvis packages ./packages
COPY --chown=jarvis:jarvis apps/api ./apps/api
COPY --chown=jarvis:jarvis orchestrator ./orchestrator

USER jarvis

# Sem HEALTHCHECK: este processo não expõe porta nem endpoint. Um healthcheck de
# "processo vivo" sempre passa (o PID 1 É o processo) e daria falsa segurança —
# `restart: unless-stopped` no compose cobre queda de verdade. Health real depende
# de heartbeat do Executive no Postgres/Redis, que é trabalho de v1.
CMD ["python", "-m", "orchestrator.main"]
