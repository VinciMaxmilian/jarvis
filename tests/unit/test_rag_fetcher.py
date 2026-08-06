"""Aceite das guardas de `packages/rag/fetcher.py`.

Nenhum teste aqui toca a rede: o transporte do httpx é um `MockTransport` e o
`socket.getaddrinfo` é substituído por uma tabela. Isso não é só higiene de
suíte — é o que torna os testes de SSRF *possíveis*: para afirmar que uma URL
foi recusada é preciso poder dizer qual IP o nome resolveria, e num teste com
DNS real `exemplo.com` resolve para o que a internet quiser hoje.

A pergunta que cada teste responde é sempre a mesma: **a requisição chegou a
sair?** Por isso o handler do transporte registra os caminhos pedidos, e a
asserção forte quase nunca é `resultado is None` — é `pedidos == []`.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Callable

import httpx
import pytest

from packages.rag.fetcher import (
    DEFAULT_MAX_BYTES,
    FetchedDoc,
    FetcherConfig,
    extrair_de_html,
    fetch_many,
    fetch_url,
    limpar_cache_robots,
)

#: Um IP público de verdade (documentação da IANA), para o caminho feliz: o
#: fetcher precisa deixar passar alguma coisa, senão "bloqueia tudo" também
#: passaria em todos os testes de bloqueio.
IP_PUBLICO = "93.184.216.34"

CONFIG_BASE = {"respeitar_robots": False, "timeout": 5.0}


@pytest.fixture(autouse=True)
def _robots_limpo() -> None:
    """O cache de robots.txt é global; teste que herda o de outro mente."""
    limpar_cache_robots()
    yield
    limpar_cache_robots()


@pytest.fixture
def dns(monkeypatch: pytest.MonkeyPatch) -> Callable[[dict[str, str]], None]:
    """Instala uma tabela `host → ip` no lugar do resolvedor do sistema."""

    def instalar(mapa: dict[str, str]) -> None:
        def getaddrinfo(host: str, port: object, *args: object, **kwargs: object):
            ip = mapa.get(host)
            if ip is None:
                raise socket.gaierror(f"host fora da tabela do teste: {host}")
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

        monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)

    return instalar


def cliente_de(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    """Cliente com o mesmo formato do de produção, mas sem sair da máquina.

    `follow_redirects=False` é repetido aqui de propósito: é a premissa de que o
    fetcher depende para revalidar cada salto, e um teste que a ligasse estaria
    exercitando outro código.
    """
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
        headers={"User-Agent": "JarvisBot/0.1 (+knowledge ingestion)"},
    )


def html_de(corpo: str) -> httpx.Response:
    return httpx.Response(
        200, headers={"content-type": "text/html; charset=utf-8"}, content=corpo.encode()
    )


# --------------------------------------------------------------------------- #
# SSRF
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/segredo",
        "http://10.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data/",  # metadados de nuvem
        "http://localhost:8000/interno",
        "http://[::1]/interno",
        "http://[::ffff:127.0.0.1]/disfarcado",
    ],
)
async def test_fetcher_bloqueia_ip_privado(url: str) -> None:
    pedidos: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        pedidos.append(str(request.url))
        return html_de("<html><body>não deveria ter chegado aqui</body></html>")

    async with cliente_de(handler) as cliente:
        doc = await fetch_url(url, config=FetcherConfig(**CONFIG_BASE), cliente=cliente)

    assert doc is None
    # A guarda vale antes de conectar: nenhum pacote sai, nem para descobrir.
    assert pedidos == []


async def test_fetcher_bloqueia_redirect_para_ip_privado(
    dns: Callable[[dict[str, str]], None],
) -> None:
    """O 302 é o furo clássico: a URL validada não é a URL buscada."""
    dns({"exemplo.com": IP_PUBLICO})
    pedidos: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        pedidos.append(str(request.url))
        if request.url.host == "exemplo.com":
            return httpx.Response(
                302, headers={"location": "http://169.254.169.254/latest/meta-data/"}
            )
        return httpx.Response(  # pragma: no cover — é o que o teste prova não ocorrer
            200, headers={"content-type": "text/plain"}, content=b"token=secreto"
        )

    async with cliente_de(handler) as cliente:
        doc = await fetch_url(
            "http://exemplo.com/artigo",
            config=FetcherConfig(**CONFIG_BASE),
            cliente=cliente,
        )

    assert doc is None
    assert pedidos == ["http://exemplo.com/artigo"]


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "file://C:/Windows/win.ini", "ftp://exemplo.com/arquivo"],
)
async def test_fetcher_recusa_esquema_nao_http(url: str) -> None:
    pedidos: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        pedidos.append(str(request.url))
        return html_de("<html></html>")

    async with cliente_de(handler) as cliente:
        doc = await fetch_url(url, config=FetcherConfig(**CONFIG_BASE), cliente=cliente)

    assert doc is None
    assert pedidos == []


# --------------------------------------------------------------------------- #
# robots.txt
# --------------------------------------------------------------------------- #


async def test_fetcher_respeita_robots(dns: Callable[[dict[str, str]], None]) -> None:
    dns({"exemplo.com": IP_PUBLICO})
    pedidos: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        pedidos.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                content=b"User-agent: *\nDisallow: /privado\n",
            )
        return html_de("<html><title>Aberto</title><body>livre</body></html>")

    config = FetcherConfig(respeitar_robots=True, timeout=5.0)
    async with cliente_de(handler) as cliente:
        proibido = await fetch_url(
            "http://exemplo.com/privado/pagina", config=config, cliente=cliente
        )
        permitido = await fetch_url(
            "http://exemplo.com/publico/pagina", config=config, cliente=cliente
        )

    assert proibido is None
    assert permitido is not None and permitido.titulo == "Aberto"
    # O robots.txt foi buscado **uma** vez para as duas URLs: o cache é por
    # domínio, e sem ele cada download dobraria de custo.
    assert pedidos.count("/robots.txt") == 1
    assert "/privado/pagina" not in pedidos


# --------------------------------------------------------------------------- #
# Content-Type e teto de bytes
# --------------------------------------------------------------------------- #


async def test_fetcher_recusa_content_type(dns: Callable[[dict[str, str]], None]) -> None:
    dns({"exemplo.com": IP_PUBLICO})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "image/png"}, content=b"\x89PNG\r\n\x1a\n"
        )

    async with cliente_de(handler) as cliente:
        doc = await fetch_url(
            "http://exemplo.com/grafico.png",
            config=FetcherConfig(**CONFIG_BASE),
            cliente=cliente,
        )

    assert doc is None


async def test_fetcher_aborta_acima_do_teto(
    dns: Callable[[dict[str, str]], None],
) -> None:
    """Sem `Content-Length` o teto só existe se for verificado durante o stream."""
    dns({"exemplo.com": IP_PUBLICO})
    enviados: list[int] = []

    async def corpo():
        for _ in range(50):
            enviados.append(1)
            yield b"a" * 1024

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/plain"}, content=corpo()
        )

    config = FetcherConfig(max_bytes=4096, respeitar_robots=False, timeout=5.0)
    async with cliente_de(handler) as cliente:
        doc = await fetch_url(
            "http://exemplo.com/dump.txt", config=config, cliente=cliente
        )

    assert doc is None
    # Cortou perto do teto em vez de engolir os 50 KB e descartar no fim.
    assert len(enviados) <= 6, f"leu {len(enviados)} KB antes de desistir"


def test_teto_do_fetcher_bate_com_o_do_reindex() -> None:
    """Se o fetcher aceitar mais do que o reindex indexa, o arquivo escrito em
    disco é pulado **em silêncio** pelo job noturno — o pior tipo de perda."""
    from packages.scheduler.reindex import DEFAULT_MAX_BYTES as TETO_REINDEX

    assert DEFAULT_MAX_BYTES == TETO_REINDEX


# --------------------------------------------------------------------------- #
# Extração
# --------------------------------------------------------------------------- #

PAGINA = """
<html>
  <head><title>  O que é um algoritmo  </title><style>body{color:red}</style></head>
  <body>
    <nav><a href="/">Início</a><a href="/sobre">Sobre</a></nav>
    <header><h1>Cabeçalho decorativo</h1></header>
    <main>
      <h2>Definição</h2>
      <p>Algoritmo é uma sequência finita de passos.</p>

      <p>Todo algoritmo termina.</p>
    </main>
    <aside>Leia também: dez dicas</aside>
    <form><input name="busca"></form>
    <footer>Copyright 2026</footer>
    <script>rastrear()</script>
    <noscript>Ative o JavaScript</noscript>
  </body>
</html>
"""


async def test_fetcher_extrai_titulo_e_limpa_nav(
    dns: Callable[[dict[str, str]], None],
) -> None:
    dns({"exemplo.com": IP_PUBLICO})

    def handler(request: httpx.Request) -> httpx.Response:
        return html_de(PAGINA)

    async with cliente_de(handler) as cliente:
        doc = await fetch_url(
            "http://exemplo.com/algoritmos",
            config=FetcherConfig(**CONFIG_BASE),
            cliente=cliente,
        )

    assert isinstance(doc, FetchedDoc)
    assert doc.titulo == "O que é um algoritmo"
    assert doc.content_type == "text/html"
    assert doc.bytes_baixados > 0

    assert "Algoritmo é uma sequência finita de passos." in doc.texto
    for ruido in ("Início", "Sobre", "Copyright 2026", "rastrear()", "Leia também"):
        assert ruido not in doc.texto, f"{ruido!r} sobreviveu à poda"
    # Linhas vazias colapsadas: chunk que é metade quebra de linha desperdiça
    # janela de embedding.
    assert "\n\n" not in doc.texto


def test_extrair_de_html_usa_h1_quando_nao_ha_title() -> None:
    """O `<h1>` é lido antes da poda — ele quase sempre mora dentro do `<header>`."""
    titulo, texto = extrair_de_html(
        "<html><body><header><h1>Título no header</h1></header>"
        "<p>corpo</p></body></html>"
    )
    assert titulo == "Título no header"
    assert texto == "corpo"


# --------------------------------------------------------------------------- #
# Erros e concorrência
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("modo", ["conexao", "timeout", "404", "500"])
async def test_fetcher_erro_devolve_none_nao_levanta(
    dns: Callable[[dict[str, str]], None], modo: str
) -> None:
    """Quem chama está num laço sobre 20 URLs; uma exceção derrubaria as outras."""
    dns({"exemplo.com": IP_PUBLICO})

    def handler(request: httpx.Request) -> httpx.Response:
        if modo == "conexao":
            raise httpx.ConnectError("conexão recusada", request=request)
        if modo == "timeout":
            raise httpx.ReadTimeout("demorou demais", request=request)
        return httpx.Response(int(modo))

    async with cliente_de(handler) as cliente:
        doc = await fetch_url(
            "http://exemplo.com/pagina",
            config=FetcherConfig(**CONFIG_BASE),
            cliente=cliente,
        )

    assert doc is None


async def test_fetch_many_respeita_concorrencia(
    dns: Callable[[dict[str, str]], None],
) -> None:
    dns({"exemplo.com": IP_PUBLICO})
    em_voo = 0
    pico = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal em_voo, pico
        em_voo += 1
        pico = max(pico, em_voo)
        try:
            await asyncio.sleep(0.01)
            return html_de(f"<title>p</title><body>{request.url.path}</body>")
        finally:
            em_voo -= 1

    urls = [f"http://exemplo.com/artigo-{i}" for i in range(8)]
    config = FetcherConfig(concorrencia=2, respeitar_robots=False, timeout=5.0)
    async with cliente_de(handler) as cliente:
        docs = await fetch_many(urls, config=config, cliente=cliente)

    assert len(docs) == 8
    assert pico <= 2, f"{pico} downloads simultâneos com concorrencia=2"


async def test_fetch_many_devolve_so_os_que_deram_certo(
    dns: Callable[[dict[str, str]], None],
) -> None:
    dns({"exemplo.com": IP_PUBLICO})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/quebrado":
            return httpx.Response(500)
        return html_de("<title>ok</title><body>conteúdo</body>")

    urls = [
        "http://exemplo.com/bom",
        "http://exemplo.com/quebrado",
        "http://127.0.0.1/interno",  # recusado antes de sair
        "ftp://exemplo.com/arquivo",  # esquema recusado
        "http://exemplo.com/outro",
    ]
    async with cliente_de(handler) as cliente:
        docs = await fetch_many(
            urls, config=FetcherConfig(**CONFIG_BASE), cliente=cliente
        )

    assert [d.url for d in docs] == ["http://exemplo.com/bom", "http://exemplo.com/outro"]


# --------------------------------------------------------------------------- #
# Ponte com a capability `browser`
# --------------------------------------------------------------------------- #


def _browser():
    from capabilities.browser.backend.handlers import Browser
    from packages.shared.contracts import CapabilityPermissions

    return Browser(CapabilityPermissions(network=["exemplo.com"]))


def test_capability_browser_usa_o_fetcher(monkeypatch: pytest.MonkeyPatch) -> None:
    """A capability é síncrona e o fetcher é async; a ponte é `asyncio.run`.

    Este teste roda o handler **fora** de qualquer event loop, que é o caminho
    real: a capability vive num subprocesso, um loop por execução.
    """
    from capabilities.browser.backend import handlers
    from capabilities.browser.schemas import ExtrairEntrada

    async def falso(url: str, *, config=None, cliente=None):
        return FetchedDoc(
            url=url,
            titulo="t",
            texto="conteúdo limpo",
            content_type="text/html",
            bytes_baixados=10,
        )

    monkeypatch.setattr(handlers, "fetch_url", falso)

    saida = _browser().browser_extract_text(
        ExtrairEntrada(url="http://exemplo.com/artigo")
    )
    assert saida.url == "http://exemplo.com/artigo"
    assert saida.texto == "conteúdo limpo"


def test_capability_browser_recusa_quando_fetcher_devolve_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from capabilities.browser.backend import handlers
    from capabilities.browser.schemas import ExtrairEntrada
    from packages.capabilities import EntradaInvalida

    async def falso(url: str, *, config=None, cliente=None):
        return None

    monkeypatch.setattr(handlers, "fetch_url", falso)

    with pytest.raises(EntradaInvalida):
        _browser().browser_extract_text(ExtrairEntrada(url="http://exemplo.com/x"))


def test_capability_browser_confere_host_antes_do_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Permissão declarada continua valendo — e agora vale na URL final também."""
    from capabilities.browser.backend import handlers
    from capabilities.browser.schemas import ExtrairEntrada
    from packages.capabilities import PermissaoNaoDeclarada

    chamou = False

    async def falso(url: str, *, config=None, cliente=None):  # pragma: no cover
        nonlocal chamou
        chamou = True
        return None

    monkeypatch.setattr(handlers, "fetch_url", falso)

    with pytest.raises(PermissaoNaoDeclarada):
        _browser().browser_extract_text(ExtrairEntrada(url="http://outro.com/x"))
    assert chamou is False


async def test_capability_browser_funciona_dentro_de_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`asyncio.run` levanta se já houver loop; a ponte cai para uma thread."""
    from capabilities.browser.backend import handlers
    from capabilities.browser.schemas import ExtrairEntrada

    async def falso(url: str, *, config=None, cliente=None):
        return FetchedDoc(
            url=url, titulo="t", texto="ok", content_type="text/html", bytes_baixados=2
        )

    monkeypatch.setattr(handlers, "fetch_url", falso)

    # Chamada síncrona de dentro de um teste async: há loop rodando nesta thread.
    saida = _browser().browser_extract_text(ExtrairEntrada(url="http://exemplo.com/y"))
    assert saida.texto == "ok"
