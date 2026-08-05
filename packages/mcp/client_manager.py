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
                sse_transport = await self._exit_stack.enter_async_context(sse_client(self.params))
                read, write = sse_transport
            else:
                # self.params é StdioServerParameters
                from mcp.client.stdio import stdio_client
                stdio_transport = await self._exit_stack.enter_async_context(stdio_client(self.params))
                read, write = stdio_transport

            self.session = await self._exit_stack.enter_async_context(ClientSession(read, write))
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
                        
                    logger.info("mcp.server.registered", server=server_name, tools=len(tools_result.tools))
                except Exception:
                    # Log já foi emitido pelo connect()
                    pass
                    
        # Tentar conectar no nosso MCP Central via SSE rodando no Windows Host
        # Usa host.docker.internal para sair do Docker e acessar o localhost do Windows
        host_server_name = "Jarvis-Windows-Host"
        if host_server_name not in self.servers:
            sse_url = os.environ.get("WINDOWS_MCP_URL", "http://host.docker.internal:8765/sse")
            instance = MCPServerInstance(host_server_name, sse_url)
            try:
                await instance.connect()
                self.servers[host_server_name] = instance
                
                assert instance.session is not None
                tools_result = await instance.session.list_tools()
                for tool in tools_result.tools:
                    self.tool_routes[tool.name] = host_server_name
                    
                logger.info("mcp.server.registered", server=host_server_name, tools=len(tools_result.tools))
            except Exception as exc:
                # O servidor pode não estar rodando no Windows. Não derruba nada,
                # mas TAMBÉM não some: quando o dono pedir "clica ali" e o Jarvis
                # responder que não tem como, a causa é esta linha. Silêncio total
                # aqui transformava "esqueci de subir o host" em "o agente é burro".
                logger.warning(
                    "mcp.host.indisponivel",
                    server=host_server_name,
                    url=sse_url,
                    error=str(exc),
                    dica="suba o MCP do host: scripts/run_desktop_host.ps1",
                )

    async def get_tools_specs(self) -> list[dict[str, Any]]:
        """Devolve as especificações das ferramentas prontas para o LLM.

        NOTA DE CUSTO: isto interroga TODOS os servidores por `list_tools()`, em
        série, e é chamado a cada mensagem (`ChiefAI.respond` monta o catálogo
        antes de cada chamada ao modelo). Um servidor stdio lento entra
        integralmente no tempo de resposta, e num canal de voz esse tempo é
        silêncio. O log por servidor abaixo existe para que "está demorando" seja
        atribuível a um nome, em vez de virar um buraco anônimo na linha do tempo.
        """
        # Usa um dicionário para evitar duplicatas pelo nome da ferramenta
        specs_by_name = {}
        for server_name, instance in self.servers.items():
            if not instance.session:
                continue
            try:
                _t0 = time.perf_counter()
                tools_result = await instance.session.list_tools()
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
                logger.error("mcp.list_tools.failed", server=server_name, error=str(exc))
        return list(specs_by_name.values())

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoca uma ferramenta roteando para o servidor MCP correto."""
        server_name = self.tool_routes.get(name)
        if not server_name:
            raise KeyError(f"Ferramenta '{name}' não encontrada nos servidores MCP.")
            
        instance = self.servers.get(server_name)
        if not instance or not instance.session:
            raise RuntimeError(f"Servidor MCP '{server_name}' desconectado.")
            
        result = await instance.session.call_tool(name, arguments=arguments)

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
            payload["images"] = images
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
