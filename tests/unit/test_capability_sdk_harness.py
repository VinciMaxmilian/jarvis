"""O harness: o contrato de teste que toda capability usa.

Dois alvos aqui. O primeiro é o próprio harness — cada verificação tem um teste
que a vê **falhar**, porque verificação que nunca reprovou nada é verificação que
ninguém sabe se funciona. O segundo é o aceite da fatia: a capability de exemplo
(`capabilities/exemplo_nas/`) passa pelo harness inteira, e é ela o molde das
capabilities reais da v2.

A capability sintética daqui é instalada em `tmp_path` com o manifest gerado pelo
próprio SDK — o mesmo caminho que a v3 vai percorrer ao gerar uma capability nova.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import BaseModel

from capabilities.exemplo_nas.backend import handlers as exemplo
from packages.capabilities import (
    Capability,
    CapabilityHarness,
    CasoDeTool,
    Relatorio,
    ToolRequirements,
    entrypoint,
    escrever_arquivos,
    manifest_de,
    tool,
)
from packages.shared.contracts import CapabilityPermissions, CapabilityStatus

#: O manifest da capability sintética aponta para cá: o harness confere que o
#: `entrypoint` importa e é chamável, e este módulo é importável de verdade.
ENTRYPOINT = "tests.unit.test_capability_sdk_harness:main_sintetico"


class GravarEntrada(BaseModel):
    nome: str
    conteudo: str = ""


class GravarSaida(BaseModel):
    caminho: str
    bytes: int


class FalarEntrada(BaseModel):
    texto: str


class Sintetica(Capability):
    """Uma tool que escreve em disco e uma que exige rede. O mínimo realista."""

    name = "sintetica"
    version = "0.1.0"
    description = "Capability sintética do teste do harness."
    trigger_intents = ("gravar arquivo sintético",)
    runtime = "python"

    @tool(
        description="Grava um arquivo na raiz concedida.",
        entrada=GravarEntrada,
        saida=GravarSaida,
    )
    def gravar(self, entrada: GravarEntrada) -> GravarSaida:
        destino = Path(self.permissions.filesystem[0]) / entrada.nome
        return GravarSaida(
            caminho=str(destino),
            bytes=destino.write_text(entrada.conteudo, encoding="utf-8"),
        )

    @tool(
        description="Fala com um host declarado.",
        entrada=FalarEntrada,
        requires=ToolRequirements(network=("api.exemplo.com",)),
    )
    def falar(self, entrada: FalarEntrada) -> dict[str, str]:
        return {"texto": entrada.texto}


main_sintetico = entrypoint(Sintetica)

CASOS = (
    CasoDeTool(
        tool="gravar",
        arguments={"nome": "nota.txt", "conteudo": "abc"},
        espera={"bytes": 3},
    ),
    CasoDeTool(tool="falar", arguments={"texto": "oi"}, espera={"texto": "oi"}),
)


def instalar(
    base: Path,
    *,
    permissions: CapabilityPermissions | None = None,
    com_tests: bool = True,
    com_docs: bool = True,
    ajustar: dict[str, Any] | None = None,
) -> Path:
    """Instala a capability sintética em disco, como a v3 instalaria.

    `ajustar` reescreve o `manifest.yaml` já gerado — é como se produz o manifest
    torto que cada teste de reprovação precisa.
    """
    diretorio = base / Sintetica.name
    manifest = manifest_de(
        Sintetica,
        entrypoint=ENTRYPOINT,
        permissions=permissions
        or CapabilityPermissions(network=["api.exemplo.com"], filesystem=["/mnt/dados"]),
    )
    escrever_arquivos(diretorio, manifest, trigger_intents=Sintetica.trigger_intents)

    if ajustar is not None:
        dados = yaml.safe_load((diretorio / "manifest.yaml").read_text(encoding="utf-8"))
        dados.update(ajustar)
        (diretorio / "manifest.yaml").write_text(
            yaml.safe_dump(dados, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    if com_tests:
        (diretorio / "tests").mkdir(exist_ok=True)
        (diretorio / "tests" / "test_sintetica.py").write_text("", encoding="utf-8")
    if com_docs:
        (diretorio / "docs").mkdir(exist_ok=True)
        (diretorio / "docs" / "README.md").write_text("# doc", encoding="utf-8")
    return diretorio


@pytest.fixture
def concessao(tmp_path: Path) -> CapabilityPermissions:
    """Concessão de execução: a raiz vira `tmp_path`, a rede continua a do manifest."""
    return CapabilityPermissions(
        network=["api.exemplo.com"], filesystem=[str(tmp_path / "trabalho")]
    )


@pytest.fixture
def capability(concessao: CapabilityPermissions) -> Sintetica:
    Path(concessao.filesystem[0]).mkdir(parents=True, exist_ok=True)
    return Sintetica(concessao)


# --------------------------------------------------------------------------- #
# Caminho feliz
# --------------------------------------------------------------------------- #


def test_capability_bem_formada_passa_sem_erro_nem_aviso(
    tmp_path: Path, capability: Sintetica
) -> None:
    diretorio = instalar(tmp_path)

    relatorio = CapabilityHarness(diretorio, capability).verificar()

    assert relatorio.ok, relatorio.resumo()
    assert relatorio.avisos == ()
    assert relatorio.tools == ("falar", "gravar")


def test_rodar_ensaia_e_executa_cada_caso(
    tmp_path: Path, capability: Sintetica
) -> None:
    diretorio = instalar(tmp_path)

    relatorio = CapabilityHarness(diretorio, capability).rodar(CASOS)

    assert relatorio.ok, relatorio.resumo()
    assert relatorio.casos_executados == 2
    assert (Path(capability.permissions.filesystem[0]) / "nota.txt").is_file()


def test_ensaio_nao_escreve_o_que_a_execucao_escreve(
    tmp_path: Path, capability: Sintetica
) -> None:
    """`plan.md` §9: o ensaio registra o que faria e não faz."""
    harness = CapabilityHarness(instalar(tmp_path), capability)
    alvo = Path(capability.permissions.filesystem[0]) / "nota.txt"

    ensaio = harness.ensaiar(CASOS[0])

    assert ensaio.executado is False
    assert not alvo.exists()

    harness.executar(CASOS[0])
    assert alvo.read_text(encoding="utf-8") == "abc"


# --------------------------------------------------------------------------- #
# Reprovação — cada verificação vista falhando
# --------------------------------------------------------------------------- #


def problemas(relatorio: Relatorio, *, avisos: bool = False) -> list[str]:
    fonte = relatorio.avisos if avisos else relatorio.erros
    return sorted(p.campo for p in fonte)


def test_tool_no_codigo_e_ausente_do_manifest_e_erro(
    tmp_path: Path, capability: Sintetica
) -> None:
    """Catálogo incompleto faz `resolve()` decidir com informação errada."""
    diretorio = instalar(tmp_path)
    dados = yaml.safe_load((diretorio / "manifest.yaml").read_text(encoding="utf-8"))
    dados["tools"] = [t for t in dados["tools"] if t["name"] != "falar"]
    (diretorio / "manifest.yaml").write_text(
        yaml.safe_dump(dados, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    relatorio = CapabilityHarness(diretorio, capability).verificar()

    assert problemas(relatorio) == ["tools.falar"]


def test_schema_do_manifest_divergente_do_codigo_e_erro(
    tmp_path: Path, capability: Sintetica
) -> None:
    """O Chief AI monta a chamada pelo schema do manifest; divergir é chamada errada."""
    diretorio = instalar(tmp_path)
    dados = yaml.safe_load((diretorio / "manifest.yaml").read_text(encoding="utf-8"))
    for spec in dados["tools"]:
        if spec["name"] == "gravar":
            spec["input_schema"]["properties"]["nome"]["type"] = "integer"
    (diretorio / "manifest.yaml").write_text(
        yaml.safe_dump(dados, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    relatorio = CapabilityHarness(diretorio, capability).verificar()

    assert problemas(relatorio) == ["tools.gravar"]
    assert "render_manifest_yaml" in relatorio.resumo()


def test_permissao_exigida_e_nao_concedida_e_erro(
    tmp_path: Path, capability: Sintetica
) -> None:
    """A tool exige o host, o manifest não concede: o kernel negaria na 1ª execução."""
    diretorio = instalar(
        tmp_path, permissions=CapabilityPermissions(filesystem=["/mnt/dados"])
    )

    relatorio = CapabilityHarness(diretorio, capability).verificar()

    assert problemas(relatorio) == ["permissions.network"]
    assert "api.exemplo.com" in relatorio.resumo()


def test_identidade_divergente_entre_manifest_e_classe_e_erro(
    tmp_path: Path, capability: Sintetica
) -> None:
    diretorio = instalar(tmp_path, ajustar={"version": "9.9.9"})

    relatorio = CapabilityHarness(diretorio, capability).verificar()

    assert problemas(relatorio) == ["version"]


def test_entrypoint_que_nao_importa_e_erro(
    tmp_path: Path, capability: Sintetica
) -> None:
    diretorio = instalar(tmp_path, ajustar={"entrypoint": "modulo.que.nao.existe:main"})

    relatorio = CapabilityHarness(diretorio, capability).verificar()

    assert problemas(relatorio) == ["entrypoint"]


def test_entrypoint_sem_o_atributo_e_erro(
    tmp_path: Path, capability: Sintetica
) -> None:
    diretorio = instalar(
        tmp_path,
        ajustar={"entrypoint": "tests.unit.test_capability_sdk_harness:nao_existe"},
    )

    relatorio = CapabilityHarness(diretorio, capability).verificar()

    assert problemas(relatorio) == ["entrypoint"]


def test_capability_sem_tests_nao_passa(tmp_path: Path, capability: Sintetica) -> None:
    """`plan-scheme.md`: sem `tests/` não passa do Gate 2."""
    diretorio = instalar(tmp_path, com_tests=False)

    relatorio = CapabilityHarness(diretorio, capability).verificar()

    assert problemas(relatorio) == ["tests/"]


def test_manifest_invalido_vira_erro_em_vez_de_explodir(
    tmp_path: Path, capability: Sintetica
) -> None:
    """O harness relata; quem levanta é `carregar_arquivos` para quem o chama direto."""
    diretorio = instalar(tmp_path)
    (diretorio / "manifest.yaml").write_text("name: [", encoding="utf-8")

    relatorio = CapabilityHarness(diretorio, capability).verificar()

    assert problemas(relatorio) == ["manifest.yaml"]


def test_caso_com_saida_diferente_da_esperada_reprova(
    tmp_path: Path, capability: Sintetica
) -> None:
    diretorio = instalar(tmp_path)
    caso = CasoDeTool(tool="falar", arguments={"texto": "oi"}, espera={"texto": "tchau"})

    relatorio = CapabilityHarness(diretorio, capability).rodar([caso])

    assert not relatorio.ok
    assert problemas(relatorio) == ["tools.falar"]
    assert "tchau" in relatorio.resumo()


def test_tool_que_levanta_vira_erro_nomeando_a_tool(
    tmp_path: Path, capability: Sintetica
) -> None:
    """Sem isto, o pytest mostraria um traceback sem dizer qual caso o produziu."""
    diretorio = instalar(tmp_path)
    caso = CasoDeTool(tool="gravar", arguments={"nome": "sub/dir/nota.txt"})

    relatorio = CapabilityHarness(diretorio, capability).rodar([caso])

    assert not relatorio.ok
    assert problemas(relatorio) == ["tools.gravar"]


def test_verificacao_reprovada_nao_executa_caso_nenhum(
    tmp_path: Path, capability: Sintetica
) -> None:
    """Executar capability com contrato quebrado é rodar o que não foi aprovado."""
    diretorio = instalar(tmp_path, com_tests=False)

    relatorio = CapabilityHarness(diretorio, capability).rodar(CASOS)

    assert not relatorio.ok
    assert relatorio.casos_executados == 0


# --------------------------------------------------------------------------- #
# Avisos — o que o dono precisa ver e pode aceitar
# --------------------------------------------------------------------------- #


def test_host_concedido_e_nao_usado_e_aviso(
    tmp_path: Path, capability: Sintetica
) -> None:
    """Escopo mínimo é aceite da v2 (`plan.md` §14), não erro de contrato."""
    diretorio = instalar(
        tmp_path,
        permissions=CapabilityPermissions(
            network=["api.exemplo.com", "sobrando.exemplo.com"]
        ),
    )

    relatorio = CapabilityHarness(diretorio, capability).verificar()

    assert relatorio.ok
    assert problemas(relatorio, avisos=True) == ["permissions.network"]
    assert "sobrando.exemplo.com" in relatorio.resumo()


def test_active_sem_approved_commit_e_aviso(
    tmp_path: Path, capability: Sintetica
) -> None:
    diretorio = instalar(tmp_path, ajustar={"status": CapabilityStatus.ACTIVE.value})

    relatorio = CapabilityHarness(diretorio, capability).verificar()

    assert relatorio.ok
    assert problemas(relatorio, avisos=True) == ["approved_commit"]


def test_falta_de_docs_e_aviso(tmp_path: Path, capability: Sintetica) -> None:
    diretorio = instalar(tmp_path, com_docs=False)

    relatorio = CapabilityHarness(diretorio, capability).verificar()

    assert relatorio.ok
    assert problemas(relatorio, avisos=True) == ["docs/README.md"]


def test_tool_sem_caso_de_teste_e_aviso(
    tmp_path: Path, capability: Sintetica
) -> None:
    diretorio = instalar(tmp_path)

    relatorio = CapabilityHarness(diretorio, capability).rodar([CASOS[0]])

    assert relatorio.ok
    assert problemas(relatorio, avisos=True) == ["tools.falar"]


# --------------------------------------------------------------------------- #
# Aceite da fatia: a capability de exemplo
# --------------------------------------------------------------------------- #


def sonda_fixa(host: str, porta: int) -> bool:
    """Sonda determinística: a suíte não toca a rede."""
    return True


def test_capability_de_exemplo_passa_pelo_harness(tmp_path: Path) -> None:
    """O molde das capabilities da v2 cumpre o contrato que o SDK exige."""
    concessao = CapabilityPermissions(
        network=[exemplo.HOST_NAS], filesystem=[str(tmp_path)]
    )
    nas = exemplo.NasArquivos(concessao, sonda=sonda_fixa)
    casos = (
        CasoDeTool(
            tool="nas_gravar",
            arguments={"nome": "relatorio.txt", "conteudo": "linha 1\n"},
            espera={"bytes": 8},
        ),
        CasoDeTool(tool="nas_listar", arguments={}, espera={"total": 1}),
        CasoDeTool(tool="nas_status", arguments={}, espera={"online": True}),
    )

    relatorio = CapabilityHarness(exemplo.DIRETORIO, nas).rodar(casos)

    assert relatorio.ok, relatorio.resumo()
    assert relatorio.casos_executados == 3
    assert relatorio.avisos == ()
