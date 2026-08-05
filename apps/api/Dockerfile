# API FastAPI da v0 — imagem multi-stage.
#
# ATENÇÃO: o contexto de build é a RAIZ do monorepo, não esta pasta —
# a instalação sai do pyproject.toml da raiz, que é a única fonte de verdade das
# dependências (requirements.txt é um espelho e pode divergir).
#   docker build -f apps/api/Dockerfile .
# O compose já faz isso: `context: ../..`.
#
# Por que multi-stage: o estágio `builder` é o único lugar onde um toolchain de
# compilação poderia entrar. O `runtime` recebe só o venv pronto e o código, então
# nem o pip cache nem um eventual gcc sobram na imagem final.
#
# Por que NÃO instalamos build-essential: todas as dependências da v0 têm wheel
# manylinux para cp312 — inclusive as duas suspeitas de sempre:
#   - psycopg[binary]  -> o extra `[binary]` É o wheel com a libpq embutida;
#                         instalar gcc/libpq-dev aqui seria trabalho jogado fora.
#   - asyncpg          -> publica wheel cp312 manylinux_x86_64.
#   - pydantic-core / uvloop / httptools / watchfiles -> wheels prontos.
# Se algum dia uma dependência perder o wheel, o pip vai falhar no `builder` com
# mensagem clara: aí o `apt-get install gcc` entra AQUI, e só aqui.

# --------------------------------------------------------------------------- #
# Estágio 1 — dependências
# --------------------------------------------------------------------------- #
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PATH="/opt/venv/bin:$PATH"

# venv em /opt/venv, FORA de /app. Isso é o que faz o volume de código do dev
# (`../..:/app`) não enterrar as dependências instaladas.
RUN python -m venv /opt/venv

# webrtcvad precisa de compilador C
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends gcc g++ python3-dev && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Camada de dependência: só o manifesto. Editar código não invalida esta camada,
# então o `pip install` (a parte lenta) roda de novo apenas quando o
# pyproject.toml muda de verdade.
COPY pyproject.toml ./

# Extrai `[project].dependencies` do pyproject com tomllib (stdlib no 3.12) e
# instala só as dependências — o pacote `jarvis` em si não é instalado.
# Motivo: o código do monorepo é servido por PYTHONPATH=/app (ver runtime), o que
# funciona igual com a imagem crua e com o bind mount do dev, sem depender de
# install editável nem de diretório-fantasma para o setuptools resolver.
# chr(10) em vez de "\n" para não misturar escape de shell com escape de Docker.
# O import final é smoke test: falha no BUILD se um driver não importar, em vez de
# falhar no primeiro request. Mantenha esta linha IDÊNTICA à do
# orchestrator/Dockerfile — é o que faz os dois builds compartilharem a camada.
RUN python -c "import pathlib, tomllib; deps = tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['dependencies']; pathlib.Path('/tmp/requirements.txt').write_text(chr(10).join(deps))" \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && python -c "import fastapi, uvicorn, asyncpg, psycopg, alembic, sqlalchemy, openai, anthropic, structlog, webrtcvad, faster_whisper, edge_tts, pydub, PIL"

# --------------------------------------------------------------------------- #
# Estágio 2 — runtime
# --------------------------------------------------------------------------- #
FROM python:3.12-slim AS runtime

# PYTHONDONTWRITEBYTECODE: o /app do dev é bind mount de disco Windows e o
#   container roda como não-root — escrever __pycache__ lá é lento e inútil.
# PYTHONPATH=/app: explícito em vez de depender do cwd. Vale para uvicorn, para o
#   alembic e para qualquer `python -c` de manutenção.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app

# Só o venv atravessa. Nada de pip cache, nada de toolchain.
COPY --from=builder /opt/venv /opt/venv

# --------------------------------------------------------------------------- #
# ffmpeg — decodificador de MP3 do caminho de voz (apps/api/routers/voice.py).
#
# Por que um BINÁRIO e não um pacote pip: o `pydub` não decodifica MP3 sozinho.
# Ele monta uma linha de comando e chama `ffmpeg`/`avconv` por subprocesso. Sem o
# executável no PATH, `pip install pydub` instala com sucesso, o import passa
# (só emite um RuntimeWarning) e a falha só aparece no primeiro
# `AudioSegment.from_file(..., format="mp3")` — em produção, no meio de uma
# conversa por voz. Ou seja: é a única dependência da API que o pyproject.toml
# NÃO consegue declarar, e por isso mora aqui.
#
# Onde ele é exigido: o edge-tts devolve MP3, e voice.py decodifica para
# reamostrar a 24 kHz mono 16-bit e mandar PCM cru pelo WebSocket, que é o que o
# player do PWA espera. Trocar o front para receber MP3 e decodificar com
# `decodeAudioData` eliminaria esta dependência inteira — vale reconsiderar se o
# tamanho da imagem apertar.
#
# Não confundir com o `export(format="wav")` da mesma rota: WAV o pydub escreve
# pelo módulo `wave` da stdlib, sem tocar no ffmpeg. Só o lado do MP3 precisa.
#
# NÃO está no runtime do orchestrator de propósito: aquele serviço importa
# apps.api.db, apps.api.deps e packages.agents.*, nunca routers/voice.py.
RUN set -eux; \
    apt-get update -qq; \
    apt-get install -y -qq --no-install-recommends ffmpeg; \
    rm -rf /var/lib/apt/lists/*; \
    ffmpeg -version

# --------------------------------------------------------------------------- #
# postgresql-client-16 — o binário `pg_dump` do job de backup (v1.4).
#
# Por que na imagem e não instalado na hora: `infrastructure/scripts/backup.sh`
# instalava o cliente a cada execução, o que faz o backup das 3h depender de
# `apt-get update`, de rede e do repositório da PostgreSQL estarem de pé. A noite
# em que a rede cai é exatamente a noite em que o backup importa.
#
# Por que a versão 16 explicitamente, e do PGDG: esta imagem é Debian trixie,
# cujo `postgresql-client` padrão é o **17**, e o servidor do compose é
# `postgres:16-alpine`. `pg_dump` 17 contra servidor 16 grava
# `SET transaction_timeout = 0` no arquivo — parâmetro que só existe a partir do
# 17 — e o `pg_restore` morre no meio, com o banco já limpo pelo `--clean`. O
# backup era gravado com sucesso e só se descobria inútil no dia do desastre.
# Trocou a imagem do Postgres no compose? Troque PG_MAJOR aqui e em backup.sh.
ARG PG_MAJOR=16
RUN set -eux; \
    apt-get update -qq; \
    apt-get install -y -qq --no-install-recommends curl ca-certificates gnupg; \
    install -d /usr/share/postgresql-common/pgdg; \
    curl -sS --fail -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
        https://www.postgresql.org/media/keys/ACCC4CF8.asc; \
    . /etc/os-release; \
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list; \
    apt-get update -qq; \
    apt-get install -y -qq --no-install-recommends "postgresql-client-${PG_MAJOR}"; \
    apt-get purge -y -qq curl gnupg; \
    apt-get autoremove -y -qq; \
    rm -rf /var/lib/apt/lists/*; \
    "/usr/lib/postgresql/${PG_MAJOR}/bin/pg_dump" --version

# No PATH: sem isto o `pg_dump` só é alcançável pelo caminho absoluto, e o job
# passaria a depender de uma variável de ambiente para achar o próprio binário.
ENV PATH="/usr/lib/postgresql/16/bin:$PATH"

WORKDIR /app

# Usuário não-root criado ANTES do COPY, para o --chown resolver o nome.
RUN useradd --create-home --uid 10001 jarvis

# Camada de código, a que muda a cada commit. Cópia seletiva: entra só o que a
# API importa de verdade (main -> routers -> db -> packages.*), mais o
# alembic.ini das migrations. graphify-out, docs, tools e apps/web ficam fora.
COPY --chown=jarvis:jarvis pyproject.toml alembic.ini ./
COPY --chown=jarvis:jarvis packages ./packages
COPY --chown=jarvis:jarvis apps/api ./apps/api

USER jarvis

EXPOSE 8000

# Bate no /health real de apps/api/main.py (não inventa rota). Porta fixa em 8000
# porque é a do CMD; se API_PORT mudar, muda aqui também.
# urlopen levanta em status != 2xx, o que já faz o exit != 0 exigido pelo Docker.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).read()"]

# CMD = PRODUÇÃO: sem --reload.
#   --workers 1 é deliberado, não preguiça: sistema single-user, com WebSocket de
#   streaming e estado em processo. Mais de um worker exigiria sticky session sem
#   entregar throughput que um dono só precise.
# Em DEV o compose sobrescreve este command para acrescentar --reload, que só faz
# sentido lá porque o código chega por volume.
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]

# --------------------------------------------------------------------------- #
# Estágio 3 — test: pytest + mypy + ruff + black
#
# Por que existe: nenhum interpretador da máquina roda a suíte hoje. Os venvs de
# apps/api e orchestrator têm as deps da app mas não têm pytest; o Python do
# sistema tem pytest mas não tem anthropic nem structlog, e a coleta morre no
# import do conftest. "pytest verde" é o aceite da v1.0 (plan-execution.md §3) —
# um aceite que ninguém consegue executar não é aceite.
#
# Por que estágio separado e não deps de dev no runtime: pytest, mypy e ruff não
# têm o que fazer numa imagem que serve requisição, e a imagem de produção não
# deve mudar de tamanho por causa de ferramenta de desenvolvimento.
#
# Herda de `builder` (não de `runtime`) porque precisa do pip e do venv gravável.
# Fica DEPOIS do runtime no arquivo, então um `docker build` sem --target pararia
# aqui: por isso api e migrate declaram `target: runtime` no compose.
# --------------------------------------------------------------------------- #
FROM builder AS test

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

# Mesma extração de antes, agora sobre [project.optional-dependencies].dev — a
# lista real do pyproject, não uma cópia que envelhece em silêncio.
RUN python -c "import pathlib, tomllib; deps = tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['optional-dependencies']['dev']; pathlib.Path('/tmp/dev-requirements.txt').write_text(chr(10).join(deps))" \
    && pip install --no-cache-dir -r /tmp/dev-requirements.txt \
    && python -c "import pytest, pytest_asyncio, mypy, ruff, black"

# O mesmo `postgresql-client-16` do runtime, pelo mesmo motivo — ver o bloco
# grande no estágio `runtime`. Aqui ele não é luxo: `backup.sh` roda o job dentro
# deste serviço, e é neste container que o backup do dia a dia acontece.
# Repetido em vez de herdado porque `test` deriva de `builder`, não de `runtime`.
ARG PG_MAJOR=16
RUN set -eux; \
    apt-get update -qq; \
    apt-get install -y -qq --no-install-recommends curl ca-certificates gnupg; \
    install -d /usr/share/postgresql-common/pgdg; \
    curl -sS --fail -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
        https://www.postgresql.org/media/keys/ACCC4CF8.asc; \
    . /etc/os-release; \
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list; \
    apt-get update -qq; \
    apt-get install -y -qq --no-install-recommends "postgresql-client-${PG_MAJOR}"; \
    rm -rf /var/lib/apt/lists/*; \
    "/usr/lib/postgresql/${PG_MAJOR}/bin/pg_dump" --version

ENV PATH="/usr/lib/postgresql/16/bin:$PATH"

WORKDIR /app

# Sem COPY do código: o compose monta o repo em /app. Rodar teste contra código
# congelado na imagem obrigaria a rebuildar a cada edição, que é o oposto do uso.
# Root de propósito: mypy e pytest escrevem cache, e o bind mount vem do host.
CMD ["pytest"]
