"""Teste da capability `shell`.

`plan-scheme.md`: uma capability sem `tests/` não passa do Gate 2, e o resultado
deste arquivo é anexo obrigatório do gate (`plan.md` §8).

Duas metades, com propósitos diferentes:

- **Com executor injetado.** É a maior parte. O executor falso devolve resultado
  roteirizado, o que torna os casos determinísticos e independentes do `PATH` da
  máquina. É assim que o harness roda: sem iniciar processo nenhum.
- **Com o executor real.** Um único teste, marcado para pular quando `python` não
  está no `PATH`. Ele existe porque tudo que é falso passa; o que prova que
  `subprocess` foi chamado certo é `subprocess` sendo chamado.

O que este arquivo mais confere é **negação**: fora da allowlist, `cwd` fora da
concessão, programa com caminho no nome, timeout. Numa capability que executa
programa externo, o teste do caminho feliz é o menos interessante.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from capabilities.shell.backend.handlers import (
    DIRETORIO,
    PERMITIDOS_PADRAO,
    Resultado,
    Shell,
    carregar_allowlist,
)
from packages.capabilities import (
    CapabilityHarness,
    CasoDeTool,
    EntradaInvalida,
    PermissaoNaoDeclarada,
)
from packages.shared.contracts import CapabilityPermissions

#: A allowlist de teste. Curta para que "está na lista" e "não está" sejam duas
#: asserções e não uma coincidência.
PERMITIDOS = ("python", "git")

CASOS = (
    CasoDeTool(
        tool="shell_listar_permitidos",
        arguments={},
        espera={"permitidos": list(PERMITIDOS), "total": 2},
        descricao="publica a allowlist sem iniciar processo nenhum",
    ),
    CasoDeTool(
        tool="shell_executar",
        arguments={"programa": "git", "argumentos": ["--version"]},
        espera={"exit_code": 0, "expirou": False, "truncado": False},
        descricao="executa um programa da allowlist e devolve o código de saída",
    ),
)


def executor_fixo(
    *,
    exit_code: int | None = 0,
    stdout: str = "ok\n",
    stderr: str = "",
    expirou: bool = False,
) -> object:
    """Executor determinístico, no molde da sonda injetada de `exemplo_nas`."""

    def executor(comando: Sequence[str], *, cwd: str, timeout: float) -> Resultado:
        return Resultado(
            exit_code=exit_code, stdout=stdout, stderr=stderr, expirou=expirou
        )

    return executor


@pytest.fixture
def concessao(tmp_path: Path) -> CapabilityPermissions:
    trabalho = tmp_path / "trabalho"
    trabalho.mkdir()
    return CapabilityPermissions(
        network=[], filesystem=[str(trabalho)], process=True
    )


@pytest.fixture
def capability(concessao: CapabilityPermissions) -> Shell:
    return Shell(concessao, permitidos=PERMITIDOS, executor=executor_fixo())


def test_a_capability_passa_pelo_harness(capability: Shell) -> None:
    """O aceite: manifest, catálogo, permissões, layout, dry_run e os dois casos."""
    relatorio = CapabilityHarness(DIRETORIO, capability).rodar(CASOS)

    assert relatorio.ok, relatorio.resumo()
    assert relatorio.casos_executados == len(CASOS)


def test_programa_fora_da_allowlist_e_negado(capability: Shell) -> None:
    """Negação de escopo, não erro de argumento: o comando está bem formado."""
    with pytest.raises(PermissaoNaoDeclarada) as exc:
        capability.call("shell_executar", {"programa": "curl", "argumentos": ["x"]})

    assert exc.value.kind == "process"
    assert exc.value.target == "curl"
    assert exc.value.tool == "shell_executar"


def test_allowlist_ignora_caixa(capability: Shell) -> None:
    """`GIT` e `git` são o mesmo programa em Windows; a lista não pode discordar."""
    saida = capability.call("shell_executar", {"programa": "GIT"})

    assert saida["exit_code"] == 0


@pytest.mark.parametrize(
    "programa",
    ["/bin/sh", "..\\evil", "C:/Windows/System32/cmd.exe", "sub/dir/git"],
)
def test_programa_com_caminho_morre_no_schema(
    capability: Shell, programa: str
) -> None:
    """Aceitar caminho faria a allowlist virar decoração: bastaria gravar um
    arquivo com nome permitido em qualquer lugar."""
    with pytest.raises(EntradaInvalida) as exc:
        capability.call("shell_executar", {"programa": programa})

    assert [p.campo for p in exc.value.problemas] == ["programa"]


def test_argumento_com_metacaractere_e_texto_literal(capability: Shell) -> None:
    """`;` e `|` não são operadores aqui — não há shell para interpretá-los.

    O teste é sobre o que **não** acontece: o argumento passa pela validação e
    chega ao executor como um item da lista, sem virar segundo comando.
    """
    recebido: list[list[str]] = []

    def espiao(comando: Sequence[str], *, cwd: str, timeout: float) -> Resultado:
        recebido.append(list(comando))
        return Resultado(exit_code=0, stdout="", stderr="")

    shell = Shell(
        capability.permissions, permitidos=PERMITIDOS, executor=espiao
    )
    shell.call(
        "shell_executar",
        {"programa": "git", "argumentos": ["status", "; rm -rf /", "| cat"]},
    )

    assert recebido[0][1:] == ["status", "; rm -rf /", "| cat"]


def test_exit_code_diferente_de_zero_nao_e_falha_da_tool(
    concessao: CapabilityPermissions,
) -> None:
    """O comando rodou e disse que falhou. Isso é resposta, não exceção."""
    shell = Shell(
        concessao,
        permitidos=PERMITIDOS,
        executor=executor_fixo(exit_code=2, stdout="", stderr="boom\n"),
    )

    saida = shell.call("shell_executar", {"programa": "git"})

    assert saida["exit_code"] == 2
    assert saida["stderr"] == "boom\n"
    assert saida["expirou"] is False


def test_timeout_volta_como_resultado_e_nao_como_excecao(
    concessao: CapabilityPermissions,
) -> None:
    shell = Shell(
        concessao,
        permitidos=PERMITIDOS,
        executor=executor_fixo(exit_code=None, expirou=True, stdout=""),
    )

    saida = shell.call("shell_executar", {"programa": "git", "timeout": 1})

    assert saida["expirou"] is True
    assert saida["exit_code"] is None


def test_saida_gigante_e_cortada_e_marcada(
    concessao: CapabilityPermissions,
) -> None:
    shell = Shell(
        concessao,
        permitidos=PERMITIDOS,
        executor=executor_fixo(stdout="x" * (200 * 1024)),
    )

    saida = shell.call("shell_executar", {"programa": "git"})

    assert saida["truncado"] is True
    assert len(saida["stdout"]) < 200 * 1024


def test_timeout_acima_do_teto_morre_no_schema(capability: Shell) -> None:
    with pytest.raises(EntradaInvalida) as exc:
        capability.call("shell_executar", {"programa": "git", "timeout": 10_000})

    assert [p.campo for p in exc.value.problemas] == ["timeout"]


def test_cwd_fora_da_concessao_e_negado(capability: Shell, tmp_path: Path) -> None:
    with pytest.raises(PermissaoNaoDeclarada) as exc:
        capability.call(
            "shell_executar", {"programa": "git", "cwd": str(tmp_path / "fora")}
        )

    assert exc.value.kind == "filesystem"


def test_cwd_com_dotdot_morre_no_schema(capability: Shell) -> None:
    with pytest.raises(EntradaInvalida) as exc:
        capability.call("shell_executar", {"programa": "git", "cwd": "../fora"})

    assert [p.campo for p in exc.value.problemas] == ["cwd"]


def test_cwd_inexistente_dentro_da_concessao_e_erro_de_argumento(
    capability: Shell,
) -> None:
    """Dentro do escopo e ainda assim impossível: é o argumento que está errado."""
    with pytest.raises(EntradaInvalida) as exc:
        capability.call("shell_executar", {"programa": "git", "cwd": "nao_existe"})

    assert [p.campo for p in exc.value.problemas] == ["cwd"]


def test_listar_permitidos_nao_declara_processo() -> None:
    """A tool que só lê a lista não pode exigir permissão de iniciar processo."""
    por_nome = {d.name: d for d in Shell.declarations()}

    assert por_nome["shell_listar_permitidos"].requires.process is False
    assert por_nome["shell_executar"].requires.process is True
    assert por_nome["shell_executar"].requires_approval is True


def test_allowlist_do_disco_e_a_que_vale() -> None:
    """`allowlist.yaml` é do dono: se ele mexer, é o que a capability passa a usar."""
    assert carregar_allowlist(DIRETORIO) == PERMITIDOS_PADRAO


def test_allowlist_do_disco_le_lista_e_mapa(tmp_path: Path) -> None:
    (tmp_path / "allowlist.yaml").write_text("- git\n- ls\n", encoding="utf-8")
    assert carregar_allowlist(tmp_path) == ("git", "ls")

    (tmp_path / "allowlist.yaml").write_text(
        "permitidos:\n  - git\n", encoding="utf-8"
    )
    assert carregar_allowlist(tmp_path) == ("git",)


def test_allowlist_torta_e_erro_e_nao_volta_para_a_padrao(tmp_path: Path) -> None:
    """Cair na padrão em silêncio seria uma restrição que o dono acha que aplicou."""
    (tmp_path / "allowlist.yaml").write_text("git\n", encoding="utf-8")

    with pytest.raises(ValueError, match="lista de nomes"):
        carregar_allowlist(tmp_path)


def test_allowlist_vazia_nao_deixa_executar_nada(
    concessao: CapabilityPermissions,
) -> None:
    shell = Shell(concessao, permitidos=(), executor=executor_fixo())

    with pytest.raises(PermissaoNaoDeclarada):
        shell.call("shell_executar", {"programa": "git"})


def test_sem_manifest_o_sdk_nega_antes_de_o_handler_rodar() -> None:
    """`requires=process` mais manifest vazio: o SDK nega sem chamar o handler.

    A negação vem do próprio despacho (`Capability.call`), antes da allowlist e
    antes do `cwd` — é a aritmética de declaração que `plan.md` §8 chama de item 3
    do Gate 2 na sua forma barata.
    """
    with pytest.raises(PermissaoNaoDeclarada) as exc:
        Shell(permitidos=PERMITIDOS, executor=executor_fixo()).call(
            "shell_executar", {"programa": "git"}
        )

    assert exc.value.kind == "process"


def test_com_processo_concedido_e_sem_pasta_nao_ha_cwd() -> None:
    """Passada a barreira do SDK, falta a raiz de trabalho — e ela também é negação."""
    so_processo = CapabilityPermissions(network=[], filesystem=[], process=True)

    with pytest.raises(PermissaoNaoDeclarada) as exc:
        Shell(so_processo, permitidos=PERMITIDOS, executor=executor_fixo()).call(
            "shell_executar", {"programa": "git"}
        )

    assert exc.value.kind == "filesystem"


def test_programa_permitido_mas_ausente_do_path(
    concessao: CapabilityPermissions,
) -> None:
    """Na allowlist e fora do `PATH` é erro de argumento, com o nome do campo."""
    shell = Shell(
        concessao,
        permitidos=("programa_que_nao_existe_em_lugar_nenhum",),
        executor=executor_fixo(),
    )

    with pytest.raises(EntradaInvalida) as exc:
        shell.call(
            "shell_executar",
            {"programa": "programa_que_nao_existe_em_lugar_nenhum"},
        )

    assert [p.campo for p in exc.value.problemas] == ["programa"]


# --------------------------------------------------------------------------- #
# A metade que usa `subprocess` de verdade
# --------------------------------------------------------------------------- #


def test_executor_real_roda_um_processo(concessao: CapabilityPermissions) -> None:
    """Tudo que é falso passa. Isto prova que o `subprocess` foi chamado certo.

    Roda `python -c` — nada de rede, nada fora de `tmp_path`, e o `stdin` vai para
    `DEVNULL`, então o processo não tem como pendurar esperando entrada.
    """
    import shutil as _shutil

    if _shutil.which("python") is None:  # pragma: no cover — depende do PATH
        pytest.skip("python não está no PATH deste ambiente")

    shell = Shell(concessao, permitidos=("python",))
    saida = shell.call(
        "shell_executar",
        {"programa": "python", "argumentos": ["-c", "print('oi'); exit(3)"]},
    )

    assert saida["exit_code"] == 3
    assert saida["stdout"].strip() == "oi"
    assert saida["expirou"] is False
    assert saida["cwd"] == str(Path(concessao.filesystem[0]))
