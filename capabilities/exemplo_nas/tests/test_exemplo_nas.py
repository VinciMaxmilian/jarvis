"""Teste da capability `exemplo_nas` — o molde do que toda capability tem de ter.

`plan-scheme.md`: uma capability sem `tests/` não passa do Gate 2, e o resultado
deste arquivo é anexo obrigatório do gate (`plan.md` §8).

O corpo do teste é o contrato de teste do SDK: monta a capability com uma
concessão apontada para `tmp_path`, lista os casos que ela promete atender e
manda o harness rodar. O harness confere manifest, catálogo, permissões, layout,
ensaia cada caso em `dry_run` provando que nada foi escrito, e só então executa.

A concessão do teste **não** é a do manifest, e isso é de propósito: o manifest
concede `/mnt/nas/documentos`, que só existe na máquina do dono. O que o harness
confere contra o manifest é a *declaração* (o que as tools exigem, o catálogo, a
identidade); o que ele executa roda na concessão de teste. As duas conferências
são a mesma capability vista de dois lugares.

Nenhuma linha aqui toca a rede: a sonda do NAS é injetada.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from capabilities.exemplo_nas.backend.handlers import (
    DIRETORIO,
    HOST_NAS,
    PORTA_SMB,
    NasArquivos,
    Sonda,
)
from packages.capabilities import (
    CapabilityHarness,
    CasoDeTool,
    EntradaInvalida,
    PermissaoNaoDeclarada,
)
from packages.shared.contracts import CapabilityPermissions

#: Os casos que a capability promete atender. Ordem importa: `nas_gravar` cria o
#: arquivo que `nas_listar` conta — um caso preparando o outro é mais honesto do
#: que uma fixture que planta o arquivo sem passar pela tool.
CASOS = (
    CasoDeTool(
        tool="nas_gravar",
        arguments={"nome": "relatorio.txt", "conteudo": "linha 1\n"},
        espera={"bytes": 8},
        descricao="grava um arquivo na raiz concedida",
    ),
    CasoDeTool(
        tool="nas_listar",
        arguments={},
        espera={"total": 1},
        descricao="lista o que acabou de ser gravado",
    ),
    CasoDeTool(
        tool="nas_status",
        arguments={},
        espera={"host": HOST_NAS, "porta": PORTA_SMB, "online": True},
        descricao="confere o NAS com a sonda injetada",
    ),
)


def sonda_fixa(*, responde: bool) -> Sonda:
    """Sonda determinística. A suíte roda sem rede (`plan-execution.md` §1.0b)."""

    def sonda(host: str, porta: int) -> bool:
        return responde

    return sonda


@pytest.fixture
def concessao(tmp_path: Path) -> CapabilityPermissions:
    """A concessão do teste: a raiz vira `tmp_path`, a rede continua a do manifest."""
    return CapabilityPermissions(
        network=[HOST_NAS], filesystem=[str(tmp_path)], process=False
    )


@pytest.fixture
def capability(concessao: CapabilityPermissions) -> NasArquivos:
    return NasArquivos(concessao, sonda=sonda_fixa(responde=True))


def test_a_capability_passa_pelo_harness(capability: NasArquivos) -> None:
    """O aceite: manifest, catálogo, permissões, layout, dry_run e os três casos."""
    relatorio = CapabilityHarness(DIRETORIO, capability).rodar(CASOS)

    assert relatorio.ok, relatorio.resumo()
    assert relatorio.casos_executados == len(CASOS)


def test_gravar_escreve_de_verdade_na_raiz_concedida(
    capability: NasArquivos, tmp_path: Path
) -> None:
    saida = capability.call(
        "nas_gravar", {"nome": "nota.md", "conteudo": "conteúdo"}
    )

    assert (tmp_path / "nota.md").read_text(encoding="utf-8") == "conteúdo"
    assert saida["caminho"] == str(tmp_path / "nota.md")


def test_nome_com_escape_de_diretorio_e_recusado(capability: NasArquivos) -> None:
    """O `..` morre no schema, antes de o guarda do kernel precisar existir."""
    with pytest.raises(EntradaInvalida) as exc:
        capability.call("nas_gravar", {"nome": "../fora.txt", "conteudo": "x"})

    assert [p.campo for p in exc.value.problemas] == ["nome"]


def test_sem_concessao_de_filesystem_nao_ha_raiz() -> None:
    """Capability construída sem manifest não escreve em lugar nenhum."""
    with pytest.raises(PermissaoNaoDeclarada) as exc:
        NasArquivos().call("nas_listar", {})

    assert exc.value.kind == "filesystem"
