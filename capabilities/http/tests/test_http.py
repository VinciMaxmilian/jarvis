"""Teste da capability `http`.

`plan-scheme.md`: uma capability sem `tests/` não passa do Gate 2, e o resultado
deste arquivo é anexo obrigatório do gate (`plan.md` §8).

**Nenhuma linha toca a rede.** O cliente HTTP é injetado, no mesmo molde da sonda
de `exemplo_nas`, e a suíte roda offline (`plan-execution.md` §1.0b). O que se
prova aqui é a fronteira — qual host passa, qual não passa, o que vira erro do SDK
e o que vira resposta — e essa parte não precisa de servidor nenhum.

O que a suíte **não** prova é o `cliente_httpx`: ele exige rede e está marcado com
`pragma: no cover`. O que ele faz de específico (ler em pedaços para o teto de
tamanho ser teto de verdade) está documentado no módulo e no README.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from capabilities.http.backend.handlers import DIRETORIO, Http, Resposta
from packages.capabilities import (
    CapabilityHarness,
    CasoDeTool,
    EntradaInvalida,
    PermissaoNaoDeclarada,
)
from packages.shared.contracts import CapabilityPermissions

#: Os hosts do teste. Dois para que "concedido" e "não concedido" sejam duas
#: asserções e não uma coincidência.
HOST = "api.exemplo.com"
OUTRO_HOST = "evil.exemplo.com"

CASOS = (
    CasoDeTool(
        tool="http_get",
        arguments={"url": f"https://{HOST}/v1/status"},
        espera={"status_code": 200, "truncado": False},
        descricao="busca um recurso num host concedido",
    ),
    CasoDeTool(
        tool="http_post",
        arguments={
            "url": f"https://{HOST}/v1/itens",
            "corpo": '{"nome": "x"}',
        },
        espera={"status_code": 200},
        descricao="envia um corpo para um host concedido",
    ),
)


class ClienteEspiao:
    """Cliente determinístico que guarda o que recebeu. Sem rede, sem servidor."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        corpo: str = "ok",
        erro: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self.corpo = corpo
        self.erro = erro
        self.chamadas: list[dict[str, object]] = []

    def __call__(
        self,
        metodo: str,
        url: str,
        *,
        headers: Mapping[str, str],
        corpo: str | None,
        timeout: float,
        max_bytes: int,
    ) -> Resposta:
        self.chamadas.append(
            {
                "metodo": metodo,
                "url": url,
                "headers": dict(headers),
                "corpo": corpo,
                "timeout": timeout,
                "max_bytes": max_bytes,
            }
        )
        if self.erro is not None:
            raise self.erro
        bruto = self.corpo.encode("utf-8")
        return Resposta(
            status_code=self.status_code,
            headers={"content-type": "application/json"},
            corpo=self.corpo[:max_bytes],
            bytes=min(len(bruto), max_bytes),
            truncado=len(bruto) > max_bytes,
        )


@pytest.fixture
def concessao() -> CapabilityPermissions:
    return CapabilityPermissions(network=[HOST], filesystem=[], process=False)


@pytest.fixture
def cliente() -> ClienteEspiao:
    return ClienteEspiao()


@pytest.fixture
def capability(
    concessao: CapabilityPermissions, cliente: ClienteEspiao
) -> Http:
    return Http(concessao, cliente=cliente)


def test_a_capability_passa_pelo_harness(capability: Http) -> None:
    """O aceite: manifest, catálogo, permissões, layout, dry_run e os dois casos."""
    relatorio = CapabilityHarness(DIRETORIO, capability).rodar(CASOS)

    assert relatorio.ok, relatorio.resumo()
    assert relatorio.casos_executados == len(CASOS)


def test_host_nao_concedido_e_negado(capability: Http) -> None:
    """A conferência é em runtime porque o host vem no argumento, não no código."""
    with pytest.raises(PermissaoNaoDeclarada) as exc:
        capability.call("http_get", {"url": f"https://{OUTRO_HOST}/x"})

    assert exc.value.kind == "network"
    assert exc.value.target == OUTRO_HOST
    assert exc.value.tool == "http_get"


def test_host_negado_nao_chega_a_requisitar(
    capability: Http, cliente: ClienteEspiao
) -> None:
    """A negação vem antes da chamada — não é a resposta que é descartada."""
    with pytest.raises(PermissaoNaoDeclarada):
        capability.call("http_get", {"url": f"https://{OUTRO_HOST}/x"})

    assert cliente.chamadas == []


def test_porta_no_host_nao_muda_a_concessao(
    capability: Http, cliente: ClienteEspiao
) -> None:
    """`permissions.network` é lista de hosts; conceder o host concede a porta."""
    capability.call("http_get", {"url": f"https://{HOST}:8443/x"})

    assert cliente.chamadas[0]["url"] == f"https://{HOST}:8443/x"


def test_sem_concessao_de_rede_nada_sai(cliente: ClienteEspiao) -> None:
    """Capability construída sem manifest não fala com ninguém."""
    with pytest.raises(PermissaoNaoDeclarada) as exc:
        Http(cliente=cliente).call("http_get", {"url": f"https://{HOST}/x"})

    assert exc.value.kind == "network"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://api.exemplo.com/x",
        "api.exemplo.com/x",
        "https:///sem-host",
        "https://user:senha@api.exemplo.com/x",
    ],
)
def test_url_invalida_morre_no_schema(capability: Http, url: str) -> None:
    """Esquema errado, host ausente e credencial embutida morrem antes do I/O."""
    with pytest.raises(EntradaInvalida) as exc:
        capability.call("http_get", {"url": url})

    assert [p.campo for p in exc.value.problemas] == ["url"]


def test_header_com_quebra_de_linha_e_recusado(capability: Http) -> None:
    """Injeção de cabeçalho: `\\r\\n` num valor transforma uma requisição em duas."""
    with pytest.raises(EntradaInvalida) as exc:
        capability.call(
            "http_get",
            {"url": f"https://{HOST}/x", "headers": {"X-A": "b\r\nX-B: c"}},
        )

    assert [p.campo for p in exc.value.problemas] == ["headers"]


def test_timeout_acima_do_teto_morre_no_schema(capability: Http) -> None:
    with pytest.raises(EntradaInvalida) as exc:
        capability.call("http_get", {"url": f"https://{HOST}/x", "timeout": 9_999})

    assert [p.campo for p in exc.value.problemas] == ["timeout"]


def test_timeout_e_max_bytes_chegam_ao_cliente(
    capability: Http, cliente: ClienteEspiao
) -> None:
    """Teto que não é repassado não é teto."""
    capability.call(
        "http_get", {"url": f"https://{HOST}/x", "timeout": 3, "max_bytes": 128}
    )

    assert cliente.chamadas[0]["timeout"] == 3
    assert cliente.chamadas[0]["max_bytes"] == 128


def test_resposta_grande_volta_cortada_e_marcada(
    concessao: CapabilityPermissions,
) -> None:
    """Diferente de `fs_ler`, aqui corta em vez de recusar: o começo é a resposta."""
    grande = Http(concessao, cliente=ClienteEspiao(corpo="x" * 5_000))

    saida = grande.call(
        "http_get", {"url": f"https://{HOST}/x", "max_bytes": 100}
    )

    assert saida["truncado"] is True
    assert saida["bytes"] == 100


def test_status_de_erro_nao_e_falha_da_tool(
    concessao: CapabilityPermissions,
) -> None:
    """404 é resposta: a requisição foi feita e o servidor respondeu."""
    quatro_zero_quatro = Http(
        concessao, cliente=ClienteEspiao(status_code=404, corpo="nao achei")
    )

    saida = quatro_zero_quatro.call("http_get", {"url": f"https://{HOST}/x"})

    assert saida["status_code"] == 404
    assert saida["corpo"] == "nao achei"


def test_falha_de_transporte_vira_erro_do_sdk(
    concessao: CapabilityPermissions,
) -> None:
    """Erro da biblioteca HTTP nunca sobe cru para quem chamou."""
    caiu = Http(
        concessao, cliente=ClienteEspiao(erro=OSError("connection refused"))
    )

    with pytest.raises(EntradaInvalida) as exc:
        caiu.call("http_get", {"url": f"https://{HOST}/x"})

    assert [p.campo for p in exc.value.problemas] == ["url"]


def test_post_manda_corpo_e_content_type(
    capability: Http, cliente: ClienteEspiao
) -> None:
    capability.call(
        "http_post",
        {
            "url": f"https://{HOST}/itens",
            "corpo": '{"a": 1}',
            "content_type": "application/json",
        },
    )

    chamada = cliente.chamadas[0]
    assert chamada["metodo"] == "POST"
    assert chamada["corpo"] == '{"a": 1}'
    assert chamada["headers"]["content-type"] == "application/json"


def test_get_e_idempotente_e_post_exige_aprovacao() -> None:
    """O catálogo é o que o kernel lê antes de repetir ou de perguntar."""
    specs = {s.name: s for s in Http.tool_specs()}

    assert specs["http_get"].idempotent is True
    assert specs["http_get"].requires_approval is False
    assert specs["http_post"].idempotent is False
    assert specs["http_post"].requires_approval is True


def test_nenhuma_tool_declara_host_estatico() -> None:
    """O host vem no argumento; declarar um fixo seria mentir no catálogo.

    É por isto que o harness avisa sobre hosts concedidos e não exigidos — o aviso
    está certo sobre o fato e errado sobre a conclusão (ver `docs/README.md`).
    """
    assert Http.requirements().network == ()
