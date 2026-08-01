"""Gate do Cloudflare Access: verificação do JWT na origem.

A suíte assina os próprios tokens com um par RSA gerado na fixture e serve o
JWKS por `httpx.MockTransport`. **Nada aqui toca a rede**: um teste de
autenticação que depende da Cloudflare estar de pé falha por motivo errado e,
pior, passa a ser ignorado quando falha.

O que está sendo protegido é uma afirmação de uma linha só — "quem chegou aqui é
o dono" — e cada recusa abaixo é uma forma diferente de essa afirmação ser
falsa: sem token, token de outra aplicação (`aud`), de outra equipe (`iss`), de
outra pessoa (`email`), vencido, ou assinado por quem não é o Access.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterator
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request, WebSocket
from jwt.algorithms import RSAAlgorithm
from pydantic import ValidationError
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from apps.api import cf_access as cf
from apps.api.cf_access import (
    AccessTokenError,
    CloudflareAccessMiddleware,
    CloudflareAccessVerifier,
    JwksCache,
    extract_token,
)
from packages.shared.settings import Settings

TEAM = "meutime.cloudflareaccess.com"
ISSUER = f"https://{TEAM}"
CERTS_URL = f"{ISSUER}/cdn-cgi/access/certs"
AUD = "a" * 64  # tag Application Audience: hex de 64 caracteres
OWNER = "dono@exemplo.com"
KID = "kid-atual"
KID_NOVO = "kid-pos-rotacao"


# --------------------------------------------------------------------------- #
# Chaves e tokens
# --------------------------------------------------------------------------- #


def _generate_key() -> rsa.RSAPrivateKey:
    # 2048 bits: o mínimo aceito como sério e o mais barato de gerar. A geração
    # roda uma vez por sessão porque a 4096 custaria segundos em cada execução.
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def keypair() -> rsa.RSAPrivateKey:
    return _generate_key()


@pytest.fixture(scope="session")
def key_alheia() -> rsa.RSAPrivateKey:
    """Par RSA que o Access NÃO conhece — assinatura tecnicamente válida,
    proveniência errada. É o token forjado por quem leu o formato."""
    return _generate_key()


def _jwk(private_key: rsa.RSAPrivateKey, kid: str) -> dict[str, Any]:
    """JWK público no formato que o `/cdn-cgi/access/certs` devolve."""
    entry: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    entry.update(kid=kid, alg="RS256", use="sig")
    return entry


def make_token(
    private_key: rsa.RSAPrivateKey,
    *,
    kid: str = KID,
    aud: str = AUD,
    iss: str = ISSUER,
    email: str | None = OWNER,
    expira_em: int = 300,
    algorithm: str = "RS256",
    key_override: Any = None,
) -> str:
    """Token no formato do Access (claims conferidos na doc `Application token`).

    `expira_em` negativo produz token vencido; `email=None` produz o token de
    service token, que não carrega identidade humana nenhuma.
    """
    agora = int(time.time())
    payload: dict[str, Any] = {
        "aud": aud,
        "iss": iss,
        "iat": agora,
        "nbf": agora,
        "exp": agora + expira_em,
        "type": "app",
        "sub": "7335d417-61da-459d-899c-0a01c76a2f94",
        "identity_nonce": "6ei69kawdKzMIAPF",
        "country": "BR",
    }
    if email is not None:
        payload["email"] = email
    chave = key_override if key_override is not None else private_key
    return jwt.encode(payload, chave, algorithm=algorithm, headers={"kid": kid})


# --------------------------------------------------------------------------- #
# JWKS servido em memória
# --------------------------------------------------------------------------- #


class FakeJwksEndpoint:
    """`/cdn-cgi/access/certs` em memória, com contador de acessos.

    O contador é o que permite afirmar "não buscou de novo" — sem número, a
    exigência de cache vira comentário no código.
    """

    def __init__(self, keys: list[dict[str, Any]]) -> None:
        self.keys = keys
        self.hits = 0
        self.status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert str(request.url) == CERTS_URL, f"URL inesperada: {request.url}"
        self.hits += 1
        if self.status != 200:
            return httpx.Response(self.status, text="indisponível")
        return httpx.Response(200, json={"keys": self.keys})

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


@pytest.fixture
def jwks(keypair: rsa.RSAPrivateKey) -> FakeJwksEndpoint:
    return FakeJwksEndpoint([_jwk(keypair, KID)])


@pytest.fixture
def verifier(jwks: FakeJwksEndpoint) -> CloudflareAccessVerifier:
    return CloudflareAccessVerifier(
        issuer=ISSUER,
        audience=AUD,
        owner_email=OWNER,
        jwks=JwksCache(CERTS_URL, transport=jwks.transport),
    )


# --------------------------------------------------------------------------- #
# App sintético — a matriz de recusa não precisa de banco nem de rota real
# --------------------------------------------------------------------------- #


@pytest.fixture
def app(verifier: CloudflareAccessVerifier) -> FastAPI:
    aplicacao = FastAPI()
    aplicacao.add_middleware(CloudflareAccessMiddleware, verifier=verifier)

    @aplicacao.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @aplicacao.get("/api/protegido")
    def protegido(request: Request) -> dict[str, Any]:
        # Lê a identidade do scope, que é onde o middleware a deixou já
        # verificada — nunca do header cru.
        return {"email": request.scope["cf_access_claims"]["email"]}

    @aplicacao.websocket("/api/chat/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_text("aceito")
        await websocket.close()

    return aplicacao


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _hdr(token: str) -> dict[str, str]:
    return {"Cf-Access-Jwt-Assertion": token}


# --------------------------------------------------------------------------- #
# Matriz de aceite e recusa (HTTP)
# --------------------------------------------------------------------------- #


def test_health_dispensa_token(client: TestClient) -> None:
    """O HEALTHCHECK do Dockerfile bate aqui de dentro do container e não tem
    como obter JWT. Se esta rota exigir token, o container nunca fica healthy e
    o compose derruba a stack inteira por 'falha' de autenticação."""
    resposta = client.get("/health")

    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}


def test_token_valido_e_aceito(client: TestClient, keypair: rsa.RSAPrivateKey) -> None:
    resposta = client.get("/api/protegido", headers=_hdr(make_token(keypair)))

    assert resposta.status_code == 200
    assert resposta.json() == {"email": OWNER}


def test_token_valido_pelo_cookie_e_aceito(
    client: TestClient, keypair: rsa.RSAPrivateKey
) -> None:
    """O Access também deposita o token no cookie `CF_Authorization`. Ele é
    fallback, não fonte primária — a doc avisa que o cookie pode não chegar."""
    resposta = client.get(
        "/api/protegido", cookies={"CF_Authorization": make_token(keypair)}
    )

    assert resposta.status_code == 200


def test_sem_token_e_recusado(client: TestClient) -> None:
    resposta = client.get("/api/protegido")

    assert resposta.status_code == 401
    # A resposta não diz QUAL verificação falhou: distinguir isso daria a quem
    # sonda um oráculo para calibrar o próximo palpite.
    assert resposta.json()["detail"] == cf._DENY_DETAIL


def test_aud_de_outra_aplicacao_e_recusado(
    client: TestClient, keypair: rsa.RSAPrivateKey
) -> None:
    """A mesma conta Zero Trust assina token para todas as suas aplicações. Sem
    conferir o `aud`, o token de qualquer outra aplicação do dono abre esta."""
    token = make_token(keypair, aud="b" * 64)

    assert client.get("/api/protegido", headers=_hdr(token)).status_code == 401


def test_email_de_outra_identidade_e_recusado(
    client: TestClient, keypair: rsa.RSAPrivateKey
) -> None:
    """Token assinado, no prazo e para esta aplicação — e ainda assim recusado.
    Sistema de um usuário só: identidade diferente é recusa, não aviso."""
    token = make_token(keypair, email="outra.pessoa@exemplo.com")

    assert client.get("/api/protegido", headers=_hdr(token)).status_code == 401


def test_token_vencido_e_recusado(
    client: TestClient, keypair: rsa.RSAPrivateKey
) -> None:
    token = make_token(keypair, expira_em=-60)

    assert client.get("/api/protegido", headers=_hdr(token)).status_code == 401


def test_issuer_de_outra_equipe_e_recusado(
    client: TestClient, keypair: rsa.RSAPrivateKey
) -> None:
    token = make_token(keypair, iss="https://outraequipe.cloudflareaccess.com")

    assert client.get("/api/protegido", headers=_hdr(token)).status_code == 401


def test_assinatura_de_chave_alheia_e_recusada(
    client: TestClient, keypair: rsa.RSAPrivateKey, key_alheia: rsa.RSAPrivateKey
) -> None:
    """`kid` conhecido, formato perfeito, chave errada — o caso que só a
    verificação criptográfica pega."""
    token = make_token(keypair, key_override=key_alheia)

    assert client.get("/api/protegido", headers=_hdr(token)).status_code == 401


def test_token_sem_email_e_recusado(
    client: TestClient, keypair: rsa.RSAPrivateKey
) -> None:
    """É a forma do token de *service token*, que traz `common_name` e nenhuma
    identidade humana. Nenhum service token fala pelo dono."""
    token = make_token(keypair, email=None)

    assert client.get("/api/protegido", headers=_hdr(token)).status_code == 401


def test_token_alg_none_e_recusado(client: TestClient) -> None:
    """`alg: none` é o ataque de manual: payload legítimo, assinatura vazia."""
    agora = int(time.time())
    token = jwt.encode(
        {
            "aud": AUD,
            "iss": ISSUER,
            "email": OWNER,
            "iat": agora,
            "exp": agora + 300,
        },
        key="",
        algorithm="none",
        headers={"kid": KID},
    )

    assert client.get("/api/protegido", headers=_hdr(token)).status_code == 401


def test_token_hs256_com_kid_conhecido_e_recusado(client: TestClient) -> None:
    """Confusão de algoritmo: o atacante assina em HMAC esperando que a chave
    pública RSA seja usada como segredo."""
    agora = int(time.time())
    token = jwt.encode(
        {
            "aud": AUD,
            "iss": ISSUER,
            "email": OWNER,
            "iat": agora,
            "exp": agora + 300,
        },
        key="segredo",
        algorithm="HS256",
        headers={"kid": KID},
    )

    assert client.get("/api/protegido", headers=_hdr(token)).status_code == 401


def test_lixo_no_header_e_recusado(client: TestClient) -> None:
    assert client.get("/api/protegido", headers=_hdr("nem-jwt-e")).status_code == 401


def test_docs_e_openapi_ficam_atras_do_gate(client: TestClient) -> None:
    """Rota que ninguém registrou à mão também é coberta — é a razão de o gate
    ser middleware e não `Depends`."""
    assert client.get("/openapi.json").status_code == 401
    assert client.get("/docs").status_code == 401


# --------------------------------------------------------------------------- #
# WebSocket — o furo que `BaseHTTPMiddleware` deixaria passar
# --------------------------------------------------------------------------- #


def test_websocket_sem_token_e_recusado(client: TestClient) -> None:
    """`BaseHTTPMiddleware` só é chamado para scope `http`; o canal principal do
    sistema é `websocket` e passaria inteiro por fora do gate."""
    with pytest.raises(WebSocketDisconnect) as erro:  # noqa: SIM117
        with client.websocket_connect("/api/chat/ws"):
            pass  # pragma: no cover — o handshake não chega a completar

    assert erro.value.code == 1008  # policy violation


def test_websocket_com_token_invalido_e_recusado(
    client: TestClient, keypair: rsa.RSAPrivateKey
) -> None:
    token = make_token(keypair, email="invasor@exemplo.com")

    with pytest.raises(WebSocketDisconnect):  # noqa: SIM117
        with client.websocket_connect("/api/chat/ws", headers=_hdr(token)):
            pass  # pragma: no cover


def test_websocket_com_token_valido_e_aceito(
    client: TestClient, keypair: rsa.RSAPrivateKey
) -> None:
    with client.websocket_connect(
        "/api/chat/ws", headers=_hdr(make_token(keypair))
    ) as ws:
        assert ws.receive_text() == "aceito"


# --------------------------------------------------------------------------- #
# Extração do token
# --------------------------------------------------------------------------- #


def _scope(headers: list[tuple[bytes, bytes]]) -> dict[str, Any]:
    return {"type": "http", "path": "/x", "headers": headers}


def test_header_tem_precedencia_sobre_cookie() -> None:
    scope = _scope(
        [
            (b"cf-access-jwt-assertion", b"do-header"),
            (b"cookie", b"CF_Authorization=do-cookie"),
        ]
    )

    assert extract_token(scope) == "do-header"


def test_cookie_e_o_fallback() -> None:
    scope = _scope([(b"cookie", b"outro=1; CF_Authorization=do-cookie")])

    assert extract_token(scope) == "do-cookie"


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [(b"cf-access-jwt-assertion", b"   ")],
        [(b"cookie", b"CF_Authorization=")],
        [(b"cookie", b"nada=aqui")],
        [(b"cookie", b"=;;")],  # cookie malformado é "sem token", não 500
    ],
)
def test_ausencia_de_token_nao_levanta(headers: list[tuple[bytes, bytes]]) -> None:
    assert extract_token(_scope(headers)) is None


# --------------------------------------------------------------------------- #
# Cache do JWKS: rotação sem tempestade de requisições
# --------------------------------------------------------------------------- #


async def test_jwks_e_buscado_uma_vez_e_reusado(jwks: FakeJwksEndpoint) -> None:
    cache = JwksCache(CERTS_URL, transport=jwks.transport)

    for _ in range(10):
        assert await cache.get_key(KID) is not None

    assert jwks.hits == 1, (
        "buscar o JWKS a cada request põe a Cloudflare no caminho crítico"
    )


async def test_buscas_concorrentes_colapsam_em_uma(jwks: FakeJwksEndpoint) -> None:
    """Cache frio com 20 requisições simultâneas: o lock tem de deixar UMA
    passar. Sem ele, o primeiro request depois de um restart vira uma rajada."""
    cache = JwksCache(CERTS_URL, transport=jwks.transport)

    await asyncio.gather(*(cache.get_key(KID) for _ in range(20)))

    assert jwks.hits == 1


async def test_kid_novo_dispara_exatamente_uma_rebusca(
    jwks: FakeJwksEndpoint, keypair: rsa.RSAPrivateKey
) -> None:
    """Rotação: a chave girou e o token chega com `kid` que nunca vimos."""
    cache = JwksCache(CERTS_URL, transport=jwks.transport, refetch_cooldown_seconds=0.0)
    await cache.get_key(KID)
    assert jwks.hits == 1

    jwks.keys = [_jwk(keypair, KID_NOVO)]

    assert await cache.get_key(KID_NOVO) is not None
    assert jwks.hits == 2


async def test_kid_desconhecido_nao_vira_tempestade(jwks: FakeJwksEndpoint) -> None:
    """`kid` inventado é o caminho de quem forja token. Sem cooldown, cada
    requisição forjada viraria um GET nosso para a Cloudflare — o atacante
    passaria a escolher o nosso tráfego de saída."""
    cache = JwksCache(
        CERTS_URL, transport=jwks.transport, refetch_cooldown_seconds=3600.0
    )
    await cache.get_key(KID)
    assert jwks.hits == 1

    for i in range(25):
        with pytest.raises(AccessTokenError):
            await cache.get_key(f"kid-forjado-{i}")

    assert jwks.hits == 2, "uma rebusca, não uma por requisição"


async def test_chave_aposentada_some_do_cache(
    jwks: FakeJwksEndpoint, keypair: rsa.RSAPrivateKey
) -> None:
    """Substituição inteira do mapa, não merge: chave revogada tem de parar de
    aceitar token."""
    cache = JwksCache(
        CERTS_URL,
        transport=jwks.transport,
        ttl_seconds=0.0,
        refetch_cooldown_seconds=0.0,
    )
    await cache.get_key(KID)

    jwks.keys = [_jwk(keypair, KID_NOVO)]

    with pytest.raises(AccessTokenError):
        await cache.get_key(KID)


async def test_jwks_inalcancavel_recusa_em_vez_de_liberar(
    jwks: FakeJwksEndpoint,
) -> None:
    """Fail-closed: sem as chaves não sabemos verificar nada, e 'não sei' em
    autenticação é recusa."""
    jwks.status = 503
    cache = JwksCache(CERTS_URL, transport=jwks.transport)

    with pytest.raises(AccessTokenError):
        await cache.get_key(KID)


async def test_verificador_devolve_as_claims(
    verifier: CloudflareAccessVerifier, keypair: rsa.RSAPrivateKey
) -> None:
    claims = await verifier.verify(make_token(keypair))

    assert claims["email"] == OWNER
    # O PyJWT NÃO normaliza `aud`: devolve a claim como ela veio no token. Ele
    # aceita string ou lista na *verificação* (parâmetro `audience`), mas o
    # payload retornado é literal. Um token do Access traz `aud` como lista de um
    # elemento; este aqui é assinado por `make_token`, que põe a string.
    assert claims["aud"] == AUD
    assert claims["iss"] == ISSUER


async def test_email_do_dono_compara_sem_caixa(
    jwks: FakeJwksEndpoint, keypair: rsa.RSAPrivateKey
) -> None:
    """IdP pode devolver `Dono@Exemplo.com`. Recusar o dono por causa de
    maiúscula é o tipo de rigor que faz alguém desligar o gate."""
    verificador = CloudflareAccessVerifier(
        issuer=ISSUER,
        audience=AUD,
        owner_email="Dono@Exemplo.COM",
        jwks=JwksCache(CERTS_URL, transport=jwks.transport),
    )

    assert await verificador.verify(make_token(keypair, email="DONO@exemplo.com"))


# --------------------------------------------------------------------------- #
# Settings: o default de enforcement e as falhas altas
# --------------------------------------------------------------------------- #

_BASE: dict[str, Any] = {
    "database_url": "postgresql+asyncpg://u:p@h:5432/d",
    "tavily_api_key": "tvly-teste",
    "_env_file": None,  # isola do .env da raiz: a suíte não depende da máquina
}


@pytest.fixture(autouse=True)
def _sem_cf_no_ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    """Variável CF_* exportada na máquina não pode mudar o resultado do teste."""
    for nome in (
        "CF_ACCESS_TEAM_DOMAIN",
        "CF_ACCESS_AUD",
        "CF_ACCESS_EMAIL",
        "CF_ACCESS_ENFORCE",
        "ENVIRONMENT",
    ):
        monkeypatch.delenv(nome, raising=False)


def _settings(**overrides: Any) -> Settings:
    return Settings(**{**_BASE, **overrides})  # type: ignore[arg-type]


_CONFIGURADO: dict[str, Any] = {
    "cf_access_team_domain": "meutime",
    "cf_access_aud": AUD,
    "cf_access_email": OWNER,
}


def test_dev_sem_access_configurado_nao_exige_token() -> None:
    """O default não pode quebrar `127.0.0.1:8000`, onde não existe Access e
    portanto não existe JWT — gate que impede o dono de trabalhar é desligado."""
    config = _settings(environment="dev")

    assert config.cf_access_enforced is False


def test_access_configurado_liga_o_gate_sozinho() -> None:
    """Quem preencheu as três variáveis já montou o Access. Exigir um segundo
    passo ('agora ligue') é criar um passo para esquecer."""
    assert _settings(**_CONFIGURADO).cf_access_enforced is True


def test_prod_sem_access_e_sem_decisao_nao_sobe() -> None:
    """O caso que este default existe para impedir: a origem de pé, publicada,
    sem autenticação nenhuma. Não subir é estritamente melhor."""
    with pytest.raises(ValidationError, match="sem Cloudflare Access configurado"):
        _settings(environment="prod")


def test_prod_com_off_explicito_sobe() -> None:
    """Escape hatch consciente (outro gate na frente). Ela existe, mas grita no
    log de boot em nível ERROR — ver `install_cloudflare_access`."""
    config = _settings(environment="prod", cf_access_enforce="off")

    assert config.cf_access_enforced is False


@pytest.mark.parametrize(
    "faltando", ["cf_access_team_domain", "cf_access_aud", "cf_access_email"]
)
def test_configuracao_pela_metade_derruba_o_boot(faltando: str) -> None:
    """Meia configuração não vira meio-gate. Com `CF_ACCESS_AUD` em branco, por
    exemplo, uma verificação escrita sem cuidado aceitaria qualquer aplicação da
    conta."""
    parcial = {**_CONFIGURADO, faltando: ""}

    with pytest.raises(ValidationError, match="pela metade"):
        _settings(**parcial)


def test_enforce_on_sem_configuracao_derruba_o_boot() -> None:
    with pytest.raises(ValidationError, match="CF_ACCESS_ENFORCE=on exige"):
        _settings(cf_access_enforce="on")


def test_off_explicito_desliga_mesmo_configurado() -> None:
    assert _settings(**_CONFIGURADO, cf_access_enforce="off").cf_access_enforced is False


@pytest.mark.parametrize(
    "entrada",
    [
        "meutime",
        "meutime.cloudflareaccess.com",
        "https://meutime.cloudflareaccess.com",
        "https://meutime.cloudflareaccess.com/",
        "https://meutime.cloudflareaccess.com/cdn-cgi/access/certs",
        "  MeuTime  ",
    ],
)
def test_team_domain_normaliza_o_que_o_dono_copiou(entrada: str) -> None:
    """O dashboard exibe o valor de várias formas. Uma barra sobrando reprovaria
    todo token válido, porque `iss` é comparado byte a byte."""
    config = _settings(**{**_CONFIGURADO, "cf_access_team_domain": entrada})

    assert config.cf_access_issuer == ISSUER
    assert config.cf_access_certs_url == CERTS_URL


def test_settings_vazio_nao_deriva_url_invalida() -> None:
    config = _settings()

    assert config.cf_access_issuer == ""
    assert config.cf_access_certs_url == ""


# --------------------------------------------------------------------------- #
# App real: as rotas que existem de verdade estão cobertas
# --------------------------------------------------------------------------- #


@pytest.fixture
def app_real(
    monkeypatch: pytest.MonkeyPatch, jwks: FakeJwksEndpoint
) -> Iterator[FastAPI]:
    """`create_app()` de verdade, com Access ligado e JWKS servido em memória.

    O app sintético acima prova a lógica do gate; este prova a FIAÇÃO — que
    `/health` continua livre, que `/api/chat/ws` está coberta e que a ordem
    CORS/Access em `main.py` não deixou o gate por fora.
    """
    from packages.shared.settings import get_settings

    for nome, valor in (
        ("CF_ACCESS_TEAM_DOMAIN", TEAM),
        ("CF_ACCESS_AUD", AUD),
        ("CF_ACCESS_EMAIL", OWNER),
    ):
        monkeypatch.setenv(nome, valor)
    monkeypatch.setattr(cf, "_http_transport", lambda: jwks.transport)

    get_settings.cache_clear()
    try:
        from apps.api.main import create_app

        yield create_app()
    finally:
        # A instância é cacheada por processo: deixá-la suja contaminaria
        # qualquer teste posterior que leia configuração.
        get_settings.cache_clear()


def test_app_real_health_dispensa_token(app_real: FastAPI) -> None:
    assert TestClient(app_real).get("/health").status_code == 200


def test_app_real_recusa_sem_token(app_real: FastAPI) -> None:
    assert TestClient(app_real).get("/openapi.json").status_code == 401


def test_app_real_aceita_token_do_dono(
    app_real: FastAPI, keypair: rsa.RSAPrivateKey
) -> None:
    resposta = TestClient(app_real).get(
        "/openapi.json", headers=_hdr(make_token(keypair))
    )

    assert resposta.status_code == 200


def test_app_real_websocket_do_chat_esta_coberto(app_real: FastAPI) -> None:
    """`/api/chat/ws` é o canal principal do sistema. Se ele ficar de fora, o
    401 no HTTP dá a impressão de que está tudo protegido."""
    with pytest.raises(WebSocketDisconnect):  # noqa: SIM117
        with TestClient(app_real).websocket_connect("/api/chat/ws"):
            pass  # pragma: no cover


def test_app_real_websocket_do_chat_aceita_o_dono(
    app_real: FastAPI, keypair: rsa.RSAPrivateKey
) -> None:
    with TestClient(app_real).websocket_connect(
        "/api/chat/ws", headers=_hdr(make_token(keypair))
    ):
        pass


def test_preflight_cors_nao_e_barrado_pelo_gate(app_real: FastAPI) -> None:
    """O navegador manda `OPTIONS` sem credencial nenhuma. Com o Access por fora
    do CORS, todo preflight tomaria 401 e o PWA quebraria com um erro de CORS
    que não tem nada a ver com CORS."""
    resposta = TestClient(app_real).options(
        "/api/chat/",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert resposta.status_code == 200
    assert resposta.headers["access-control-allow-origin"] == "http://localhost:5173"
