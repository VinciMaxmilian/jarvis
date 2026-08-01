"""Verificação, na origem, da asserção assinada pelo Cloudflare Access.

O Access autentica o dono na borda e repassa a identidade num JWT RS256 no
header `Cf-Access-Jwt-Assertion` (a Cloudflare também põe o mesmo token no cookie
`CF_Authorization`, mas a própria documentação avisa que o cookie "is not
guaranteed to be passed" — por isso o header é a fonte primária e o cookie é
apenas o fallback).

**Por que a origem repete um trabalho que a borda já fez.** Porque a borda só
cobre o caminho que passa pela borda. O Tunnel termina neste container; qualquer
outra rota até ele — um segundo túnel, um hostname sem policy, uma ingress rule
que sobrou de um teste — chega sem Access e, sem esta verificação, é atendida.
Origem que confia em header não verificado está autenticando por convenção.

Procedimento conferido na documentação corrente da Cloudflare
("Validate JWTs", cloudflare-one/.../authorization-cookie/validating-json):

  - header  `Cf-Access-Jwt-Assertion`, cookie `CF_Authorization`;
  - JWKS    `https://<equipe>.cloudflareaccess.com/cdn-cgi/access/certs`;
  - `iss`   `https://<equipe>.cloudflareaccess.com`;
  - `aud`   a tag Application Audience da aplicação (string);
  - `alg`   RS256;
  - rotação a cada ~6 semanas; o endpoint devolve a chave atual E a anterior, e a
    anterior segue válida por 7 dias. O casamento é por `kid`.
"""

from __future__ import annotations

import asyncio
import json
import time
from http.cookies import CookieError, SimpleCookie
from typing import Any, Final

import httpx
import jwt
import structlog
from fastapi import FastAPI
from jwt.algorithms import RSAAlgorithm
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from packages.shared.settings import Settings, get_settings

logger = structlog.get_logger("jarvis.cf_access")

#: Nomes exatos definidos pela Cloudflare. Não são configuráveis de propósito:
#: se mudarem, é uma mudança de contrato dela e tem de aparecer num diff daqui.
ACCESS_HEADER: Final = "cf-access-jwt-assertion"
ACCESS_COOKIE: Final = "CF_Authorization"

#: Rotas servidas sem token. Só `/health`: o HEALTHCHECK do Dockerfile bate nela
#: de dentro do próprio container (`urlopen('http://127.0.0.1:8000/health')`) e
#: não tem nem como obter um JWT. Ela devolve `{"status": "ok"}` e nada mais —
#: não vaza estado. Tudo o mais (inclusive `/docs`, `/openapi.json` e
#: `/brain.html`, que expõe o grafo do código) fica atrás do gate.
PUBLIC_PATHS: Final[frozenset[str]] = frozenset({"/health"})

#: Mensagem única devolvida ao cliente. O motivo real vai para o log: distinguir
#: "assinatura inválida" de "e-mail errado" na resposta transforma o endpoint num
#: oráculo para quem está sondando, e o dono lê o `docker logs` de qualquer jeito.
_DENY_DETAIL: Final = "Cloudflare Access: asserção ausente ou inválida"

#: Fechamento de WebSocket por violação de política (RFC 6455).
_WS_POLICY_VIOLATION: Final = 1008


class AccessTokenError(Exception):
    """Motivo técnico da recusa. Vai para o log, nunca para a resposta."""


def _http_transport() -> httpx.AsyncBaseTransport | None:
    """Transporte do cliente que busca o JWKS. `None` = pilha real do httpx.

    É função de módulo, e não parâmetro de `create_app`, porque o teste precisa
    exercitar o app REAL sem tocar a rede: ele troca isto por um
    `httpx.MockTransport`. A alternativa seria arrastar um argumento de teste por
    toda a assinatura de produção para servir só a suíte.
    """
    return None


class JwksCache:
    """Chaves públicas do Access, em memória, indexadas por `kid`.

    Duas pressões opostas moldam esta classe:

    1. buscar o JWKS a cada requisição põe a Cloudflare no caminho crítico de
       todo request e some com a app se o endpoint dela oscilar;
    2. nunca rebuscar quebra na rotação de chave — e a rotação é automática, sem
       aviso, a cada ~6 semanas.

    A saída é cache com TTL para o caso rotineiro **mais** uma busca extra
    disparada por `kid` desconhecido, que é o sintoma exato de rotação. Essa
    busca extra é o que precisa de cuidado: um `kid` aleatório num token forjado
    também é "desconhecido", e sem freio cada requisição forjada viraria um GET
    nosso para a Cloudflare — o atacante escolheria o nosso tráfego de saída. Daí
    o par `_lock` (concorrentes esperam UMA busca, não N) + `_cooldown`
    (sequenciais não passam de uma busca por janela).
    """

    def __init__(
        self,
        certs_url: str,
        *,
        ttl_seconds: float = 3600.0,
        refetch_cooldown_seconds: float = 60.0,
        http_timeout: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._certs_url = certs_url
        self._ttl = float(ttl_seconds)
        self._cooldown = float(refetch_cooldown_seconds)
        self._http_timeout = http_timeout
        self._transport = transport
        self._keys: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        #: `monotonic`, não `time()`: relógio de parede ajustado para trás (NTP,
        #: suspend do notebook) deixaria o cache "no futuro" e eterno.
        #:
        #: `None` — e não `0.0` — para "nunca aconteceu". A origem do `monotonic`
        #: é arbitrária (no Linux, o boot da máquina), então `0.0` NÃO é um
        #: instante distante: num container recém-subido `now - 0.0` vale a
        #: uptime, e enquanto ela for menor que o cooldown o sentinela se disfarça
        #: de "tentei agora há pouco" e engole a primeira rebusca. Sentinela e
        #: medida não podem morar na mesma escala.
        self._fetched_at: float | None = None
        self._last_attempt: float | None = None
        #: Contador de buscas efetivas. O teste do "sem tempestade de requisições"
        #: precisa de um número para afirmar, não de um log para ler.
        self.fetch_count = 0

    async def get_key(self, kid: str) -> Any:
        """Chave pública do `kid`, buscando o JWKS só quando necessário."""
        key = self._cached(kid)
        if key is not None:
            return key

        async with self._lock:
            # Recheque dentro do lock: enquanto esperávamos, outra corrotina pode
            # ter feito exatamente a busca que íamos fazer.
            key = self._cached(kid)
            if key is not None:
                return key
            await self._refresh()
            key = self._keys.get(kid)

        if key is None:
            raise AccessTokenError(f"kid ausente do JWKS do Access: {kid!r}")
        return key

    def _cached(self, kid: str) -> Any | None:
        """Chave em cache, se o cache ainda está dentro do TTL."""
        if self._fetched_at is None:
            return None
        if time.monotonic() - self._fetched_at >= self._ttl:
            return None
        return self._keys.get(kid)

    async def _refresh(self) -> None:
        """Rebusca o JWKS, respeitando o cooldown. Chamado sob `self._lock`."""
        now = time.monotonic()

        # Carga inicial NÃO é rebusca, e por isso não gasta o orçamento do
        # cooldown. A diferença não é cosmética: contando a carga inicial, um
        # `kid` girado logo depois do boot cairia direto no freio, e a API
        # recusaria TODO mundo por uma janela inteira sem uma única tentativa de
        # se recuperar — indisponibilidade causada por um evento que quem
        # controla é a Cloudflare, não nós. Custa no máximo uma requisição extra.
        e_rebusca = self._fetched_at is not None

        if (
            e_rebusca
            and self._last_attempt is not None
            and now - self._last_attempt < self._cooldown
        ):
            # Freio de tempestade. Devolver sem buscar é seguro: as chaves já em
            # `self._keys` continuam válidas (a anterior vale 7 dias após girar),
            # então um TTL vencido dentro do cooldown degrada para "chave um
            # pouco velha", não para "recusa tudo".
            logger.debug("cf_access.jwks_refresh_skipped", certs_url=self._certs_url)
            return

        if e_rebusca:
            self._last_attempt = now
        try:
            async with httpx.AsyncClient(
                timeout=self._http_timeout, transport=self._transport
            ) as client:
                response = await client.get(self._certs_url)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Tentativa FALHA conta para o cooldown mesmo sendo a carga inicial —
            # aqui não vale a isenção acima. Sem isto, JWKS fora do ar viraria um
            # GET nosso por requisição recebida: exatamente a tempestade que o
            # freio existe para evitar, só que disparada por indisponibilidade em
            # vez de por token forjado.
            self._last_attempt = now
            # Fail-closed deliberado: JWKS inalcançável e cache vazio significa
            # que não sabemos verificar nada, e "não sei" aqui é recusa.
            logger.error(
                "cf_access.jwks_unreachable", certs_url=self._certs_url, error=str(exc)
            )
            raise AccessTokenError(f"JWKS inalcançável: {exc}") from exc

        keys: dict[str, Any] = {}
        for entry in payload.get("keys", []):
            kid = entry.get("kid")
            if not kid or entry.get("kty") != "RSA":
                continue
            try:
                keys[kid] = RSAAlgorithm.from_jwk(json.dumps(entry))
            except (jwt.PyJWTError, ValueError, TypeError) as exc:  # pragma: no cover
                logger.warning("cf_access.jwk_ignored", kid=kid, error=str(exc))

        if not keys:
            raise AccessTokenError(f"JWKS de {self._certs_url} veio sem chave RSA")

        # Substituição inteira, não merge: é assim que chave aposentada some do
        # cache. Um merge manteria para sempre toda chave já vista, e uma chave
        # revogada continuaria aceitando token.
        self._keys = keys
        self._fetched_at = time.monotonic()
        self.fetch_count += 1
        logger.info("cf_access.jwks_loaded", kids=sorted(keys), count=len(keys))


class CloudflareAccessVerifier:
    """Verifica assinatura, `aud`, `iss`, validade e identidade do dono."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        owner_emails: list[str],
        jwks: JwksCache,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._owner_emails = [e.strip().lower() for e in owner_emails]
        self._jwks = jwks

    @classmethod
    def from_settings(
        cls, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> CloudflareAccessVerifier:
        return cls(
            issuer=settings.cf_access_issuer,
            audience=settings.cf_access_aud,
            owner_emails=settings.cf_access_emails,
            jwks=JwksCache(
                settings.cf_access_certs_url,
                ttl_seconds=float(settings.cf_access_jwks_ttl_seconds),
                transport=transport,
            ),
        )

    async def verify(self, token: str) -> dict[str, Any]:
        """Claims do token, ou `AccessTokenError` nomeando o que reprovou."""
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AccessTokenError(f"header do JWT ilegível: {exc}") from exc

        # `algorithms=["RS256"]` no decode abaixo já barraria `alg: none` e a
        # confusão RS256/HS256. A checagem aqui existe para recusar ANTES de
        # tocar o JWKS: token com alg absurdo não merece uma ida à rede.
        alg = header.get("alg")
        if alg != "RS256":
            raise AccessTokenError(f"alg inesperado: {alg!r} (esperado RS256)")

        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise AccessTokenError("JWT sem `kid` — impossível escolher a chave")

        key = await self._jwks.get_key(kid)

        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                # `require` é o que impede token sem `exp` de valer para sempre e
                # token sem `email` de passar como anônimo: sem esta lista, claim
                # ausente é claim não verificado.
                options={"require": ["exp", "iat", "iss", "aud", "email"]},
            )
        except jwt.PyJWTError as exc:
            # NÃO redecodifique o token aqui para enfeitar o log. Redecodificar
            # dentro do `except` reintroduz a falha que acabou de acontecer: um
            # payload que não é base64/UTF-8 válido levanta `DecodeError` DE
            # DENTRO do handler, escapa de `AccessTokenError` e o gate devolve
            # 500 em vez de 401 — 500 que qualquer um dispara sem token nenhum.
            # O motivo real já vai no `AccessTokenError` e é logado em `_deny`.
            raise AccessTokenError(f"{type(exc).__name__}: {exc}") from exc
        email = claims.get("email")
        if not isinstance(email, str) or email.strip().lower() not in self._owner_emails:
            # O e-mail não está na lista de donos autorizados.
            raise AccessTokenError("claim `email` não é a de um dono autorizado")

        # Token de service token não traz `email` (traz `common_name`), então o
        # `require` acima já o reprova. É o comportamento desejado: nenhum
        # service token fala por este dono.
        return claims


def extract_token(scope: Scope) -> str | None:
    """Token do header do Access; na falta dele, do cookie `CF_Authorization`."""
    headers = Headers(scope=scope)

    token = headers.get(ACCESS_HEADER)
    if token and token.strip():
        return token.strip()

    raw_cookie = headers.get("cookie")
    if not raw_cookie:
        return None
    jar: SimpleCookie = SimpleCookie()
    try:
        jar.load(raw_cookie)
    except CookieError:
        # Cookie malformado é entrada hostil ou cliente quebrado; nos dois casos
        # a resposta é "sem token", não uma exceção de 500.
        return None
    morsel = jar.get(ACCESS_COOKIE)
    if morsel is None or not morsel.value:
        return None
    return morsel.value


class CloudflareAccessMiddleware:
    """Gate ASGI puro: nega por default, libera `/health` por exceção.

    **Por que middleware ASGI e não `Depends`.** Um `Depends` é opt-in: cada
    router novo precisa lembrar de pedi-lo, e o dia em que alguém esquecer não
    dá erro nenhum — dá uma rota aberta. Gate de autenticação tem de ser opt-out,
    e ele já cobre `/docs`, `/openapi.json` e qualquer rota futura sem uma linha
    a mais.

    **Por que ASGI puro e não `BaseHTTPMiddleware`.** `BaseHTTPMiddleware` só é
    invocado para `scope["type"] == "http"`. A rota `/api/chat/ws` é o canal
    principal do sistema, e ela é `websocket` — passaria inteira por fora do
    gate, que é exatamente o furo mais fácil de não notar (o HTTP dá 401 nos
    testes manuais e a impressão é de que está tudo protegido). Aqui os dois
    tipos de scope entram pela mesma porta.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        verifier: CloudflareAccessVerifier,
        public_paths: frozenset[str] = PUBLIC_PATHS,
    ) -> None:
        self.app = app
        self._verifier = verifier
        self._public_paths = public_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            # `lifespan` — não é requisição e não tem o que autenticar.
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in self._public_paths:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        
        # Bypass local para o app Desktop (Tauri).
        # Requisições que passam pelo Cloudflare Tunnel recebem o header 'cf-ray'.
        # Se 'cf-ray' não está presente, a requisição foi feita DIRETAMENTE
        # na porta local (ex: localhost:8000), o que só é possível de dentro da
        # própria máquina, não pelo túnel.
        if "cf-ray" not in headers:
            scope["cf_access_claims"] = {"email": self._verifier._owner_emails[0]}
            await self.app(scope, receive, send)
            return

        token = extract_token(scope)
        if token is None:
            await self._deny(scope, receive, send, path, "sem asserção do Access")
            return

        try:
            claims = await self._verifier.verify(token)
        except AccessTokenError as exc:
            await self._deny(scope, receive, send, path, str(exc))
            return

        # Identidade verificada no scope: quem estiver abaixo lê daqui em vez de
        # reler o header cru, que é o hábito que reintroduz confiança em header.
        scope["cf_access_claims"] = claims
        await self.app(scope, receive, send)

    async def _deny(
        self, scope: Scope, receive: Receive, send: Send, path: str, reason: str
    ) -> None:
        logger.warning(
            "cf_access.denied",
            path=path,
            scope_type=scope["type"],
            reason=reason,
        )
        if scope["type"] == "websocket":
            # Fechar antes do accept: o handshake nunca se completa. Consumimos o
            # `websocket.connect` primeiro porque é o que o protocolo ASGI manda
            # — servidor que espera por ele trava se pularmos essa etapa.
            await receive()
            await send({"type": "websocket.close", "code": _WS_POLICY_VIOLATION})
            return
        response = JSONResponse({"detail": _DENY_DETAIL}, status_code=401)
        await response(scope, receive, send)


def install_cloudflare_access(
    app: FastAPI,
    settings: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bool:
    """Instala o gate se ele estiver ligado. Devolve se instalou.

    A decisão de ligar mora em `Settings.cf_access_enforced`; aqui só se anuncia
    o resultado, alto, porque "a API está autenticada?" precisa ser respondível
    lendo o `docker logs` do boot, sem inspecionar processo em execução.
    """
    resolved = settings or get_settings()

    if not resolved.cf_access_enforced:
        if resolved.environment == "prod":
            logger.error(
                "cf_access.disabled_in_prod",
                enforce=resolved.cf_access_enforce,
                detail=(
                    "ORIGEM SEM AUTENTICAÇÃO em produção. Qualquer requisição que "
                    "alcance este container é atendida. Só faz sentido se houver "
                    "outro gate na frente."
                ),
            )
        else:
            logger.info(
                "cf_access.disabled",
                enforce=resolved.cf_access_enforce,
                environment=resolved.environment,
                detail="sem Access configurado; gate fora do caminho em desenvolvimento",
            )
        return False

    app.add_middleware(
        CloudflareAccessMiddleware,
        verifier=CloudflareAccessVerifier.from_settings(
            resolved, transport=transport or _http_transport()
        ),
    )
    logger.info(
        "cf_access.enabled",
        issuer=resolved.cf_access_issuer,
        aud=resolved.cf_access_aud,
        owners=resolved.cf_access_emails,
        public_paths=sorted(PUBLIC_PATHS),
    )
    return True


__all__ = [
    "ACCESS_COOKIE",
    "ACCESS_HEADER",
    "PUBLIC_PATHS",
    "AccessTokenError",
    "CloudflareAccessMiddleware",
    "CloudflareAccessVerifier",
    "JwksCache",
    "extract_token",
    "install_cloudflare_access",
]
