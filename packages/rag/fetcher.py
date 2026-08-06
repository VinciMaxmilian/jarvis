"""Download seguro de páginas web e extração de texto para o nível `knowledge`.

Este módulo é o **único** ponto do repo que baixa conteúdo de terceiro para virar
conhecimento. A URL não vem do dono: vem de um resultado de busca, ou seja, de
quem escreveu a página. Por isso nada aqui é "validação defensiva opcional" — é o
perímetro. As guardas, na ordem em que rodam:

1. **Esquema** — só `http`/`https`. `file://` transformaria "pesquisar" em
   "ler o disco da máquina"; `ftp://`, `gopher://` e afins não têm cliente aqui.
2. **SSRF** — o hostname é resolvido *antes* de conectar e o IP é recusado se for
   privado, loopback, link-local, reservado, multicast ou não especificado.
   `169.254.169.254` é o caso que motiva a lista: é o endpoint de metadados de
   nuvem, e uma página maliciosa que consiga o Jarvis a buscá-lo recebe de volta
   credencial de instância dentro do índice de conhecimento.
3. **Redirect** — `follow_redirects=True` do httpx **pula** a checagem acima no
   destino: a validação aconteceu na URL de origem, e o 302 leva para onde
   quiser. Aqui os redirects são seguidos **à mão** (`follow_redirects=False` no
   cliente), e cada salto repete esquema + deny-list + resolução de IP + robots.
   Resta uma janela de DNS rebinding entre a resolução e o `connect` do httpx
   (o nome é resolvido duas vezes); fechá-la exigiria conectar no IP validado com
   `Host:` reescrito, o que quebra SNI/TLS e não vale o preço para este uso.
   O que essa janela permite é uma requisição, sem credencial, cuja resposta
   ainda passa por content-type e teto de bytes.
4. **robots.txt** — respeitado por domínio, com cache. Falha ao buscar o arquivo
   é **fail-open** (o comportamento que a norma descreve), mas com log: negar
   tudo quando o robots.txt está fora do ar transformaria uma indisponibilidade
   de terceiro em "o Jarvis parou de aprender", sem ninguém entender por quê.
5. **Content-Type** em allow-list. Imagem, vídeo e binário não viram texto; o que
   vira é lixo vetorizado que compete com conteúdo real na busca.
6. **Teto de bytes** com abort no meio do stream. Baixar 500 MB para descartar
   depois já pagou a banda e a memória.
7. **Timeout** em tudo, inclusive no robots.txt.

Erro **nunca** sobe para quem chama: `fetch_url` devolve `None` e loga o motivo.
O chamador é um laço sobre 20 URLs de qualidade desconhecida, e uma que falha não
pode derrubar as outras dezenove.

A extração de HTML daqui é a versão canônica — `capabilities/browser` importa
deste módulo em vez de manter a sua própria cópia.
"""

from __future__ import annotations

import asyncio
import io
import ipaddress
import socket
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
import structlog
from bs4 import BeautifulSoup
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = structlog.get_logger(__name__)

#: Mesmo valor de `packages.scheduler.reindex.DEFAULT_MAX_BYTES` — de propósito:
#: o que o fetcher aceita baixar tem que caber no que o reindex aceita indexar,
#: senão o documento entra em disco e o job noturno o pula **em silêncio**.
#: Duplicado, e não importado, para não arrastar `packages.scheduler` (e o
#: apscheduler) para dentro do subprocesso de uma capability. A igualdade é
#: verificada em `tests/unit/test_rag_fetcher.py`.
DEFAULT_MAX_BYTES = 2 * 1024 * 1024

#: Teto de saltos de redirect. Cada salto custa uma resolução de DNS e uma
#: requisição; cadeia maior que isto é quase sempre laço ou rastreador.
MAX_REDIRECTS = 5

#: Nomes que resolvem para a própria máquina sem passar por DNS. Bloquear só por
#: IP não basta: `localhost` pode estar no hosts apontando para qualquer coisa,
#: e o nome é o que aparece numa URL colhida de página.
HOSTS_LOCAIS = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})

#: Tags cujo texto é cromo de navegação, não conteúdo. Vetorizar menu e rodapé
#: enche o índice de chunks que se parecem com todas as perguntas e respondem a
#: nenhuma.
TAGS_RUIDO = ("script", "style", "nav", "header", "footer", "aside", "form", "noscript")


class FetcherConfig(BaseSettings):
    """Parâmetros do download. Nada de número mágico no corpo das funções.

    `BaseSettings` (e não dataclass) porque o teto de bytes, a concorrência e a
    deny-list são exatamente o que se quer poder apertar em produção sem deploy —
    prefixo `JARVIS_FETCHER_`. Sem `env_file`: este é um objeto que testes
    constroem dezenas de vezes com valores explícitos, e ler o `.env` a cada
    construção faria o resultado do teste depender da máquina.
    """

    model_config = SettingsConfigDict(env_prefix="jarvis_fetcher_", extra="ignore")

    timeout: float = 15.0
    max_bytes: int = DEFAULT_MAX_BYTES
    #: User-Agent identificável: quem administra o site precisa saber quem bateu
    #: na porta para poder nos barrar no robots.txt se quiser.
    user_agent: str = "JarvisBot/0.1 (+knowledge ingestion)"
    content_types: tuple[str, ...] = ("text/html", "text/plain", "application/pdf")
    dominios_bloqueados: tuple[str, ...] = ()
    respeitar_robots: bool = True
    #: 4 downloads simultâneos: o gargalo é a cortesia com o site de origem, não
    #: a CPU. Mais que isso, sobre poucos domínios, é o que faz um WAF nos tratar
    #: como ataque.
    concorrencia: int = 4


@dataclass(frozen=True, slots=True)
class FetchedDoc:
    """Uma página baixada e reduzida a texto.

    `url` é a **final**, depois dos redirects: é ela que vai para o frontmatter
    como `source_url`, e citar a URL de entrada de uma cadeia de encurtador é
    citar uma fonte que não existe mais amanhã.
    """

    url: str
    titulo: str
    texto: str
    content_type: str
    bytes_baixados: int


#: Cache de robots.txt por origem (`esquema://host:porta`). `None` significa
#: "não deu para ler" e vale como permitido — o cache guarda a falha também,
#: senão cada URL do mesmo domínio tenta de novo o arquivo que não existe.
_CACHE_ROBOTS: dict[str, RobotFileParser | None] = {}


def limpar_cache_robots() -> None:
    """Esvazia o cache de robots.txt. Existe para teste e para reload manual."""
    _CACHE_ROBOTS.clear()


# --------------------------------------------------------------------------- #
# Extração — versão canônica, compartilhada com a capability `browser`
# --------------------------------------------------------------------------- #


def extrair_de_html(html: str) -> tuple[str, str]:
    """HTML → `(titulo, texto)`.

    O título é lido **antes** da poda: o `<h1>` de fallback costuma morar dentro
    do `<header>`, que é justamente uma das tags que a poda remove.
    """
    soup = BeautifulSoup(html, "html.parser")

    titulo = ""
    if soup.title is not None and soup.title.string:
        titulo = soup.title.string.strip()
    if not titulo:
        h1 = soup.find("h1")
        if h1 is not None:
            titulo = h1.get_text(" ", strip=True)

    for tag in soup(list(TAGS_RUIDO)):
        tag.decompose()

    texto = soup.get_text(separator="\n")
    linhas = [linha.strip() for linha in texto.splitlines() if linha.strip()]
    return titulo, "\n".join(linhas)


def _extrair_de_pdf(dados: bytes) -> tuple[str, str] | None:
    """PDF → `(titulo, texto)`, ou `None` se não der para ler.

    O `pypdf` chega via Agno e não é declarado direto; se um dia deixar de vir,
    o caminho de PDF some sozinho em vez de derrubar todo o fetcher no import.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.warning("rag.fetcher.pypdf_ausente")
        return None

    try:
        leitor = PdfReader(io.BytesIO(dados))
        metadados = leitor.metadata
        titulo = (metadados.title or "") if metadados is not None else ""
        paginas = [pagina.extract_text() or "" for pagina in leitor.pages]
    except Exception as exc:  # pypdf levanta uma família larga em PDF corrompido
        logger.warning("rag.fetcher.pdf_ilegivel", erro=str(exc))
        return None

    texto = "\n".join(paginas)
    linhas = [linha.strip() for linha in texto.splitlines() if linha.strip()]
    return titulo.strip(), "\n".join(linhas)


# --------------------------------------------------------------------------- #
# Guardas de destino
# --------------------------------------------------------------------------- #


def _ip_proibido(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Verdadeiro para qualquer endereço que não seja internet pública.

    IPv6 mapeado (`::ffff:127.0.0.1`) é desembrulhado antes de julgar: as
    propriedades `is_*` do objeto IPv6 não enxergam o IPv4 embutido, e essa é a
    forma padrão de escrever loopback quando se quer passar por um filtro.
    """
    mapeado = getattr(ip, "ipv4_mapped", None)
    if mapeado is not None:
        ip = mapeado
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def _resolver(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve o host em thread — `getaddrinfo` é bloqueante e trava o loop.

    Devolve **todos** os endereços: um nome pode resolver para um IP público e um
    privado ao mesmo tempo, e basta um proibido para a URL inteira ser recusada.
    """
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass

    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo, host, None, 0, socket.SOCK_STREAM
        )
    except OSError as exc:
        logger.warning("rag.fetcher.dns_falhou", host=host, erro=str(exc))
        return []

    enderecos: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        sockaddr = info[4]
        try:
            enderecos.append(ipaddress.ip_address(sockaddr[0]))
        except ValueError:  # pragma: no cover — getaddrinfo não devolve outra coisa
            continue
    return enderecos


async def _motivo_para_recusar(url: str, config: FetcherConfig) -> str | None:
    """`None` se a URL pode ser buscada; caso contrário, o motivo já formatado."""
    partes = urlparse(url)

    if partes.scheme not in ("http", "https"):
        return f"esquema não suportado: {partes.scheme or 'ausente'!r}"

    host = (partes.hostname or "").lower()
    if not host:
        return "url sem host"

    if host in HOSTS_LOCAIS or host.endswith(".localhost"):
        return f"host local: {host}"

    for bloqueado in config.dominios_bloqueados:
        alvo = bloqueado.strip().lower().lstrip(".")
        if alvo and (host == alvo or host.endswith("." + alvo)):
            return f"domínio na deny-list: {host}"

    enderecos = await _resolver(host)
    if not enderecos:
        return f"host não resolveu: {host}"
    for ip in enderecos:
        if _ip_proibido(ip):
            return f"ip fora da internet pública: {host} → {ip}"

    return None


async def _robots_permite(url: str, config: FetcherConfig, cliente: httpx.AsyncClient) -> bool:
    partes = urlparse(url)
    origem = f"{partes.scheme}://{partes.netloc}"

    if origem not in _CACHE_ROBOTS:
        _CACHE_ROBOTS[origem] = await _carregar_robots(origem, config, cliente)

    parser = _CACHE_ROBOTS[origem]
    if parser is None:
        return True
    return parser.can_fetch(config.user_agent, url)


async def _carregar_robots(
    origem: str, config: FetcherConfig, cliente: httpx.AsyncClient
) -> RobotFileParser | None:
    """Busca e parseia o robots.txt da origem. `None` = não deu, siga em frente."""
    alvo = f"{origem}/robots.txt"
    try:
        resposta = await cliente.get(alvo, timeout=config.timeout)
    except Exception as exc:
        logger.info("rag.fetcher.robots_indisponivel", origem=origem, erro=str(exc))
        return None

    if resposta.status_code >= 400:
        logger.info(
            "rag.fetcher.robots_ausente", origem=origem, status=resposta.status_code
        )
        return None

    parser = RobotFileParser()
    try:
        parser.parse(resposta.text.splitlines())
    except Exception as exc:  # pragma: no cover — robotparser é tolerante a lixo
        logger.info("rag.fetcher.robots_ilegivel", origem=origem, erro=str(exc))
        return None
    return parser


# --------------------------------------------------------------------------- #
# Download
# --------------------------------------------------------------------------- #


def _abrir_cliente(config: FetcherConfig) -> httpx.AsyncClient:
    """Cliente com redirect **desligado** — quem segue redirect aqui somos nós."""
    return httpx.AsyncClient(
        timeout=httpx.Timeout(config.timeout),
        follow_redirects=False,
        headers={"User-Agent": config.user_agent},
    )


async def _ler_corpo(
    resposta: httpx.Response, url_final: str, config: FetcherConfig
) -> FetchedDoc | None:
    bruto = resposta.headers.get("content-type", "")
    content_type = bruto.split(";")[0].strip().lower()
    if content_type not in config.content_types:
        logger.warning(
            "rag.fetcher.content_type_recusado", url=url_final, content_type=bruto
        )
        return None

    declarado = resposta.headers.get("content-length")
    if declarado is not None and declarado.isdigit() and int(declarado) > config.max_bytes:
        logger.warning(
            "rag.fetcher.acima_do_teto",
            url=url_final,
            content_length=int(declarado),
            max_bytes=config.max_bytes,
        )
        return None

    corpo = bytearray()
    try:
        async for pedaco in resposta.aiter_bytes():
            corpo.extend(pedaco)
            # Aborta no meio: o `Content-Length` acima é uma dica do servidor, e
            # resposta chunked não traz nenhuma. Este é o teto que vale.
            if len(corpo) > config.max_bytes:
                logger.warning(
                    "rag.fetcher.acima_do_teto",
                    url=url_final,
                    baixado=len(corpo),
                    max_bytes=config.max_bytes,
                )
                return None
    except Exception as exc:
        logger.warning("rag.fetcher.leitura_falhou", url=url_final, erro=str(exc))
        return None

    dados = bytes(corpo)

    if content_type == "application/pdf":
        extraido = _extrair_de_pdf(dados)
        if extraido is None:
            return None
        titulo, texto = extraido
    else:
        codificacao = resposta.charset_encoding or "utf-8"
        try:
            conteudo = dados.decode(codificacao, errors="replace")
        except LookupError:  # charset inventado pelo servidor
            conteudo = dados.decode("utf-8", errors="replace")

        if content_type == "text/html":
            titulo, texto = extrair_de_html(conteudo)
        else:
            linhas = [ln.strip() for ln in conteudo.splitlines() if ln.strip()]
            texto = "\n".join(linhas)
            titulo = linhas[0][:120] if linhas else ""

    if not titulo:
        titulo = url_final

    return FetchedDoc(
        url=url_final,
        titulo=titulo,
        texto=texto,
        content_type=content_type,
        bytes_baixados=len(dados),
    )


async def _buscar(
    url: str, config: FetcherConfig, cliente: httpx.AsyncClient
) -> FetchedDoc | None:
    alvo = url

    for _ in range(MAX_REDIRECTS + 1):
        motivo = await _motivo_para_recusar(alvo, config)
        if motivo is not None:
            logger.warning("rag.fetcher.recusado", url=alvo, motivo=motivo)
            return None

        if config.respeitar_robots and not await _robots_permite(alvo, config, cliente):
            logger.warning("rag.fetcher.robots_proibiu", url=alvo)
            return None

        requisicao = cliente.build_request("GET", alvo)
        try:
            resposta = await cliente.send(requisicao, stream=True)
        except Exception as exc:
            logger.warning("rag.fetcher.requisicao_falhou", url=alvo, erro=str(exc))
            return None

        try:
            if resposta.status_code in (301, 302, 303, 307, 308):
                destino = resposta.headers.get("location")
                if not destino:
                    logger.warning("rag.fetcher.redirect_sem_destino", url=alvo)
                    return None
                # Novo salto: o `continue` reentra no laço e refaz TODAS as
                # guardas sobre a URL de destino. É esta linha que o
                # `follow_redirects=True` do httpx nos custaria.
                alvo = str(httpx.URL(alvo).join(destino))
                continue

            if resposta.status_code >= 400:
                logger.warning(
                    "rag.fetcher.status_ruim", url=alvo, status=resposta.status_code
                )
                return None

            return await _ler_corpo(resposta, alvo, config)
        finally:
            await resposta.aclose()

    logger.warning("rag.fetcher.redirects_demais", url=url, maximo=MAX_REDIRECTS)
    return None


async def fetch_url(
    url: str,
    *,
    config: FetcherConfig | None = None,
    cliente: httpx.AsyncClient | None = None,
) -> FetchedDoc | None:
    """Baixa uma URL e devolve o texto, ou `None` se qualquer guarda barrar.

    `cliente` existe para o chamador reaproveitar conexões (e para o teste
    injetar um `MockTransport`); omitido, um cliente descartável é aberto e
    fechado aqui mesmo.
    """
    cfg = config or FetcherConfig()
    if cliente is not None:
        return await _buscar(url, cfg, cliente)
    async with _abrir_cliente(cfg) as proprio:
        return await _buscar(url, cfg, proprio)


async def fetch_many(
    urls: Sequence[str],
    *,
    config: FetcherConfig | None = None,
    cliente: httpx.AsyncClient | None = None,
) -> list[FetchedDoc]:
    """Baixa várias URLs em paralelo limitado e devolve **só o que deu certo**.

    A lista de saída é menor que a de entrada sempre que algo falhou, e essa é a
    forma: o chamador quer documentos, não um relatório de erro por URL — o
    relatório está no log, com o motivo de cada recusa.
    """
    cfg = config or FetcherConfig()
    semaforo = asyncio.Semaphore(cfg.concorrencia)

    async def _um(alvo: str, usando: httpx.AsyncClient) -> FetchedDoc | None:
        async with semaforo:
            try:
                return await _buscar(alvo, cfg, usando)
            except Exception as exc:  # rede é criativa; o laço não pode parar
                logger.warning("rag.fetcher.erro_inesperado", url=alvo, erro=str(exc))
                return None

    if cliente is not None:
        resultados = await asyncio.gather(*(_um(u, cliente) for u in urls))
    else:
        async with _abrir_cliente(cfg) as proprio:
            resultados = await asyncio.gather(*(_um(u, proprio) for u in urls))

    return [doc for doc in resultados if doc is not None]


__all__ = [
    "DEFAULT_MAX_BYTES",
    "MAX_REDIRECTS",
    "FetchedDoc",
    "FetcherConfig",
    "extrair_de_html",
    "fetch_many",
    "fetch_url",
    "limpar_cache_robots",
]
