"""Teste da capability `filesystem`.

`plan-scheme.md`: uma capability sem `tests/` não passa do Gate 2, e o resultado
deste arquivo é anexo obrigatório do gate (`plan.md` §8).

O corpo segue o contrato de teste do SDK, igual ao de `exemplo_nas`: monta a
capability com uma concessão apontada para `tmp_path`, lista os casos que ela
promete atender e manda o harness rodar. O harness confere manifest, catálogo,
permissões e layout, ensaia cada caso em `dry_run` provando que nada foi escrito,
e só então executa.

A concessão do teste **não** é a do manifest, e isso é de propósito: o manifest
concede as pastas de trabalho do dono, que só existem na máquina dele. O que o
harness confere contra o manifest é a *declaração*; o que ele executa roda na
concessão de teste.

Os casos são encadeados de propósito — `fs_criar_pasta` prepara a pasta que
`fs_escrever` usa, e assim por diante. Um caso preparando o outro é mais honesto
do que uma fixture que planta o arquivo sem passar pela tool: o que se quer provar
é que a sequência que o Chief AI vai montar funciona.

Nenhuma linha aqui toca disco fora de `tmp_path`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from capabilities.filesystem.backend.handlers import DIRETORIO, SistemaDeArquivos
from packages.capabilities import (
    CapabilityHarness,
    CasoDeTool,
    EntradaInvalida,
    PermissaoNaoDeclarada,
)
from packages.shared.contracts import CapabilityPermissions

#: `"linha 1\n"` são 8 bytes porque a capability grava com `newline=""` — sem
#: isso o Windows traduziria `\n` para `\r\n` e o mesmo texto teria dois tamanhos
#: dependendo do sistema, o que faria este número ser um teste de plataforma.
TEXTO = "linha 1\n"
BYTES_TEXTO = 8

#: A sequência que a capability promete atender, do zero até o arquivo apagado.
CASOS = (
    CasoDeTool(
        tool="fs_criar_pasta",
        arguments={"caminho": "docs"},
        espera={"criado": True},
        descricao="cria a pasta de trabalho dentro da raiz concedida",
    ),
    CasoDeTool(
        tool="fs_escrever",
        arguments={"caminho": "docs/nota.txt", "conteudo": TEXTO},
        espera={"bytes": BYTES_TEXTO, "criado": True},
        descricao="grava um arquivo novo",
    ),
    CasoDeTool(
        tool="fs_ler",
        arguments={"caminho": "docs/nota.txt"},
        espera={"conteudo": TEXTO, "bytes": BYTES_TEXTO},
        descricao="lê de volta o que acabou de ser gravado",
    ),
    CasoDeTool(
        tool="fs_listar",
        arguments={"caminho": "docs"},
        espera={"total": 1, "truncado": False},
        descricao="lista a pasta com o único arquivo",
    ),
    CasoDeTool(
        tool="fs_copiar",
        arguments={"origem": "docs/nota.txt", "destino": "docs/copia.txt"},
        espera={"arquivos": 1},
        descricao="copia o arquivo dentro da mesma raiz",
    ),
    CasoDeTool(
        tool="fs_mover",
        arguments={"origem": "docs/copia.txt", "destino": "docs/movida.txt"},
        descricao="renomeia a cópia",
    ),
    CasoDeTool(
        tool="fs_apagar",
        arguments={"caminho": "docs/movida.txt"},
        espera={"apagados": 1, "ausente": False},
        descricao="apaga o arquivo movido",
    ),
)


@pytest.fixture
def concessao(tmp_path: Path) -> CapabilityPermissions:
    """Duas raízes: a de trabalho e uma segunda, para provar que ela é alcançável."""
    segunda = tmp_path / "segunda"
    segunda.mkdir()
    return CapabilityPermissions(
        network=[], filesystem=[str(tmp_path / "trabalho"), str(segunda)], process=False
    )


@pytest.fixture
def capability(concessao: CapabilityPermissions) -> SistemaDeArquivos:
    Path(concessao.filesystem[0]).mkdir(parents=True, exist_ok=True)
    return SistemaDeArquivos(concessao)


def test_a_capability_passa_pelo_harness(capability: SistemaDeArquivos) -> None:
    """O aceite: manifest, catálogo, permissões, layout, dry_run e os sete casos."""
    relatorio = CapabilityHarness(DIRETORIO, capability).rodar(CASOS)

    assert relatorio.ok, relatorio.resumo()
    assert relatorio.casos_executados == len(CASOS)


def test_escrever_e_ler_fecham_o_ciclo(
    capability: SistemaDeArquivos, concessao: CapabilityPermissions
) -> None:
    """A gravação chega ao disco de verdade, no lugar concedido."""
    capability.call("fs_escrever", {"caminho": "sub/nota.md", "conteudo": "conteúdo"})

    destino = Path(concessao.filesystem[0]) / "sub" / "nota.md"
    assert destino.read_text(encoding="utf-8") == "conteúdo"
    assert capability.call("fs_ler", {"caminho": "sub/nota.md"})["conteudo"] == (
        "conteúdo"
    )


def test_anexar_nao_substitui(capability: SistemaDeArquivos) -> None:
    capability.call("fs_escrever", {"caminho": "log.txt", "conteudo": "a\n"})
    capability.call(
        "fs_escrever", {"caminho": "log.txt", "conteudo": "b\n", "anexar": True}
    )

    assert capability.call("fs_ler", {"caminho": "log.txt"})["conteudo"] == "a\nb\n"


def test_segunda_raiz_concedida_e_alcancavel_por_caminho_absoluto(
    capability: SistemaDeArquivos, concessao: CapabilityPermissions
) -> None:
    """Conceder duas pastas tem de conceder duas pastas, não uma."""
    segunda = Path(concessao.filesystem[1]) / "fora_da_raiz.txt"

    saida = capability.call(
        "fs_escrever", {"caminho": str(segunda), "conteudo": "x"}
    )

    assert saida["criado"] is True
    assert segunda.read_text(encoding="utf-8") == "x"


def test_caminho_absoluto_fora_da_concessao_e_negado(
    capability: SistemaDeArquivos, tmp_path: Path
) -> None:
    """`tmp_path` não é raiz concedida — só as duas subpastas dela são."""
    with pytest.raises(PermissaoNaoDeclarada) as exc:
        capability.call(
            "fs_escrever", {"caminho": str(tmp_path / "vazado.txt"), "conteudo": "x"}
        )

    assert exc.value.kind == "filesystem"
    assert exc.value.tool == "fs_escrever"


def test_escape_com_dotdot_morre_no_schema(capability: SistemaDeArquivos) -> None:
    """O `..` é recusado pelo modelo de entrada, antes de qualquer I/O."""
    with pytest.raises(EntradaInvalida) as exc:
        capability.call("fs_ler", {"caminho": "../fora.txt"})

    assert [p.campo for p in exc.value.problemas] == ["caminho"]


def test_arquivo_inexistente_vira_erro_do_sdk(capability: SistemaDeArquivos) -> None:
    """`FileNotFoundError` cru nunca sobe: vira `EntradaInvalida` com o campo."""
    with pytest.raises(EntradaInvalida) as exc:
        capability.call("fs_ler", {"caminho": "nao_existe.txt"})

    assert [p.campo for p in exc.value.problemas] == ["caminho"]


def test_ler_pasta_como_arquivo_e_recusado(capability: SistemaDeArquivos) -> None:
    capability.call("fs_criar_pasta", {"caminho": "uma_pasta"})

    with pytest.raises(EntradaInvalida):
        capability.call("fs_ler", {"caminho": "uma_pasta"})


def test_arquivo_acima_do_teto_de_leitura_e_recusado(
    capability: SistemaDeArquivos,
) -> None:
    """Recusar é melhor que truncar: pedaço de arquivo lido como arquivo mente."""
    capability.call("fs_escrever", {"caminho": "grande.txt", "conteudo": "x" * 100})

    with pytest.raises(EntradaInvalida) as exc:
        capability.call("fs_ler", {"caminho": "grande.txt", "max_bytes": 10})

    assert [p.campo for p in exc.value.problemas] == ["max_bytes"]


def test_listar_pasta_inexistente_devolve_vazio(
    capability: SistemaDeArquivos,
) -> None:
    """Pasta não montada é estado do ambiente, não falha da tool."""
    saida = capability.call("fs_listar", {"caminho": "nunca_criada"})

    assert saida == {"entradas": [], "total": 0, "truncado": False}


def test_listar_recursivo_desce_nas_subpastas(capability: SistemaDeArquivos) -> None:
    capability.call("fs_escrever", {"caminho": "a/b/c.txt", "conteudo": "x"})

    raso = capability.call("fs_listar", {"caminho": "a"})
    fundo = capability.call("fs_listar", {"caminho": "a", "recursivo": True})

    assert [e["nome"] for e in raso["entradas"]] == ["b"]
    assert [e["nome"] for e in fundo["entradas"]] == ["b", "c.txt"]


def test_listar_respeita_o_limite_e_marca_truncado(
    capability: SistemaDeArquivos,
) -> None:
    for i in range(5):
        capability.call("fs_escrever", {"caminho": f"muitos/{i}.txt", "conteudo": "x"})

    saida = capability.call("fs_listar", {"caminho": "muitos", "limite": 2})

    assert saida["total"] == 2
    assert saida["truncado"] is True


def test_destino_existente_exige_sobrescrever(capability: SistemaDeArquivos) -> None:
    capability.call("fs_escrever", {"caminho": "um.txt", "conteudo": "1"})
    capability.call("fs_escrever", {"caminho": "dois.txt", "conteudo": "2"})

    with pytest.raises(EntradaInvalida) as exc:
        capability.call("fs_copiar", {"origem": "um.txt", "destino": "dois.txt"})
    assert [p.campo for p in exc.value.problemas] == ["destino"]

    capability.call(
        "fs_copiar",
        {"origem": "um.txt", "destino": "dois.txt", "sobrescrever": True},
    )
    assert capability.call("fs_ler", {"caminho": "dois.txt"})["conteudo"] == "1"


def test_copiar_pasta_conta_os_arquivos_de_dentro(
    capability: SistemaDeArquivos,
) -> None:
    capability.call("fs_escrever", {"caminho": "arv/a.txt", "conteudo": "a"})
    capability.call("fs_escrever", {"caminho": "arv/sub/b.txt", "conteudo": "b"})

    saida = capability.call("fs_copiar", {"origem": "arv", "destino": "arv_copia"})

    assert saida["arquivos"] == 2
    assert capability.call("fs_ler", {"caminho": "arv_copia/sub/b.txt"})[
        "conteudo"
    ] == "b"


def test_mover_some_com_a_origem(capability: SistemaDeArquivos) -> None:
    capability.call("fs_escrever", {"caminho": "antes.txt", "conteudo": "x"})

    capability.call("fs_mover", {"origem": "antes.txt", "destino": "depois.txt"})

    with pytest.raises(EntradaInvalida):
        capability.call("fs_ler", {"caminho": "antes.txt"})
    assert capability.call("fs_ler", {"caminho": "depois.txt"})["conteudo"] == "x"


def test_apagar_pasta_com_conteudo_exige_recursivo(
    capability: SistemaDeArquivos,
) -> None:
    """Apagar é o único efeito daqui que não tem desfazer. Ele pergunta duas vezes."""
    capability.call("fs_escrever", {"caminho": "cheia/x.txt", "conteudo": "x"})

    with pytest.raises(EntradaInvalida) as exc:
        capability.call("fs_apagar", {"caminho": "cheia"})
    assert [p.campo for p in exc.value.problemas] == ["recursivo"]

    saida = capability.call("fs_apagar", {"caminho": "cheia", "recursivo": True})
    assert saida["apagados"] == 1


def test_apagar_ausente_e_erro_por_padrao_e_silencioso_sob_pedido(
    capability: SistemaDeArquivos,
) -> None:
    with pytest.raises(EntradaInvalida):
        capability.call("fs_apagar", {"caminho": "fantasma.txt"})

    saida = capability.call(
        "fs_apagar", {"caminho": "fantasma.txt", "ausente_ok": True}
    )
    assert saida == {
        "caminho": saida["caminho"],
        "apagados": 0,
        "ausente": True,
    }


def test_apagar_exige_aprovacao_do_dono() -> None:
    """`requires_approval` é o que o kernel lê antes de executar (`plan.md` §9)."""
    specs = {s.name: s for s in SistemaDeArquivos.tool_specs()}

    assert specs["fs_apagar"].requires_approval is True
    assert specs["fs_ler"].requires_approval is False


def test_sem_concessao_de_filesystem_nao_ha_raiz() -> None:
    """Capability construída sem manifest não toca em lugar nenhum."""
    with pytest.raises(PermissaoNaoDeclarada) as exc:
        SistemaDeArquivos().call("fs_listar", {})

    assert exc.value.kind == "filesystem"
