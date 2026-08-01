"""A classe base, o decorator de tool e o despacho de uma capability.

`plan.md` §7: cada capability é um mini software com fronteira explícita —
manifest, permissões declaradas, schema de entrada e saída, implementação,
testes. Este módulo é a metade em código dessa fronteira; a metade em disco está
em `manifest.py`.

**MCP é o padrão de tools; o SDK envolve e expõe MCP, não o substitui**
(`tools.md` §7). Concretamente: o que sai daqui é `ToolSpec` com `input_schema`
em JSON Schema, que é o formato de tool do MCP. O SDK não inventa protocolo — ele
acrescenta o que o MCP não cobre neste caso (manifest com estado e aprovação,
permissão declarada, ciclo de vida) e deixa o transporte para o kernel.

Quatro decisões que o código sozinho não explica:

- **Entrada e saída são modelos Pydantic, não dicionários.** O invariante de
  `plan-execution.md` §7 é que nenhum dict solto atravesse fronteira de módulo, e
  a fronteira capability↔kernel é uma delas. O dicionário aparece só nas duas
  pontas — `arguments` que chega do kernel e o mapa JSON que volta — porque é o
  formato de `Task.input`/`Task.output`. Entre uma ponta e outra existe modelo.
- **A tool declara de que precisa (`requires`); o manifest concede.** São duas
  declarações separadas de propósito: a primeira é do autor do código, a segunda
  é do dono que aprovou. Comparar as duas pega, sem rodar nada, a capability que
  pediu SMB e passou a falar HTTP — o item 3 do Gate 2 (`plan.md` §8) na sua
  forma barata.
- **`dry_run` não chama o handler.** Ele monta o `Ensaio` — o que faria, com
  quais argumentos, tocando o quê — e devolve. `plan.md` §9 exige que a primeira
  execução registre sem fazer; um `if dry_run` dentro de cada handler seria uma
  linha que o autor esquece, e o esquecimento só aparece depois do efeito.
- **A classe é validada na criação, não na chamada.** Ver `DeclaracaoInvalida`.

Contrato com o kernel (`packages/kernel/runtime/_child.py`): `manifest.entrypoint`
é `modulo:atributo` e o atributo é chamado como `atributo(tool, arguments)`,
devolvendo mapa serializável em JSON. `entrypoint()` produz exatamente esse
chamável a partir da classe.

O despacho é **síncrono** porque esse contrato é síncrono: a capability roda em
subprocesso próprio, e o paralelismo que interessa é o do supervisor, não o de
dentro dela. Handler que precise de I/O assíncrono chama `asyncio.run()` no
próprio corpo — é um event loop por execução, num processo que existe para uma
execução só.
"""

from __future__ import annotations

import inspect
import os
import os.path
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from packages.capabilities.errors import (
    DeclaracaoInvalida,
    EntradaInvalida,
    PermissaoNaoDeclarada,
    Problema,
    SaidaInvalida,
    ToolDesconhecida,
)
from packages.shared.contracts import RUNTIME_PADRAO, CapabilityPermissions, ToolSpec

#: Assinatura que o kernel chama no subprocesso. Não é escolha do SDK: está fixada
#: em `packages/kernel/runtime/_child.py`.
Handler = Callable[[str, dict[str, Any]], dict[str, Any]]

#: Onde o decorator pendura o marcador. Atributo de função, e não registro global,
#: porque duas capabilities importadas no mesmo processo não podem se misturar.
ATRIBUTO_TOOL = "_jarvis_tool"

#: Slug do `name`: é nome de diretório, de branch (`capability/<name>`) e chave do
#: registry ao mesmo tempo. Maiúscula e hífen quebram pelo menos um dos três.
PADRAO_NOME = re.compile(r"[a-z][a-z0-9_]*")

#: Semver simples. Sem faixa nem curinga: versão de capability é ponto fixo que o
#: Gate 2 aprovou, não intervalo a resolver.
PADRAO_VERSAO = re.compile(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?")

F = TypeVar("F", bound=Callable[..., Any])


class ToolRequirements(BaseModel):
    """O que uma tool precisa alcançar para funcionar. Declarado no código.

    É o espelho de `CapabilityPermissions`, com um papel diferente: aquele é o que
    o dono **concedeu** no manifest, este é o que o autor **pediu** na tool. O SDK
    recusa a diferença; o kernel aplica a concessão.

    `filesystem` aqui é raro e proposital: a maioria das capabilities recebe a raiz
    de trabalho pela própria concessão (`permissions.filesystem` do manifest) e não
    tem caminho fixo a exigir. Declarar caminho aqui só faz sentido quando ele é
    constante da implementação — um socket, um diretório de sistema.
    """

    model_config = ConfigDict(frozen=True)

    #: Hosts ou IPs que a tool contata. Vazio = a tool não usa rede.
    network: tuple[str, ...] = ()
    #: Caminhos absolutos fixos que a tool escreve. Vazio no caso normal.
    filesystem: tuple[str, ...] = ()
    #: A tool inicia subprocesso externo.
    process: bool = False

    def alvos(self) -> tuple[tuple[str, str], ...]:
        """Pares `(kind, target)` de tudo que a tool exige, para conferência."""
        pares: list[tuple[str, str]] = [("network", h) for h in self.network]
        pares.extend(("filesystem", p) for p in self.filesystem)
        if self.process:
            pares.append(("process", "subprocesso"))
        return tuple(pares)

    @property
    def vazio(self) -> bool:
        return not (self.network or self.filesystem or self.process)


class Ensaio(BaseModel):
    """O que a tool faria, sem ter feito. Retorno de `call(dry_run=True)`.

    `executado` existe para o harness **provar** que o handler não rodou, em vez
    de o teste confiar que não rodou.
    """

    model_config = ConfigDict(frozen=True)

    dry_run: bool = True
    executado: bool = False
    capability: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    requires: ToolRequirements = Field(default_factory=ToolRequirements)


@dataclass(frozen=True)
class ToolDeclaration:
    """Uma tool declarada em código, pronta para virar `ToolSpec`.

    Dataclass e não modelo Pydantic porque carrega classe e função — coisas que
    não atravessam processo nem viram YAML. O que atravessa é a `ToolSpec` que
    `spec()` produz, e essa é contrato.
    """

    name: str
    description: str
    entrada: type[BaseModel]
    saida: type[BaseModel] | None
    requires: ToolRequirements
    idempotent: bool
    requires_approval: bool
    handler: Callable[..., Any]

    def spec(self) -> ToolSpec:
        """A tool no formato do catálogo — `input_schema` é JSON Schema (MCP)."""
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=self.entrada.model_json_schema(),
            output_schema=(
                self.saida.model_json_schema(mode="serialization") if self.saida else None
            ),
            idempotent=self.idempotent,
            requires_approval=self.requires_approval,
        )


@dataclass(frozen=True)
class _Marcador:
    """O que o decorator guarda até a classe existir."""

    name: str | None
    description: str
    entrada: type[BaseModel]
    saida: type[BaseModel] | None
    requires: ToolRequirements
    idempotent: bool
    requires_approval: bool


def tool(
    *,
    description: str,
    entrada: type[BaseModel],
    saida: type[BaseModel] | None = None,
    name: str | None = None,
    requires: ToolRequirements | None = None,
    idempotent: bool = False,
    requires_approval: bool = False,
) -> Callable[[F], F]:
    """Marca um método como tool da capability.

    O método continua sendo um método normal — o decorator devolve a mesma função,
    sem embrulho. Quem chama por fora usa `Capability.call()`, que valida; quem
    chama por dentro (um handler que reaproveita outro) chama o método direto e
    paga o preço de não ter validação, que é o certo para chamada interna.

    Args:
        description: entra no catálogo e é o que o Chief AI lê ao escolher a tool.
        entrada: modelo Pydantic dos argumentos. Vira o `input_schema` da `ToolSpec`.
        saida: modelo Pydantic do retorno. `None` deixa o handler devolver um mapa.
        name: nome da tool no catálogo. Default: o nome do método.
        requires: alvos que a tool precisa alcançar (ver `ToolRequirements`).
        idempotent: repetir a chamada tem o mesmo efeito de chamar uma vez.
        requires_approval: a execução exige aprovação do dono antes de acontecer.
    """

    def decorar(func: F) -> F:
        marcador = _Marcador(
            name=name,
            description=description,
            entrada=entrada,
            saida=saida,
            requires=requires or ToolRequirements(),
            idempotent=idempotent,
            requires_approval=requires_approval,
        )
        setattr(func, ATRIBUTO_TOOL, marcador)
        return func

    return decorar


def _normalizar_caminho(caminho: str) -> str:
    """Caminho absoluto canônico, sem tocar o disco (o alvo pode não existir)."""
    return os.path.normpath(os.path.abspath(caminho))


def _dentro(alvo: str, raiz: str) -> bool:
    """`True` se `alvo` está sob `raiz`.

    Prefixo **com separador**: sem ele `/dados/nas` concederia `/dados/nas_publico`,
    que é outro diretório. Mesma regra do kernel, aplicada aqui sobre caminho
    declarado — não sobre chamada de `open()`.
    """
    alvo_n = _normalizar_caminho(alvo)
    raiz_n = _normalizar_caminho(raiz)
    return alvo_n == raiz_n or alvo_n.startswith(raiz_n.rstrip(os.sep) + os.sep)


def concedido(
    kind: str, target: str, permissions: CapabilityPermissions
) -> bool:
    """`True` se `permissions` cobre o alvo exigido por uma tool.

    Função e não método porque a conferência acontece em dois momentos com donos
    diferentes: no despacho (contra a concessão da instância) e na verificação do
    manifest (contra a concessão em disco, sem instância nenhuma).
    """
    if kind == "network":
        declarados = {h.strip().lower() for h in permissions.network if h.strip()}
        return target.strip().lower() in declarados
    if kind == "filesystem":
        return any(_dentro(target, raiz) for raiz in permissions.filesystem)
    if kind == "process":
        return permissions.process
    return False


def alvos_nao_concedidos(
    requires: ToolRequirements, permissions: CapabilityPermissions
) -> tuple[tuple[str, str], ...]:
    """Os pares `(kind, target)` que a tool exige e o manifest não concede."""
    return tuple(
        (kind, target)
        for kind, target in requires.alvos()
        if not concedido(kind, target, permissions)
    )


class Capability:
    """Base de toda capability. Subclassear é declarar; o kernel é quem executa.

    A subclasse declara identidade em atributos de classe e comportamento em
    métodos decorados com `@tool`. A concessão de permissão **não** é atributo de
    classe: ela chega no construtor, vinda do `manifest.yaml` que o dono aprovou.
    Fosse atributo de classe, o código concederia a si mesmo o que quisesse, e o
    gate não teria o que aprovar.
    """

    #: Slug único. É o nome do diretório em `capabilities/` e o sufixo da branch.
    name: ClassVar[str] = ""
    #: Semver. Nova versão passa pelos mesmos dois gates (`plan.md` §7).
    version: ClassVar[str] = ""
    #: Uma frase. Entra no catálogo e pesa no casamento de intenção do registry.
    description: ClassVar[str] = ""
    #: Intenções que devem acionar a capability em `resolve()` (`plan.md` §6).
    trigger_intents: ClassVar[tuple[str, ...]] = ()
    #: Pacotes pip exigidos, iguais aos do manifest.
    dependencies: ClassVar[tuple[str, ...]] = ()
    #: Quem executa. O conjunto de adapters é do kernel; o default é o do contrato.
    runtime: ClassVar[str] = RUNTIME_PADRAO

    #: Preenchido por `__init_subclass__`. Chave é o nome da tool no catálogo.
    _declaracoes: ClassVar[dict[str, ToolDeclaration]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        problemas: list[Problema] = []
        cls._declaracoes = _coletar(cls, problemas)
        problemas.extend(_conferir_identidade(cls))
        if problemas:
            raise DeclaracaoInvalida(cls.name, problemas)

    def __init__(self, permissions: CapabilityPermissions | None = None) -> None:
        """`permissions` é a concessão do manifest. Ausente = nada concedido.

        O default vazio é o certo: capability construída sem manifest não tem
        escopo nenhum, e a primeira tool que exigir alvo será negada em vez de
        rodar com permissão que ninguém deu.
        """
        self._permissions = permissions or CapabilityPermissions()

    # ------------------------------------------------------------------ #
    # catálogo
    # ------------------------------------------------------------------ #

    @property
    def permissions(self) -> CapabilityPermissions:
        """A concessão sob a qual esta instância roda."""
        return self._permissions

    @classmethod
    def declarations(cls) -> tuple[ToolDeclaration, ...]:
        """As tools declaradas, em ordem de nome (determinismo de catálogo)."""
        return tuple(cls._declaracoes[nome] for nome in sorted(cls._declaracoes))

    @classmethod
    def tool_specs(cls) -> list[ToolSpec]:
        """O que vai para `manifest.tools` e para o catálogo do registry."""
        return [d.spec() for d in cls.declarations()]

    @classmethod
    def declaration(cls, tool_name: str) -> ToolDeclaration:
        decl = cls._declaracoes.get(tool_name)
        if decl is None:
            raise ToolDesconhecida(cls.name, tool_name, sorted(cls._declaracoes))
        return decl

    @classmethod
    def requirements(cls) -> ToolRequirements:
        """A união do que todas as tools exigem — o escopo mínimo do manifest."""
        network: list[str] = []
        filesystem: list[str] = []
        process = False
        for decl in cls.declarations():
            network.extend(decl.requires.network)
            filesystem.extend(decl.requires.filesystem)
            process = process or decl.requires.process
        return ToolRequirements(
            network=tuple(dict.fromkeys(network)),
            filesystem=tuple(dict.fromkeys(filesystem)),
            process=process,
        )

    # ------------------------------------------------------------------ #
    # despacho
    # ------------------------------------------------------------------ #

    def call(
        self,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Executa uma tool e devolve o mapa JSON que vira `Task.output`.

        Ordem fixa: existe a tool → o manifest concede o que ela exige → os
        argumentos casam com o schema → (dry_run devolve o ensaio) → o handler
        roda. A permissão vem antes da validação de entrada de propósito: negar
        por escopo é decisão sobre a capability, e não depende de o argumento
        estar bem formado.
        """
        decl = self.declaration(tool_name)
        self._conferir_permissoes(decl)
        entrada = self._validar_entrada(decl, dict(arguments or {}))

        if dry_run:
            ensaio = Ensaio(
                capability=self.name,
                tool=decl.name,
                arguments=entrada.model_dump(mode="json"),
                requires=decl.requires,
            )
            return ensaio.model_dump(mode="json")

        return self._serializar_saida(decl, decl.handler(self, entrada))

    def _conferir_permissoes(self, decl: ToolDeclaration) -> None:
        negados = alvos_nao_concedidos(decl.requires, self._permissions)
        if negados:
            kind, target = negados[0]
            raise PermissaoNaoDeclarada(kind, target, self.name, decl.name)

    def _validar_entrada(
        self, decl: ToolDeclaration, arguments: dict[str, Any]
    ) -> BaseModel:
        try:
            return decl.entrada.model_validate(arguments)
        except ValidationError as exc:
            raise EntradaInvalida(self.name, decl.name, _problemas(exc)) from exc

    def _serializar_saida(self, decl: ToolDeclaration, bruto: object) -> dict[str, Any]:
        if decl.saida is not None:
            if not isinstance(bruto, decl.saida):
                raise SaidaInvalida(
                    self.name,
                    decl.name,
                    f"esperava {decl.saida.__name__}, veio {type(bruto).__name__}",
                )
            dados = bruto.model_dump(mode="json")
            return dict(dados)
        if not isinstance(bruto, dict):
            raise SaidaInvalida(
                self.name,
                decl.name,
                f"sem modelo de saída declarado, o handler tem de devolver um mapa; "
                f"veio {type(bruto).__name__}",
            )
        return dict(bruto)


def entrypoint(fabrica: Callable[[], Capability]) -> Handler:
    """O chamável que o kernel invoca: `atributo(tool, arguments) -> dict`.

    Recebe uma fábrica, e não uma instância, porque construir a capability lê o
    `manifest.yaml` do disco e o import do módulo acontece **dentro** do
    subprocesso já com o guarda de permissões instalado
    (`packages/kernel/runtime/_child.py`). Adiar a construção para a primeira
    chamada mantém o import barato e sem I/O.

    A instância é reaproveitada entre chamadas do mesmo processo — o processo dura
    uma execução, então isso é cache de uma chamada só, mas o subprocesso é
    detalhe do kernel e não uma promessa do SDK.
    """
    instancia: list[Capability] = []

    def handler(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not instancia:
            instancia.append(fabrica())
        return instancia[0].call(tool_name, arguments)

    return handler


# --------------------------------------------------------------------------- #
# Coleta e conferência da declaração
# --------------------------------------------------------------------------- #


def _problemas(exc: ValidationError) -> tuple[Problema, ...]:
    """`ValidationError` do Pydantic em `Problema`, com o caminho do campo."""
    return tuple(
        Problema(
            campo=".".join(str(parte) for parte in erro["loc"]) or "<raiz>",
            mensagem=str(erro["msg"]),
        )
        for erro in exc.errors()
    )


def _coletar(
    cls: type[Capability], problemas: list[Problema]
) -> dict[str, ToolDeclaration]:
    """Varre a MRO atrás de métodos marcados por `@tool`.

    Da base para a subclasse: método sobrescrito na subclasse substitui o da base,
    que é o que `super()` já faz com qualquer método.
    """
    declaracoes: dict[str, ToolDeclaration] = {}
    origem: dict[str, str] = {}

    for base in reversed(cls.__mro__):
        for atributo_nome, valor in vars(base).items():
            marcador = getattr(valor, ATRIBUTO_TOOL, None)
            if not isinstance(marcador, _Marcador):
                continue
            nome = marcador.name or atributo_nome
            anterior = origem.get(nome)
            if anterior is not None and anterior != atributo_nome:
                problemas.append(
                    Problema(
                        campo=f"tools.{nome}",
                        mensagem=(
                            f"dois métodos declaram a mesma tool "
                            f"({anterior} e {atributo_nome}); nome de tool é chave"
                        ),
                    )
                )
                continue
            problemas.extend(_conferir_assinatura(valor, nome))
            origem[nome] = atributo_nome
            declaracoes[nome] = ToolDeclaration(
                name=nome,
                description=marcador.description,
                entrada=marcador.entrada,
                saida=marcador.saida,
                requires=marcador.requires,
                idempotent=marcador.idempotent,
                requires_approval=marcador.requires_approval,
                handler=valor,
            )
    return declaracoes


def _conferir_assinatura(func: Callable[..., Any], nome: str) -> list[Problema]:
    """O handler tem de ser `(self, entrada)`.

    O SDK valida o argumento e entrega **um modelo**; um handler com três
    parâmetros seria chamado errado na primeira execução, e a mensagem do
    `TypeError` não diz que o problema é a assinatura.
    """
    parametros = list(inspect.signature(func).parameters.values())
    if len(parametros) != 2:
        return [
            Problema(
                campo=f"tools.{nome}",
                mensagem=(
                    f"o handler tem de receber (self, entrada); recebe "
                    f"({', '.join(p.name for p in parametros) or 'nada'})"
                ),
            )
        ]
    return []


def _conferir_identidade(cls: type[Capability]) -> list[Problema]:
    """Nome, versão, descrição e ao menos uma tool. O mínimo para existir."""
    problemas: list[Problema] = []

    if not cls.name:
        problemas.append(Problema(campo="name", mensagem="obrigatório"))
    elif not PADRAO_NOME.fullmatch(cls.name):
        problemas.append(
            Problema(
                campo="name",
                mensagem=(
                    f"{cls.name!r} não é slug: minúsculas, dígitos e '_', começando "
                    "por letra — é nome de diretório e de branch ao mesmo tempo"
                ),
            )
        )

    if not cls.version:
        problemas.append(Problema(campo="version", mensagem="obrigatório"))
    elif not PADRAO_VERSAO.fullmatch(cls.version):
        problemas.append(
            Problema(campo="version", mensagem=f"{cls.version!r} não é semver x.y.z")
        )

    if not cls.description.strip():
        problemas.append(
            Problema(
                campo="description",
                mensagem="obrigatória — é o que o registry casa contra a intenção",
            )
        )

    if not cls._declaracoes:
        problemas.append(
            Problema(
                campo="tools",
                mensagem=(
                    "nenhum método decorado com @tool; "
                    "capability sem tool não faz nada"
                ),
            )
        )

    return problemas


def especificacoes(capabilities: Sequence[type[Capability]]) -> list[ToolSpec]:
    """Catálogo achatado de várias capabilities. Útil para montar um `ToolExecutor`."""
    return [spec for cap in capabilities for spec in cap.tool_specs()]


__all__ = [
    "ATRIBUTO_TOOL",
    "Capability",
    "Ensaio",
    "Handler",
    "ToolDeclaration",
    "ToolRequirements",
    "alvos_nao_concedidos",
    "concedido",
    "entrypoint",
    "especificacoes",
    "tool",
]
