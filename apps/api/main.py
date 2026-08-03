"""Entrypoint FastAPI — v0.5.

Lifespan gerencia engine do DB. Rotas em routers/.
Structlog configurado no boot. Brain.html servido como estático.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from apps.api.cf_access import install_cloudflare_access
from apps.api.db.engine import dispose_engine
from apps.api.routers import chat, goals, history, settings, tools, memory, voice
from packages.shared.settings import get_settings


def _configure_logging() -> None:
    settings = get_settings()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer()
            if settings.environment == "dev"
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown."""
    _configure_logging()
    logger = structlog.get_logger("jarvis.api")
    logger.info("api.starting")
    yield
    await dispose_engine()
    logger.info("api.stopped")


def create_app() -> FastAPI:
    sys_settings = get_settings()

    app = FastAPI(
        title="Jarvis API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # A ORDEM DESTES DOIS `add_middleware` É SIGNIFICATIVA E ESTÁ INVERTIDA DE
    # PROPÓSITO. O Starlette insere cada middleware novo no TOPO da pilha, então
    # o ÚLTIMO registrado é o MAIS EXTERNO. Registrando o Access primeiro e o
    # CORS depois, a pilha final fica CORS -> Access -> rotas.
    #
    # É a ordem certa por causa do preflight: o navegador manda `OPTIONS` sem
    # cookie e sem header de autenticação (a especificação de CORS proíbe
    # credenciais no preflight). Com o Access por fora, todo preflight tomaria
    # 401, o browser jamais mandaria a requisição real e o PWA quebraria com um
    # erro de CORS que não tem nada a ver com CORS. Com o CORS por fora, ele
    # responde o preflight sozinho — que não carrega dado nenhum — e a requisição
    # real, essa sim, passa pelo Access.
    install_cloudflare_access(app, sys_settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=sys_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
    app.include_router(goals.router, prefix="/api/goals", tags=["goals"])
    app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
    app.include_router(tools.router, prefix="/api/tools", tags=["tools"])
    app.include_router(history.router, prefix="/api/history", tags=["history"])
    app.include_router(memory.router, prefix="/api/memory", tags=["memory"])
    app.include_router(voice.router, prefix="/api/voice", tags=["voice"])

    @app.get("/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/brain.html")
    async def serve_brain() -> FileResponse:
        """Serve graphify brain.html for the Brain page."""
        import os
        brain_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "graphify-out", "graph.html",
        )
        return FileResponse(brain_path, media_type="text/html")

    return app


app = create_app()
