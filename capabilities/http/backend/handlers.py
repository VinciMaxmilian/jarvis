"""O que a capability `http` faz: busca e envia por HTTP, só para hosts concedidos.

**A permissão de rede aqui é conferida em runtime, e isso é uma diferença real
para `exemplo_nas`.** O NAS contata um host só, conhecido em tempo de escrita, e
por isso a tool dele declara `requires=ToolRequirements(network=(HOST_NAS,))` —
declaração estática, que o SDK confere contra o manifest sem rodar nada. Uma
capability HTTP de uso geral não tem esse host: ele vem no argumento. Então as
tools daqui declaram `requires` **vazio** e a conferência acontece em
`_conferir_host()`, contra `permissions.network` da instância, a cada chamada.

Isso tem uma consequência visível e aceita: o harness avisa (`_avisos_de_escopo`)
que os hosts concedidos no manifest não são exigidos por nenhuma tool. O aviso
está certo sobre o fato e errado sobre a conclusão — está documentado em
`docs/README.md`. Aviso não derruba o harness; o que derrubaria seria declarar
`requires` estático mentindo que só um host é contatado.

Debaixo disto tudo continua o guarda do kernel, que intercepta `connect()` dentro
do subprocesso e é quem de fato impede a conexão. A camada daqui existe para que a
negação chegue a quem chamou como `PermissaoNaoDeclarada` com o host em `target`,
em vez de como task falhada com erro de socket.

Nada de `httpx` é importado no topo: o import mora em `cliente_httpx`, para que o
módulo carregue (e o harness confira o catálogo) numa máquina onde a dependência
não esteja instalada.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import NoReturn, Protocol

from pydantic import BaseModel, ConfigDict, Field

from capabilities.http.schemas import (
    GetEntrada,
    PostEntrada,
    RespostaSaida,
    host_de,
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
from packages.shared.contracts import CapabilityPermissions

#: Diretório da capability. Derivado de `__file__` e não do `cwd`.
DIRETORIO = Path(__file__).resolve().parents[1]

#: Quantos redirecionamentos seguir. Zero de propósito: seguir redirecionamento é
#: contatar um host que o chamador não pediu e que a conferência de escopo já
#: passou. O `Location` volta nos headers e quem quiser segui-lo chama de novo,
#: com o host novo passando pela mesma conferência.
REDIRECIONAMENTOS = False


class Resposta(BaseModel):
    """O que um cliente devolve. Fronteira entre a biblioteca HTTP e a tool."""

    model_config = ConfigDict(frozen=True)

    status_code: int
    headers: dict[str, str] = Field(default_factory=dict)
    corpo: str = ""
    bytes: int = 0
    truncado: bool = False


class Cliente(Protocol):
    """Faz a requisição. Injetável para o teste não tocar a rede."""

    def __call__(
        self,
        metodo: str,
        url: str,
        *,
        headers: Mapping[str, str],
        corpo: str | None,
        timeout: float,
        max_bytes: int,
    ) -> Resposta: ...


def cliente_httpx(  # pragma: no cover — exige rede
    metodo: str,
    url: str,
    *,
    headers: Mapping[str, str],
    corpo: str | None,
    timeout: float,
    max_bytes: int,
) -> Resposta:
    """O cliente real. Fora do teste por construção: a suíte roda sem rede.

    O corpo é lido **em pedaços**, e não com `response.text`: o teto de tamanho
    só é teto se a leitura parar quando ele é atingido. Baixar 500 MiB e depois
    cortar para 1 MiB gasta a banda e a memória que o teto existe para poupar.
    """
    import httpx

    with httpx.Client(
        timeout=timeout, follow_redirects=REDIRECIONAMENTOS
    ) as cliente:
        with cliente.stream(
            metodo, url, headers=dict(headers), content=corpo
        ) as resposta:
            pedacos: list[bytes] = []
            lidos = 0
            truncado = False
            for pedaco in resposta.iter_bytes():
                pedacos.append(pedaco)
                lidos += len(pedaco)
                if lidos >= max_bytes:
                    truncado = True
                    break
            bruto = b"".join(pedacos)[:max_bytes]
            return Resposta(
                status_code=resposta.status_code,
                headers={k.lower(): v for k, v in resposta.headers.items()},
                corpo=bruto.decode(resposta.encoding or "utf-8", errors="replace"),
                bytes=len(bruto),
                truncado=truncado,
            )


class Http(Capability):
    """Busca e envia por HTTP, só para os hosts concedidos no manifest."""

    name = "http"
    version = "0.1.0"
    description = (
        "Faz requisições HTTP GET e POST para os hosts concedidos no manifest, "
        "com timeout e teto de tamanho de resposta."
    )
    trigger_intents = (
        "buscar uma página ou API na internet",
        "consultar uma API HTTP",
        "enviar dados para uma API HTTP",
    )
    runtime = "python"

    def __init__(
        self,
        permissions: CapabilityPermissions | None = None,
        *,
        cliente: Cliente | None = None,
    ) -> None:
        """`cliente` é injeção, no mesmo molde da sonda de `exemplo_nas`."""
        super().__init__(permissions)
        self._cliente: Cliente = cliente or cliente_httpx

    # ------------------------------------------------------------------ #
    # fronteira
    # ------------------------------------------------------------------ #

    @property
    def hosts(self) -> tuple[str, ...]:
        """Os hosts concedidos, normalizados. Vazio = a capability não sai daqui."""
        return tuple(h.strip().lower() for h in self.permissions.network if h.strip())

    def _conferir_host(self, url: str, *, tool_name: str) -> str:
        """O host da URL contra `permissions.network`. É a conferência de escopo.

        `PermissaoNaoDeclarada` e não `EntradaInvalida` porque a URL está bem
        formada — o que falta é autorização, e é `kind`/`target` que vai para o
        log da task, não o texto da mensagem.
        """
        host = host_de(url)
        if host not in self.hosts:
            raise PermissaoNaoDeclarada("network", host, self.name, tool_name)
        return host

    def _recusar(self, tool_name: str, campo: str, mensagem: str) -> NoReturn:
        """Falha de rede em erro do SDK, nomeando o campo. Nunca exceção crua."""
        raise EntradaInvalida(
            self.name, tool_name, [Problema(campo=campo, mensagem=mensagem)]
        )

    def _requisitar(
        self,
        metodo: str,
        *,
        tool_name: str,
        url: str,
        headers: Mapping[str, str],
        corpo: str | None,
        timeout: float,
        max_bytes: int,
    ) -> RespostaSaida:
        """O caminho comum das duas tools: confere escopo, chama, embrulha."""
        self._conferir_host(url, tool_name=tool_name)
        try:
            resposta = self._cliente(
                metodo,
                url,
                headers=headers,
                corpo=corpo,
                timeout=timeout,
                max_bytes=max_bytes,
            )
        except Exception as exc:
            # `Exception` aberto porque a biblioteca HTTP é injetada e cada uma
            # tem a sua árvore de erro (`httpx.HTTPError`, `OSError`, `ssl`...).
            # Prender a lista aqui faria a próxima biblioteca vazar erro cru para
            # quem chamou, que é exatamente o que esta camada existe para evitar.
            self._recusar(
                tool_name, "url", f"a requisição para {url} falhou: {exc!r}"
            )

        return RespostaSaida(
            url=url,
            status_code=resposta.status_code,
            headers=dict(resposta.headers),
            corpo=resposta.corpo,
            bytes=resposta.bytes,
            truncado=resposta.truncado,
        )

    # ------------------------------------------------------------------ #
    # tools
    # ------------------------------------------------------------------ #

    @tool(
        description=(
            "Faz um GET numa URL de host concedido e devolve status, cabeçalhos e "
            "corpo, cortado no teto de tamanho."
        ),
        entrada=GetEntrada,
        saida=RespostaSaida,
        #: GET é a definição de idempotente no HTTP, e é o que permite ao kernel
        #: repetir a chamada depois de uma falha de transporte sem perguntar.
        idempotent=True,
    )
    def http_get(self, entrada: GetEntrada) -> RespostaSaida:
        return self._requisitar(
            "GET",
            tool_name="http_get",
            url=entrada.url,
            headers=entrada.headers,
            corpo=None,
            timeout=entrada.timeout,
            max_bytes=entrada.max_bytes,
        )

    @tool(
        description=(
            "Faz um POST numa URL de host concedido com o corpo em texto e "
            "devolve status, cabeçalhos e corpo da resposta."
        ),
        entrada=PostEntrada,
        saida=RespostaSaida,
        #: POST muda estado do outro lado, e o outro lado não é do dono.
        requires_approval=True,
    )
    def http_post(self, entrada: PostEntrada) -> RespostaSaida:
        headers = {"content-type": entrada.content_type, **entrada.headers}
        return self._requisitar(
            "POST",
            tool_name="http_post",
            url=entrada.url,
            headers=headers,
            corpo=entrada.corpo,
            timeout=entrada.timeout,
            max_bytes=entrada.max_bytes,
        )


def construir() -> Http:
    """A capability sob a concessão que está no manifest em disco.

    É a fábrica que o kernel usa. Lê o `manifest.yaml` — leitura, que o guarda de
    permissões não restringe — e monta a instância com os hosts que o dono
    aprovou, nunca com uma lista inventada aqui.
    """
    return Http(permissoes_declaradas(DIRETORIO))


#: O que `manifest.entrypoint` aponta: `atributo(tool, arguments) -> dict`.
main = entrypoint(construir)

__all__ = [
    "DIRETORIO",
    "REDIRECIONAMENTOS",
    "Cliente",
    "Http",
    "Resposta",
    "cliente_httpx",
    "construir",
    "main",
]
