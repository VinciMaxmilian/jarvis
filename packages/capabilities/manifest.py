"""Os dois arquivos de uma capability em disco: `manifest.yaml` e `permissions.yaml`.

`plan-scheme.md` fixa o layout: identidade e tools no `manifest.yaml`, FS e rede no
`permissions.yaml`. `packages/shared/contracts.py` fixa o schema: `permissions` é um
bloco **dentro** do `CapabilityManifest`, porque é ele que o registry grava na tabela
e o kernel lê para montar a política. Os dois estão certos e não se contradizem se o
`permissions.yaml` for tratado como o que é: a superfície de leitura do dono — o
arquivo que se abre para responder "o que esta coisa pode tocar?" sem ler 200 linhas
de JSON Schema — espelhando o bloco do manifest.

Espelho **conferido**, não confiado: divergência entre os dois arquivos é o pior caso
possível, porque o dono aprova lendo um e o kernel aplica o outro. Aqui isso é erro
nomeando o campo; `render_permissions_yaml()` existe para que ninguém precise
escrever o espelho à mão.

Por que este módulo não reusa `packages/registry/manifest.py`: são dois momentos com
tolerâncias opostas. O registry carrega no boot e não pode derrubar o sistema por um
manifest torto — ele degrada para `disabled` e segue (D-4). O SDK valida na autoria e
no teste, onde o certo é recusar tudo que não está exatamente no contrato: campo
desconhecido, `transport` que virou `runtime`, tool no código e não no manifest. O
schema em si é um só — `CapabilityManifest` — e é dele que os dois dependem.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from packages.capabilities.base import Capability
from packages.capabilities.errors import ManifestInvalido, Problema
from packages.shared.contracts import (
    CapabilityManifest,
    CapabilityPermissions,
    CapabilityStatus,
    ToolSpec,
)

NOME_MANIFEST = "manifest.yaml"
NOME_PERMISSOES = "permissions.yaml"

#: Chave do YAML com as intenções que acionam a capability (`plan.md` §6). Vive
#: fora do `CapabilityManifest` porque o contrato ainda não a declara — ver
#: `packages/registry/manifest.py`, que a lê pelo mesmo motivo.
CHAVE_TRIGGER_INTENT = "trigger_intent"

#: Campos aceitos no `manifest.yaml` além dos do contrato. Lista fechada: campo
#: desconhecido é descartado em silêncio pelo Pydantic, e permissão escrita num
#: campo com nome errado é permissão que ninguém concedeu e todo mundo acha que
#: concedeu.
EXTRAS_ACEITOS = frozenset({CHAVE_TRIGGER_INTENT})

#: Campos renomeados e a mensagem do conserto. `transport` virou `runtime` na v1.2
#: (`plan-execution.md` §2); um manifest com o nome antigo carrega com o runtime
#: **default**, o que é pior do que falhar.
RENOMEADOS = {
    "transport": "runtime — renomeado na v1.2; o valor 'mcp_stdio' virou 'mcp'",
}

#: Chaves do `permissions.yaml`. É exatamente `CapabilityPermissions`.
CHAVES_PERMISSOES = frozenset({"network", "filesystem", "process"})


class ArquivosDaCapability(BaseModel):
    """O que existe em disco, já validado. Fronteira entre o YAML e o resto."""

    model_config = ConfigDict(frozen=True)

    directory: Path
    manifest: CapabilityManifest
    trigger_intents: tuple[str, ...] = ()
    #: `permissions.yaml` presente. Ausente não é erro de schema — é aviso do
    #: harness, porque o layout de `plan-scheme.md` o exige e o dono o lê.
    tem_permissions_yaml: bool = False

    @property
    def permissions(self) -> CapabilityPermissions:
        """A concessão efetiva: a do manifest, que é a que o kernel aplica."""
        return self.manifest.permissions


# --------------------------------------------------------------------------- #
# Leitura
# --------------------------------------------------------------------------- #


def _ler_mapa(path: Path, campo: str, problemas: list[Problema]) -> dict[str, Any]:
    """Lê um YAML que tem de ser um mapa. Acumula problema em vez de levantar."""
    try:
        bruto = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        problemas.append(Problema(campo=campo, mensagem=f"não encontrado: {path}"))
        return {}
    except yaml.YAMLError as exc:
        problemas.append(Problema(campo=campo, mensagem=f"YAML inválido: {exc}"))
        return {}

    if bruto is None:
        problemas.append(Problema(campo=campo, mensagem=f"vazio: {path}"))
        return {}
    if not isinstance(bruto, dict):
        problemas.append(
            Problema(
                campo=campo,
                mensagem=f"tem de ser um mapa, veio {type(bruto).__name__}",
            )
        )
        return {}
    return dict(bruto)


def _intents(dados: dict[str, Any], problemas: list[Problema]) -> tuple[str, ...]:
    bruto = dados.get(CHAVE_TRIGGER_INTENT)
    if bruto is None:
        return ()
    if isinstance(bruto, str):
        return (bruto,)
    if isinstance(bruto, list):
        return tuple(str(item) for item in bruto if str(item).strip())
    problemas.append(
        Problema(
            campo=CHAVE_TRIGGER_INTENT,
            mensagem=f"string ou lista de strings, veio {type(bruto).__name__}",
        )
    )
    return ()


def _conferir_chaves(dados: dict[str, Any], problemas: list[Problema]) -> None:
    conhecidos = set(CapabilityManifest.model_fields) | EXTRAS_ACEITOS
    for chave in dados:
        if chave in conhecidos:
            continue
        if chave in RENOMEADOS:
            problemas.append(
                Problema(campo=chave, mensagem=f"campo removido; use {RENOMEADOS[chave]}")
            )
            continue
        problemas.append(
            Problema(
                campo=chave,
                mensagem=(
                    "campo desconhecido — seria descartado em silêncio. "
                    f"Conhecidos: {', '.join(sorted(conhecidos))}"
                ),
            )
        )


def _problemas_de_validacao(exc: ValidationError) -> list[Problema]:
    return [
        Problema(
            campo=".".join(str(parte) for parte in erro["loc"]) or "<raiz>",
            mensagem=str(erro["msg"]),
        )
        for erro in exc.errors()
    ]


def _conferir_permissions_yaml(
    path: Path, manifest: CapabilityManifest, problemas: list[Problema]
) -> bool:
    """Confere o espelho. Devolve se o arquivo existe."""
    if not path.is_file():
        return False

    dados = _ler_mapa(path, NOME_PERMISSOES, problemas)
    if not dados:
        return True

    desconhecidas = sorted(set(dados) - CHAVES_PERMISSOES)
    for chave in desconhecidas:
        problemas.append(
            Problema(
                campo=f"{NOME_PERMISSOES}:{chave}",
                mensagem=(
                    "chave desconhecida — o arquivo é exatamente network, "
                    "filesystem e process"
                ),
            )
        )

    try:
        espelho = CapabilityPermissions.model_validate(
            {k: v for k, v in dados.items() if k in CHAVES_PERMISSOES}
        )
    except ValidationError as exc:
        for problema in _problemas_de_validacao(exc):
            problemas.append(
                Problema(
                    campo=f"{NOME_PERMISSOES}:{problema.campo}",
                    mensagem=problema.mensagem,
                )
            )
        return True

    if espelho != manifest.permissions:
        problemas.append(
            Problema(
                campo=NOME_PERMISSOES,
                mensagem=(
                    "diverge de permissions do manifest — o dono aprova lendo este "
                    f"arquivo e o kernel aplica o outro. Aqui: {_resumo(espelho)}; "
                    f"no manifest: {_resumo(manifest.permissions)}"
                ),
            )
        )
    return True


def _resumo(p: CapabilityPermissions) -> str:
    return (
        f"network={list(p.network)} filesystem={list(p.filesystem)} process={p.process}"
    )


def carregar_arquivos(directory: str | Path) -> ArquivosDaCapability:
    """Lê e valida `manifest.yaml` + `permissions.yaml` de uma capability.

    Raises:
        ManifestInvalido: com **todos** os problemas encontrados, cada um nomeando
            o campo. Consertar um por execução é o laço que a v3 pagaria em token.
    """
    raiz = Path(directory)
    problemas: list[Problema] = []

    dados = _ler_mapa(raiz / NOME_MANIFEST, NOME_MANIFEST, problemas)
    if not dados:
        raise ManifestInvalido(raiz, problemas)

    _conferir_chaves(dados, problemas)
    intents = _intents(dados, problemas)

    try:
        manifest = CapabilityManifest.model_validate(dados)
    except ValidationError as exc:
        problemas.extend(_problemas_de_validacao(exc))
        raise ManifestInvalido(raiz / NOME_MANIFEST, problemas) from exc

    if manifest.name != raiz.name:
        problemas.append(
            Problema(
                campo="name",
                mensagem=(
                    f"{manifest.name!r} não é o nome do diretório ({raiz.name!r}) — "
                    "o diretório é a chave em disco e o sufixo da branch"
                ),
            )
        )

    problemas.extend(_conferir_entrypoint(manifest))
    tem_espelho = _conferir_permissions_yaml(
        raiz / NOME_PERMISSOES, manifest, problemas
    )

    if problemas:
        raise ManifestInvalido(raiz, problemas)

    return ArquivosDaCapability(
        directory=raiz,
        manifest=manifest,
        trigger_intents=intents,
        tem_permissions_yaml=tem_espelho,
    )


def _conferir_entrypoint(manifest: CapabilityManifest) -> list[Problema]:
    """`modulo:atributo` para quem roda código; URL para quem fala HTTP.

    A forma é conferida aqui, e não no kernel, porque o kernel só descobriria o
    erro na primeira execução — depois de o Gate 2 já ter aprovado.
    """
    if not manifest.entrypoint.strip():
        problemas = [Problema(campo="entrypoint", mensagem="obrigatório")]
        return problemas
    if manifest.runtime == "http":
        return []
    if ":" not in manifest.entrypoint:
        return [
            Problema(
                campo="entrypoint",
                mensagem=(
                    f"{manifest.entrypoint!r} precisa da forma 'modulo:atributo' "
                    f"para o runtime {manifest.runtime!r}"
                ),
            )
        ]
    return []


def permissoes_declaradas(directory: str | Path) -> CapabilityPermissions:
    """A concessão em disco. É com isto que uma capability se constrói.

    O caminho normal do `entrypoint()`: a capability não escolhe o próprio escopo,
    ela o recebe do manifest que o dono aprovou.
    """
    return carregar_arquivos(directory).permissions


# --------------------------------------------------------------------------- #
# Escrita — o manifest é gerado da classe, não digitado
# --------------------------------------------------------------------------- #


def manifest_de(
    cap: type[Capability],
    *,
    entrypoint: str,
    permissions: CapabilityPermissions | None = None,
    status: CapabilityStatus = CapabilityStatus.PENDING_APPROVAL,
    approved_commit: str | None = None,
) -> CapabilityManifest:
    """Monta o `CapabilityManifest` a partir da declaração em código.

    Só três coisas não saem da classe, e não é por acaso: `entrypoint` é onde o
    código foi instalado, `status` e `approved_commit` são o que o gate decidiu.
    Nenhuma das três pode ser o código dizendo de si mesmo que está aprovado.

    `permissions` default é o **mínimo** que as tools exigem. É ponto de partida
    para o dono revisar no Gate 1, não concessão automática.
    """
    exigido = cap.requirements()
    concessao = permissions or CapabilityPermissions(
        network=list(exigido.network),
        filesystem=list(exigido.filesystem),
        process=exigido.process,
    )
    return CapabilityManifest(
        name=cap.name,
        version=cap.version,
        description=cap.description,
        status=status,
        approved_commit=approved_commit,
        entrypoint=entrypoint,
        runtime=cap.runtime,
        permissions=concessao,
        tools=cap.tool_specs(),
        dependencies=list(cap.dependencies),
    )


def _yaml(dados: dict[str, Any]) -> str:
    return yaml.safe_dump(dados, allow_unicode=True, sort_keys=False, width=88)


def render_manifest_yaml(
    manifest: CapabilityManifest, *, trigger_intents: Sequence[str] = ()
) -> str:
    """O `manifest.yaml` em texto, na ordem dos campos do contrato.

    `sort_keys=False` importa: o arquivo é lido por gente no Gate 2, e a ordem do
    contrato põe identidade e permissões antes do JSON Schema das tools.
    `created_at`/`updated_at` ficam de fora — são default do modelo e gravá-los
    faria o arquivo mudar a cada geração, sujando o diff que o gate lê.
    """
    dados = manifest.model_dump(mode="json", exclude={"created_at", "updated_at"})
    if trigger_intents:
        dados[CHAVE_TRIGGER_INTENT] = list(trigger_intents)
    return _yaml(dados)


def render_permissions_yaml(permissions: CapabilityPermissions) -> str:
    """O espelho legível de `permissions` do manifest. Gerado, nunca digitado."""
    cabecalho = (
        "# Espelho de `permissions` do manifest.yaml — o kernel aplica o manifest,\n"
        "# este arquivo existe para ser lido (plan-scheme.md). Gerado por\n"
        "# packages.capabilities.render_permissions_yaml: divergência entre os dois\n"
        "# é erro no harness.\n"
    )
    return cabecalho + _yaml(permissions.model_dump(mode="json"))


def escrever_arquivos(
    directory: str | Path,
    manifest: CapabilityManifest,
    *,
    trigger_intents: Sequence[str] = (),
) -> tuple[Path, Path]:
    """Grava os dois arquivos coerentes por construção. Devolve os dois caminhos."""
    raiz = Path(directory)
    raiz.mkdir(parents=True, exist_ok=True)
    caminho_manifest = raiz / NOME_MANIFEST
    caminho_permissoes = raiz / NOME_PERMISSOES
    caminho_manifest.write_text(
        render_manifest_yaml(manifest, trigger_intents=trigger_intents),
        encoding="utf-8",
    )
    caminho_permissoes.write_text(
        render_permissions_yaml(manifest.permissions), encoding="utf-8"
    )
    return caminho_manifest, caminho_permissoes


def specs_por_nome(specs: Sequence[ToolSpec]) -> dict[str, ToolSpec]:
    """Índice por nome, para comparar catálogo do manifest com o do código."""
    return {spec.name: spec for spec in specs}


__all__ = [
    "CHAVES_PERMISSOES",
    "CHAVE_TRIGGER_INTENT",
    "EXTRAS_ACEITOS",
    "NOME_MANIFEST",
    "NOME_PERMISSOES",
    "RENOMEADOS",
    "ArquivosDaCapability",
    "carregar_arquivos",
    "escrever_arquivos",
    "manifest_de",
    "permissoes_declaradas",
    "render_manifest_yaml",
    "render_permissions_yaml",
    "specs_por_nome",
]
