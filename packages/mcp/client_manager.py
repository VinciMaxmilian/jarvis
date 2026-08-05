"""Gerenciador de Clientes MCP (Model Context Protocol).

Descobre servidores MCP na pasta `mcp/` e fornece uma interface unificada
para listar e invocar ferramentas de todos eles.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any, AsyncIterator
import contextlib

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import structlog

logger = structlog.get_logger(__name__)


#: Teto para uma chamada de tool de MCP, em segundos.
#:
#: **Por que existe.** Não havia teto nenhum. Quando a conexão SSE do host caía
#: NO MEIO de uma chamada — observado em produção logo depois de um
#: `desktop_clicar` —, o `await` da sessão ficava pendurado para sempre: o turno
#: nunca terminava, nenhuma exceção subia, e o dono simplesmente não recebia
#: resposta. Um erro que trava é pior que um erro que estoura, porque não deixa
#: rastro nem no log.
#:
#: 45s e não 5s porque as tools de desktop tiram screenshot: capturar, redimensionar
#: e trafegar ~200 KB de base64 leva segundos de verdade. O teto existe para
#: pegar conexão morta, não para apertar tool lenta.
_TIMEOUT_TOOL = float(os.environ.get("MCP_TOOL_TIMEOUT", "45"))

#: Teto para listar tools. Bem menor: `get_tools_specs` roda a CADA mensagem, e
#: um servidor pendurado aqui é silêncio direto na resposta ao dono.
_TIMEOUT_LIST = float(os.environ.get("MCP_LIST_TIMEOUT", "10"))

#: Intervalo entre tentativas de reatar um servidor que não subiu no boot.
#: 20s equilibra as duas pontas: o dono sobe o host e o Jarvis o enxerga na
#: mensagem seguinte, sem que um host permanentemente fora do ar custe uma
#: tentativa de conexão em toda frase da conversa.
_INTERVALO_PENDENTE = float(os.environ.get("MCP_RETRY_INTERVAL", "20"))


def _descrever(exc: BaseException) -> str:
    """Exceção → texto que serve num log.

    `str(exc)` de `RemoteProtocolError` e de boa parte dos erros de transporte do
    anyio/httpx é VAZIO. O log saía `error=` — um erro sem mensagem, que é o
    mesmo que não logar. O nome da classe sempre existe e já diz muito.
    """
    texto = str(exc).strip()
    return f"{type(exc).__name__}: {texto}" if texto else type(exc).__name__


class MCPServerInstance:
    """Uma instância de conexão com um servidor MCP."""

    def __init__(self, name: str, params: StdioServerParameters | str):
        self.name = name
        self.params = params
        self._exit_stack = contextlib.AsyncExitStack()
        self.session: ClientSession | None = None

    async def connect(self) -> None:
        try:
            if isinstance(self.params, str):
                # self.params é uma URL para o SSE
                from mcp.client.sse import sse_client

                sse_transport = await self._exit_stack.enter_async_context(
                    sse_client(self.params)
                )
                read, write = sse_transport
            else:
                # self.params é StdioServerParameters
                from mcp.client.stdio import stdio_client

                stdio_transport = await self._exit_stack.enter_async_context(
                    stdio_client(self.params)
                )
                read, write = stdio_transport

            self.session = await self._exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            await self.session.initialize()
            logger.info("mcp.server.connected", server=self.name)
        except Exception as exc:
            logger.error("mcp.server.failed", server=self.name, error=str(exc))
            raise

    async def close(self) -> None:
        await self._exit_stack.aclose()


class MCPClientManager:
    """Gerencia conexões com servidores MCP e expõe suas ferramentas."""

    def __init__(self, mcp_dir: Path) -> None:
        self.mcp_dir = mcp_dir
        self.servers: dict[str, MCPServerInstance] = {}
        # Mapeia tool_name para o nome do servidor que a provê
        self.tool_routes: dict[str, str] = {}
        #: Servidores que DEVERIAM existir e não conectaram. Nome → params.
        #:
        #: Sem isto, servidor fora do ar no boot da API ficava fora para sempre:
        #: `reconectar` só sabe recriar o que já está em `self.servers`, e a
        #: descoberta roda uma vez só. O caso real é o MCP do host Windows, que
        #: o dono sobe e derruba à mão — subir o host DEPOIS da API deixava o
        #: Jarvis sem as 19 tools de desktop até alguém reiniciar o container,
        #: e o modelo então respondia que não tinha ferramenta para isso.
        self._pendentes: dict[str, StdioServerParameters | str] = {}
        self._proxima_tentativa = 0.0

    async def discover_and_connect(self) -> None:
        """Encontra e conecta a todos os servidores MCP em diretórios filhos."""
        if not self.mcp_dir.exists():
            return

        for child in self.mcp_dir.iterdir():
            if child.is_dir() and (child / "main.py").exists():
                server_name = child.name
                if server_name in self.servers:
                    continue

                # Marcador `HOST_ONLY`: o servidor só faz sentido no Windows do
                # dono, não aqui dentro. Subir `jarvis_windows_host` como stdio
                # no container daria uma de duas coisas ruins — falha de import
                # engolida pelo `except` abaixo (ruído), ou, pior, se as libs
                # existissem na imagem, um servidor conectado que fotografa uma
                # tela que não existe e rouba a rota das tools do host real.
                if (child / "HOST_ONLY").exists():
                    logger.debug("mcp.server.host_only.skipped", server=server_name)
                    continue

                params = StdioServerParameters(
                    command=sys.executable,
                    args=[str(child / "main.py")],
                )

                instance = MCPServerInstance(server_name, params)
                try:
                    await instance.connect()
                    self.servers[server_name] = instance

                    # Carrega as tools
                    assert instance.session is not None
                    tools_result = await instance.session.list_tools()
                    for tool in tools_result.tools:
                        self.tool_routes[tool.name] = server_name

                    logger.info(
                        "mcp.server.registered",
                        server=server_name,
                        tools=len(tools_result.tools),
                    )
                except Exception:
                    # Log já foi emitido pelo connect()
                    pass

        # Tentar conectar no nosso MCP Central via SSE rodando no Windows Host
        # Usa host.docker.internal para sair do Docker e acessar o localhost do Windows
        host_server_name = "Jarvis-Windows-Host"
        if host_server_name not in self.servers:
            sse_url = os.environ.get(
                "WINDOWS_MCP_URL", "http://host.docker.internal:8765/sse"
            )
            instance = MCPServerInstance(host_server_name, sse_url)
            try:
                await instance.connect()
                self.servers[host_server_name] = instance

                assert instance.session is not None
                tools_result = await instance.session.list_tools()
                for tool in tools_result.tools:
                    self.tool_routes[tool.name] = host_server_name

                logger.info(
                    "mcp.server.registered",
                    server=host_server_name,
                    tools=len(tools_result.tools),
                )
            except Exception as exc:
                # O servidor pode não estar rodando no Windows. Não derruba nada,
                # mas TAMBÉM não some: quando o dono pedir "clica ali" e o Jarvis
                # responder que não tem como, a causa é esta linha. Silêncio total
                # aqui transformava "esqueci de subir o host" em "o agente é burro".
                self._pendentes[host_server_name] = sse_url
                logger.warning(
                    "mcp.host.indisponivel",
                    server=host_server_name,
                    url=sse_url,
                    error=str(exc),
                    dica="suba o MCP do host: scripts/run_desktop_host.ps1",
                )

    async def tentar_pendentes(self) -> None:
        """Reata servidores que não subiram no boot. Barato e com intervalo.

        Chamado de `get_tools_specs`, que roda a cada mensagem — daí o intervalo:
        tentar um SSE fora do ar a cada frase do dono somaria o timeout de
        conexão em toda resposta. Uma tentativa a cada `_INTERVALO_PENDENTE`
        segundos é rápida o bastante para o dono não perceber a espera entre
        subir o host e o Jarvis enxergar as ferramentas.
        """
        if not self._pendentes or time.monotonic() < self._proxima_tentativa:
            return
        self._proxima_tentativa = time.monotonic() + _INTERVALO_PENDENTE

        for nome, params in list(self._pendentes.items()):
            instancia = MCPServerInstance(nome, params)
            try:
                await asyncio.wait_for(instancia.connect(), timeout=_TIMEOUT_LIST)
                assert instancia.session is not None
                tools_result = await asyncio.wait_for(
                    instancia.session.list_tools(), timeout=_TIMEOUT_LIST
                )
            except Exception:
                continue  # `connect` já logou; segue pendente para a próxima
            self.servers[nome] = instancia
            self._pendentes.pop(nome, None)
            for tool in tools_result.tools:
                self.tool_routes[tool.name] = nome
            logger.info(
                "mcp.pendente.conectado", server=nome, tools=len(tools_result.tools)
            )

    async def reconectar(self, server_name: str) -> bool:
        """Recria a conexão de um servidor cuja sessão morreu. `True` se voltou.

        **Por que isto precisa existir.** A sessão era criada uma vez e guardada
        para sempre. Quando o processo do outro lado reiniciava — e o MCP do host
        Windows reinicia toda vez que o dono mexe nele — a sessão virava um objeto
        morto que ninguém trocava: `sse_reader` levantava
        `RemoteProtocolError: peer closed connection`, e a partir dali TODA tool
        daquele servidor falhava com erro vazio, até alguém reiniciar a API.
        Observado em produção: o agente perdeu as 19 tools de desktop no meio de
        uma tarefa e passou a inventar nomes de tool que não existiam.

        Instância NOVA em vez de reaproveitar a antiga: o `AsyncExitStack` da
        conexão quebrada foi aberto em outra task, e fechá-lo daqui levanta
        `Attempted to exit cancel scope in a different task`. Abandonar o objeto
        velho é mais barato que propagar isso para quem só queria chamar uma tool.
        """
        antigo = self.servers.get(server_name)
        if antigo is None:
            return False

        with contextlib.suppress(Exception):
            await antigo.close()

        novo = MCPServerInstance(server_name, antigo.params)
        try:
            # Com teto: reconectar num servidor que aceita TCP mas não completa o
            # handshake penduraria aqui, e este caminho roda dentro do turno.
            await asyncio.wait_for(novo.connect(), timeout=_TIMEOUT_LIST)
            assert novo.session is not None
            tools_result = await asyncio.wait_for(
                novo.session.list_tools(), timeout=_TIMEOUT_LIST
            )
        except Exception as exc:
            logger.warning(
                "mcp.reconectar.falhou", server=server_name, error=_descrever(exc)
            )
            return False

        self.servers[server_name] = novo
        for tool in tools_result.tools:
            self.tool_routes[tool.name] = server_name
        logger.info("mcp.reconectado", server=server_name, tools=len(tools_result.tools))
        return True

    async def get_tools_specs(self) -> list[dict[str, Any]]:
        """Devolve as especificações das ferramentas prontas para o LLM.

        NOTA DE CUSTO: isto interroga TODOS os servidores por `list_tools()`, em
        série, e é chamado a cada mensagem (`ChiefAI.respond` monta o catálogo
        antes de cada chamada ao modelo). Um servidor stdio lento entra
        integralmente no tempo de resposta, e num canal de voz esse tempo é
        silêncio. O log por servidor abaixo existe para que "está demorando" seja
        atribuível a um nome, em vez de virar um buraco anônimo na linha do tempo.
        """
        # Servidor que estava fora do ar no boot entra aqui, e não só num
        # restart da API: o dono sobe o MCP do host quando precisa dele, e o
        # catálogo é o único ponto que roda com frequência suficiente para
        # perceber isso sozinho.
        await self.tentar_pendentes()

        # Usa um dicionário para evitar duplicatas pelo nome da ferramenta
        specs_by_name = {}
        # `list(...)`: `reconectar` troca o valor dentro de `self.servers`, e
        # iterar o dict enquanto ele muda levanta RuntimeError.
        for server_name in list(self.servers):
            instance = self.servers[server_name]
            if not instance.session:
                continue
            try:
                _t0 = time.perf_counter()
                tools_result = await asyncio.wait_for(
                    instance.session.list_tools(), timeout=_TIMEOUT_LIST
                )
                _dt = time.perf_counter() - _t0
                if _dt > 0.5:
                    logger.warning(
                        "mcp.list_tools.lento", server=server_name, segundos=round(_dt, 2)
                    )
                for tool in tools_result.tools:
                    # Apenas inclui se este servidor for a rota atual da ferramenta
                    # (isso evita duplicatas caso o servidor stdio e o SSE exportem a mesma tool)
                    if self.tool_routes.get(tool.name) == server_name:
                        specs_by_name[tool.name] = {
                            "name": tool.name,
                            "description": tool.description or "",
                            "input_schema": tool.inputSchema,
                        }
            except Exception as exc:
                # `_descrever` e não `str(exc)`: RemoteProtocolError chega com
                # mensagem vazia, e o log saía como `error=` — um erro sem texto
                # nenhum, que foi exatamente o que escondeu a queda da conexão.
                logger.error(
                    "mcp.list_tools.failed", server=server_name, error=_descrever(exc)
                )
                # Catálogo é o primeiro lugar onde a queda aparece: ele roda a
                # cada mensagem. Reconectar aqui costuma consertar antes que o
                # dono peça alguma coisa.
                if await self.reconectar(server_name):
                    with contextlib.suppress(Exception):
                        sessao = self.servers[server_name].session
                        assert sessao is not None
                        for tool in (await sessao.list_tools()).tools:
                            if self.tool_routes.get(tool.name) == server_name:
                                specs_by_name[tool.name] = {
                                    "name": tool.name,
                                    "description": tool.description or "",
                                    "input_schema": tool.inputSchema,
                                }
        return list(specs_by_name.values())

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoca uma ferramenta roteando para o servidor MCP correto."""
        server_name = self.tool_routes.get(name)
        if not server_name:
            raise KeyError(f"Ferramenta '{name}' não encontrada nos servidores MCP.")

        instance = self.servers.get(server_name)
        if not instance or not instance.session:
            if not await self.reconectar(server_name):
                raise RuntimeError(f"Servidor MCP '{server_name}' desconectado.")
            instance = self.servers[server_name]

        assert instance.session is not None
        try:
            result = await asyncio.wait_for(
                instance.session.call_tool(name, arguments=arguments),
                timeout=_TIMEOUT_TOOL,
            )
        except Exception as exc:
            # Uma tentativa de reconexão, e uma só. Se o servidor está fora do
            # ar de verdade, insistir aqui transformaria uma falha rápida numa
            # espera longa no meio do turno do dono.
            logger.warning(
                "mcp.call_tool.sessao_morta",
                server=server_name,
                tool=name,
                error=_descrever(exc),
            )
            if not await self.reconectar(server_name):
                return {
                    "error": (
                        f"o servidor MCP '{server_name}' caiu e não voltou "
                        f"({_descrever(exc)}). Se for o host Windows, confira se "
                        "scripts/run_desktop_host.ps1 está rodando."
                    )
                }
            sessao = self.servers[server_name].session
            assert sessao is not None
            try:
                result = await asyncio.wait_for(
                    sessao.call_tool(name, arguments=arguments), timeout=_TIMEOUT_TOOL
                )
            except Exception as exc2:
                return {
                    "error": (
                        f"a tool '{name}' falhou mesmo depois de reconectar "
                        f"({_descrever(exc2)})."
                    )
                }

        # O resultado do MCP tem isError e content (lista de text/image).
        #
        # O bloco `image` era DESCARTADO em silêncio aqui. Uma tool que fotografa
        # a tela (`desktop_capturar_tela`) chegava ao modelo como um resultado
        # vazio, e ele respondia sobre a captura que nunca viu. Hoje o base64 sai
        # em `images`, separado do texto de propósito: quem consome (o laço do
        # `ChiefAI`) manda imagem pelo canal multimodal do provider, não
        # empacotada num JSON de tool result — 1 MB de base64 dentro do texto
        # estouraria o contexto e o modelo não a interpretaria como imagem.
        output = ""
        images: list[str] = []
        for item in result.content:
            if item.type == "text":
                output += item.text + "\n"
            elif item.type == "image":
                images.append(item.data)

        if result.isError:
            return {"error": output.strip()}

        payload: dict[str, Any] = {"result": output.strip()}
        if images:
            # `images_b64` e não `images`: a chave precisa dizer o FORMATO, não o
            # assunto. `SystemToolExecutor._web_search` já devolvia `images` com
            # uma lista de URLs de resultado de busca, e o laço do `ChiefAI`, ao
            # passar a aceitar imagem de tool, mandava essas URLs para o provider
            # como se fossem base64 — o Gemini respondia HTTP 400 com
            # "Base64 decoding failed for https://...". Duas coisas diferentes
            # com o mesmo nome viram uma colisão silenciosa; o nome explícito é
            # o que impede a próxima.
            payload["images_b64"] = images
        return payload

    async def close_all(self) -> None:
        for instance in self.servers.values():
            await instance.close()
        self.servers.clear()
        self.tool_routes.clear()

    async def refresh(self) -> None:
        """Encerra todas as conexões e recarrega os servidores MCP."""
        await self.close_all()
        await self.discover_and_connect()
