from __future__ import annotations

import httpx
from bs4 import BeautifulSoup
from pathlib import Path
from typing import NoReturn

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

DIRETORIO = Path(__file__).resolve().parents[1]


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
        self._conferir_host(entrada.url, "browser_extract_text")
        
        try:
            response = httpx.get(
                entrada.url, 
                timeout=entrada.timeout, 
                follow_redirects=True
            )
            response.raise_for_status()
        except Exception as exc:
            self._recusar("browser_extract_text", "url", f"falha ao buscar URL: {exc}")

        html = response.text
        soup = BeautifulSoup(html, "html.parser")

        # Remover scripts e estilos
        for script in soup(["script", "style"]):
            script.extract()
        
        texto = soup.get_text(separator="\n")
        linhas = [linha.strip() for linha in texto.splitlines() if linha.strip()]
        texto_limpo = "\n".join(linhas)

        return ExtrairSaida(url=entrada.url, texto=texto_limpo)


def construir() -> Browser:
    return Browser(permissoes_declaradas(DIRETORIO))


main = entrypoint(construir)

__all__ = ["DIRETORIO", "Browser", "construir", "main"]
