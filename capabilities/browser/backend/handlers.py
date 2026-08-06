from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, NoReturn

from capabilities.browser.schemas import (
    ExtrairEntrada,
    ExtrairSaida,
)
from packages.capabilities import (
    Capability,
    EntradaInvalida,
    PermissaoNaoDeclarada,
    Problema,
    entrypoint,
    permissoes_declaradas,
    tool,
)
from packages.rag.fetcher import FetcherConfig, fetch_url

DIRETORIO = Path(__file__).resolve().parents[1]


def _rodar(corotina: Any) -> Any:
    """Executa uma corotina a partir de código síncrono.

    O despacho do Capability SDK é síncrono por contrato (`packages/capabilities/
    base.py`), e o `fetch_url` é async porque o pipeline de pesquisa baixa dezenas
    de URLs em paralelo — async no módulo compartilhado é o que permite isso, e
    fazer o inverso (fetcher síncrono + thread pool no pipeline) trocaria uma
    ponte pequena aqui por uma ponte grande lá.

    O caminho normal é `asyncio.run`: a capability roda em subprocesso próprio,
    um loop por execução é exatamente o que o SDK descreve. O `ThreadPoolExecutor`
    cobre o caso de alguém chamar o handler de dentro de um loop já rodando
    (harness de teste, importação direta pela API) — aí `asyncio.run` levantaria
    `RuntimeError`, e a corotina precisa de um loop em outra thread.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(corotina)

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, corotina).result()


class Browser(Capability):
    """Extrai texto visível de páginas web."""

    name = "browser"
    version = "0.1.0"
    description = "Busca uma URL e extrai apenas o texto útil, ignorando tags e scripts."
    trigger_intents = (
        "ler o texto de um site",
        "extrair conteúdo de uma página web",
    )
    runtime = "python"

    def _recusar(self, tool_name: str, campo: str, mensagem: str) -> NoReturn:
        raise EntradaInvalida(
            self.name, tool_name, [Problema(campo=campo, mensagem=mensagem)]
        )

    def _conferir_host(self, url: str, tool_name: str) -> None:
        from urllib.parse import urlparse
        host = urlparse(url).hostname
        if host and self.permissions.network:
            hosts = [h.strip().lower() for h in self.permissions.network]
            if host.lower() not in hosts:
                raise PermissaoNaoDeclarada("network", host, self.name, tool_name)

    @tool(
        description="Acessa uma página web e extrai o seu texto visível.",
        entrada=ExtrairEntrada,
        saida=ExtrairSaida,
        idempotent=True,
    )
    def browser_extract_text(self, entrada: ExtrairEntrada) -> ExtrairSaida:
        """Delega tudo a `packages.rag.fetcher` — aqui só resta a permissão.

        A regra de extração (poda de `nav`/`footer`/`script`, título, colapso de
        linhas) morava duplicada neste arquivo. Duas cópias da mesma regra
        divergem na primeira correção que alguém faz num lado só; o fetcher é a
        versão canônica, e é a que traz junto as guardas de SSRF, robots.txt,
        content-type e teto de bytes que esta capability nunca teve.

        `_conferir_host` continua rodando **antes** do fetch, e roda de novo na
        URL final: como o fetcher segue redirects à mão, um 302 para fora da
        `network` declarada é visível daqui — e antes não era.
        """
        self._conferir_host(entrada.url, "browser_extract_text")

        config = FetcherConfig(timeout=entrada.timeout)
        documento = _rodar(fetch_url(entrada.url, config=config))

        if documento is None:
            # O motivo exato (esquema, IP privado, robots, content-type, teto,
            # timeout, 404) já saiu em warning estruturado no log do fetcher; o
            # contrato da tool devolve recusa, não a causa raiz.
            self._recusar(
                "browser_extract_text",
                "url",
                "falha ao buscar URL: recusada pelas guardas do fetcher ou sem conteúdo legível",
            )

        self._conferir_host(documento.url, "browser_extract_text")

        return ExtrairSaida(url=documento.url, texto=documento.texto)


def construir() -> Browser:
    return Browser(permissoes_declaradas(DIRETORIO))


main = entrypoint(construir)

__all__ = ["DIRETORIO", "Browser", "construir", "main"]
