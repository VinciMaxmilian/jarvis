"""Entrypoint FastAPI — v0.5.

Lifespan gerencia engine do DB. Rotas em routers/.
Structlog configurado no boot. Brain.html servido como estático.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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


async def _aquecer_agno() -> None:
    """Constrói o singleton do Agno Knowledge fora do caminho de uma requisição.

    **MEDIDO: 8,26 segundos.** `get_agno_knowledge()` é síncrona e faz I/O de
    banco na construção (o `__post_init__` do Knowledge cria a tabela se não
    existir). É singleton, então o custo é uma vez por processo — mas essa uma vez
    caía inteira na PRIMEIRA mensagem depois de todo boot, dentro de
    `get_tool_executor`, no caminho quente.

    Em produção isso é um susto por restart. Em desenvolvimento, com `--reload`,
    o processo reinicia a cada arquivo salvo — e aí toda primeira mensagem depois
    de uma edição paga 8s. Foi exatamente esse o motivo das primeiras chamadas de
    voz ficarem mudas: o dono falava, esperava, e desligava antes de a construção
    terminar. Em estado estável o mesmo pedido leva 1,8s.

    `to_thread` porque a função é síncrona e bloqueante: chamada direto aqui, ela
    seguraria o event loop inteiro por 8s durante o boot — o oposto do que este
    aquecimento existe para fazer.
    """
    logger = structlog.get_logger("jarvis.api")
    try:
        from packages.rag.agno_knowledge import get_agno_knowledge

        inicio = asyncio.get_running_loop().time()
        await asyncio.to_thread(get_agno_knowledge)
        logger.info(
            "api.agno.aquecido",
            segundos=round(asyncio.get_running_loop().time() - inicio, 2),
        )
    except Exception as exc:
        logger.warning("api.agno.aquecimento_falhou", error=str(exc))


async def _aquecer_mcp() -> None:
    """Sobe os servidores MCP fora do caminho de uma requisição.

    **O problema que isto resolve.** `get_mcp_manager` (apps/api/deps.py) é
    preguiçoso: o primeiro `discover_and_connect` acontece dentro da primeira
    chamada que precisar de tools. Cada servidor leva ~4-5s e eles sobem em
    série, então a PRIMEIRA mensagem depois de todo restart pagava ~15-17s antes
    de o modelo sequer ser chamado.

    No chat de texto isso era ruim. Na conversa por voz é fatal: quinze segundos
    de silêncio absoluto lêem como travamento, e o cliente desiste — foi
    exatamente o que aconteceu na primeira chamada de voz real, com o WebSocket
    fechando em 1006 no instante em que a resposta ficava pronta.

    **Por que em tarefa de fundo e não no corpo do lifespan.** Bloquear o startup
    por 17s adiaria o `/health` no mesmo tanto, e o HEALTHCHECK do container tem
    `start-period=30s`: um servidor MCP lento a mais e o Docker passaria a matar
    a API no boot. Aquecer em paralelo dá o ganho sem apostar o boot nisso.

    **Por que a falha só loga.** MCP é opcional por natureza — um servidor do
    host fora do ar não pode impedir a API de servir chat. `get_mcp_manager`
    continua sendo a autoridade; isto aqui só antecipa o trabalho dele.
    """
    logger = structlog.get_logger("jarvis.api")
    try:
        from apps.api.deps import get_mcp_manager

        manager = await get_mcp_manager()
        logger.info(
            "api.mcp.aquecido",
            servidores=len(manager.servers),
            tools=len(manager.tool_routes),
        )
    except Exception as exc:
        logger.warning("api.mcp.aquecimento_falhou", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown."""
    _configure_logging()
    logger = structlog.get_logger("jarvis.api")
    logger.info("api.starting")

    # Os dois em paralelo entre si: o Agno é I/O de banco numa thread e o MCP é
    # subprocesso, então esperar um pelo outro só somaria latência de boot.
    aquecimentos = [
        asyncio.create_task(_aquecer_agno()),
        asyncio.create_task(_aquecer_mcp()),
    ]

    yield

    # Cancelar antes de descer: se o dono derrubar a API durante o aquecimento,
    # as tarefas continuariam falando com banco e subprocessos que estão sendo
    # encerrados.
    for tarefa in aquecimentos:
        if not tarefa.done():
            tarefa.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await asyncio.gather(*aquecimentos, return_exceptions=True)

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

    # ----------------------------------------------------------------------- #
    # /media/images — as imagens gravadas por `save_modified_image`.
    #
    # Sem este mount a tool era inútil mesmo com o Pillow instalado: ela devolvia
    # `caminho` (um path de filesystem, `/app/data/images/mod_xxx.png`), e o
    # navegador não tem como abrir isso. Não havia rota estática nenhuma na app —
    # o resultado da edição existia em disco e era inalcançável pelo PWA.
    #
    # Diretório criado no import, não na primeira chamada: `StaticFiles` valida a
    # existência do diretório no mount e derruba a app se ele faltar. Numa
    # clonagem nova, `data/images` não existe até alguém editar uma imagem, e a
    # API não subiria.
    #
    # Fica ATRÁS do Cloudflare Access, como todo o resto: `public_paths` só libera
    # `/health`. Imagem que o dono editou não é conteúdo público.
    media_root = Path(__file__).resolve().parents[2] / "data" / "images"
    media_root.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/media/images",
        StaticFiles(directory=str(media_root)),
        name="media-images",
    )

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
