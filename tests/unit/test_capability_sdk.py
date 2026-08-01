"""Declaração e despacho do Capability SDK.

O que estes testes fixam é o **contrato contra o qual a v3 vai gerar código**
(`plan.md` §8): como se declara uma tool, o que sai no catálogo, o que acontece
com argumento errado, o que acontece com permissão que ninguém concedeu e o que
`dry_run` faz. Contrato instável produz capability gerada quebrada — daí cada
regra ter um teste que a fixa, e não um comentário que a descreve.

Nada aqui toca disco, rede ou modelo.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from packages.capabilities import (
    Capability,
    DeclaracaoInvalida,
    Ensaio,
    EntradaInvalida,
    PermissaoNaoDeclarada,
    SaidaInvalida,
    ToolDesconhecida,
    ToolRequirements,
    entrypoint,
    especificacoes,
    tool,
)
from packages.shared.contracts import RUNTIME_PADRAO, CapabilityPermissions


class Entrada(BaseModel):
    texto: str
    vezes: int = 1


class Saida(BaseModel):
    resultado: str


class Eco(Capability):
    """Capability mínima e válida: um nome, uma versão, uma descrição, uma tool."""

    name = "eco"
    version = "0.1.0"
    description = "Repete o texto que recebe."
    trigger_intents = ("repetir texto",)
    runtime = "python"

    def __init__(self, permissions: CapabilityPermissions | None = None) -> None:
        super().__init__(permissions)
        self.chamadas = 0

    @tool(
        description="Repete o texto n vezes.",
        entrada=Entrada,
        saida=Saida,
        idempotent=True,
    )
    def eco_repetir(self, entrada: Entrada) -> Saida:
        self.chamadas += 1
        return Saida(resultado=entrada.texto * entrada.vezes)


class ComRede(Capability):
    """Capability cuja tool exige um host. Serve para exercitar a negação."""

    name = "com_rede"
    version = "0.1.0"
    description = "Fala com um host declarado."

    @tool(
        description="Busca algo no host.",
        entrada=Entrada,
        requires=ToolRequirements(network=("api.exemplo.com",)),
    )
    def buscar(self, entrada: Entrada) -> dict[str, str]:
        return {"host": "api.exemplo.com", "texto": entrada.texto}


# --------------------------------------------------------------------------- #
# Catálogo: o que a declaração publica
# --------------------------------------------------------------------------- #


def test_tool_spec_sai_da_classe_em_json_schema() -> None:
    """`input_schema` é JSON Schema — é o formato de tool do MCP (tools.md §7)."""
    (spec,) = Eco.tool_specs()

    assert spec.name == "eco_repetir"
    assert spec.description == "Repete o texto n vezes."
    assert spec.input_schema["type"] == "object"
    assert set(spec.input_schema["properties"]) == {"texto", "vezes"}
    assert spec.input_schema["required"] == ["texto"]
    assert spec.output_schema is not None
    assert spec.idempotent is True
    assert spec.requires_approval is False


def test_catalogo_sai_em_ordem_estavel() -> None:
    """Ordem do `vars()` mudaria o manifest gerado a cada edição do arquivo."""

    class Varias(Capability):
        name = "varias"
        version = "0.1.0"
        description = "Três tools fora de ordem."

        @tool(description="c", entrada=Entrada)
        def zeta(self, entrada: Entrada) -> dict[str, str]:
            return {}

        @tool(description="a", entrada=Entrada)
        def alfa(self, entrada: Entrada) -> dict[str, str]:
            return {}

        @tool(description="b", entrada=Entrada)
        def meio(self, entrada: Entrada) -> dict[str, str]:
            return {}

    assert [s.name for s in Varias.tool_specs()] == ["alfa", "meio", "zeta"]


def test_runtime_default_vem_do_contrato() -> None:
    """Somar runtime é do kernel; o SDK não fixa a lista."""

    class SemRuntime(Capability):
        name = "sem_runtime"
        version = "0.1.0"
        description = "Não declara runtime."

        @tool(description="x", entrada=Entrada)
        def x(self, entrada: Entrada) -> dict[str, str]:
            return {}

    assert SemRuntime.runtime == RUNTIME_PADRAO


def test_especificacoes_achata_varias_capabilities() -> None:
    nomes = [s.name for s in especificacoes([Eco, ComRede])]

    assert nomes == ["eco_repetir", "buscar"]


def test_requirements_e_a_uniao_do_que_as_tools_exigem() -> None:
    """É o escopo mínimo que o manifest precisa conceder."""
    assert ComRede.requirements().network == ("api.exemplo.com",)
    assert Eco.requirements().vazio is True


# --------------------------------------------------------------------------- #
# Despacho
# --------------------------------------------------------------------------- #


def test_call_valida_a_entrada_e_serializa_a_saida() -> None:
    eco = Eco()

    saida = eco.call("eco_repetir", {"texto": "ab", "vezes": 2})

    assert saida == {"resultado": "abab"}
    assert eco.chamadas == 1


def test_entrada_invalida_nomeia_o_campo() -> None:
    """Mensagem sem o nome do campo obriga a abrir o código para consertar."""
    with pytest.raises(EntradaInvalida) as exc:
        Eco().call("eco_repetir", {"vezes": "muitas"})

    campos = sorted(p.campo for p in exc.value.problemas)
    assert campos == ["texto", "vezes"]
    assert "texto" in str(exc.value)


def test_tool_desconhecida_lista_as_que_existem() -> None:
    with pytest.raises(ToolDesconhecida) as exc:
        Eco().call("eco_gritar", {})

    assert exc.value.disponiveis == ("eco_repetir",)
    assert "eco_repetir" in str(exc.value)


def test_saida_fora_do_modelo_declarado_e_recusada() -> None:
    """Saída fora do schema é o catálogo mentindo para o Chief AI."""

    class Mentirosa(Capability):
        name = "mentirosa"
        version = "0.1.0"
        description = "Declara Saida e devolve outra coisa."

        @tool(description="x", entrada=Entrada, saida=Saida)
        def mentir(self, entrada: Entrada) -> Saida:
            return "não é um modelo"  # type: ignore[return-value]

    with pytest.raises(SaidaInvalida):
        Mentirosa().call("mentir", {"texto": "x"})


def test_sem_modelo_de_saida_o_handler_tem_de_devolver_mapa() -> None:
    class SemModelo(Capability):
        name = "sem_modelo"
        version = "0.1.0"
        description = "Devolve valor solto."

        @tool(description="x", entrada=Entrada)
        def solta(self, entrada: Entrada) -> dict[str, str]:
            return 42  # type: ignore[return-value]

    with pytest.raises(SaidaInvalida) as exc:
        SemModelo().call("solta", {"texto": "x"})

    assert "mapa" in str(exc.value)


# --------------------------------------------------------------------------- #
# dry_run — `plan.md` §9: registra o que faria e não faz
# --------------------------------------------------------------------------- #


def test_dry_run_nao_chama_o_handler() -> None:
    eco = Eco()

    bruto = eco.call("eco_repetir", {"texto": "ab", "vezes": 2}, dry_run=True)

    ensaio = Ensaio.model_validate(bruto)
    assert ensaio.dry_run is True
    assert ensaio.executado is False
    assert ensaio.arguments == {"texto": "ab", "vezes": 2}
    assert eco.chamadas == 0


def test_dry_run_ainda_valida_a_entrada() -> None:
    """Ensaiar chamada malformada não informa nada sobre a chamada real."""
    with pytest.raises(EntradaInvalida):
        Eco().call("eco_repetir", {}, dry_run=True)


def test_dry_run_registra_o_que_a_tool_tocaria() -> None:
    ensaio = Ensaio.model_validate(
        ComRede(CapabilityPermissions(network=["api.exemplo.com"])).call(
            "buscar", {"texto": "x"}, dry_run=True
        )
    )

    assert ensaio.requires.network == ("api.exemplo.com",)


# --------------------------------------------------------------------------- #
# Permissão declarada — o SDK nega a contradição; o kernel nega a chamada
# --------------------------------------------------------------------------- #


def test_permissao_nao_declarada_e_negada_antes_do_handler() -> None:
    """A tool exige um host; o manifest não concedeu nada. Não roda."""
    with pytest.raises(PermissaoNaoDeclarada) as exc:
        ComRede().call("buscar", {"texto": "x"})

    assert exc.value.kind == "network"
    assert exc.value.target == "api.exemplo.com"
    assert exc.value.capability == "com_rede"
    assert exc.value.tool == "buscar"
    assert "permissions.network" in str(exc.value)


def test_permissao_declarada_deixa_a_tool_rodar() -> None:
    concedido = ComRede(CapabilityPermissions(network=["api.exemplo.com"]))

    assert concedido.call("buscar", {"texto": "x"})["host"] == "api.exemplo.com"


def test_host_concedido_casa_sem_diferenciar_maiuscula() -> None:
    concedido = ComRede(CapabilityPermissions(network=["API.Exemplo.COM"]))

    assert concedido.call("buscar", {"texto": "x"})["texto"] == "x"


def test_outro_host_concedido_nao_libera_o_exigido() -> None:
    with pytest.raises(PermissaoNaoDeclarada) as exc:
        ComRede(CapabilityPermissions(network=["outro.host"])).call(
            "buscar", {"texto": "x"}
        )

    assert exc.value.target == "api.exemplo.com"


def test_dry_run_tambem_respeita_a_concessao() -> None:
    """Ensaio de tool fora de escopo é ensaio do que nunca vai poder acontecer."""
    with pytest.raises(PermissaoNaoDeclarada):
        ComRede().call("buscar", {"texto": "x"}, dry_run=True)


def test_prefixo_de_caminho_nao_vaza_para_o_diretorio_vizinho() -> None:
    """`/dados/nas` não concede `/dados/nas_publico` — é outro diretório."""

    class GravaFixo(Capability):
        name = "grava_fixo"
        version = "0.1.0"
        description = "Escreve num caminho constante."

        @tool(
            description="x",
            entrada=Entrada,
            requires=ToolRequirements(filesystem=("/dados/nas_publico/a.txt",)),
        )
        def gravar(self, entrada: Entrada) -> dict[str, str]:
            return {}

    with pytest.raises(PermissaoNaoDeclarada) as exc:
        GravaFixo(CapabilityPermissions(filesystem=["/dados/nas"])).call(
            "gravar", {"texto": "x"}
        )

    assert exc.value.kind == "filesystem"


def test_caminho_dentro_da_raiz_concedida_passa() -> None:
    class GravaFixo(Capability):
        name = "grava_dentro"
        version = "0.1.0"
        description = "Escreve num caminho constante."

        @tool(
            description="x",
            entrada=Entrada,
            requires=ToolRequirements(filesystem=("/dados/nas/sub/a.txt",)),
        )
        def gravar(self, entrada: Entrada) -> dict[str, str]:
            return {"ok": "sim"}

    saida = GravaFixo(CapabilityPermissions(filesystem=["/dados/nas"])).call(
        "gravar", {"texto": "x"}
    )

    assert saida == {"ok": "sim"}


def test_subprocesso_exige_process_concedido() -> None:
    class RodaComando(Capability):
        name = "roda_comando"
        version = "0.1.0"
        description = "Inicia subprocesso."

        @tool(
            description="x",
            entrada=Entrada,
            requires=ToolRequirements(process=True),
        )
        def rodar(self, entrada: Entrada) -> dict[str, str]:
            return {"ok": "sim"}

    with pytest.raises(PermissaoNaoDeclarada) as exc:
        RodaComando().call("rodar", {"texto": "x"})
    assert exc.value.kind == "process"

    concedida = RodaComando(CapabilityPermissions(process=True))
    assert concedida.call("rodar", {"texto": "x"}) == {"ok": "sim"}


# --------------------------------------------------------------------------- #
# Declaração inválida — falha no import, com o campo nomeado
# --------------------------------------------------------------------------- #


def test_capability_sem_nome_nao_e_declaravel() -> None:
    with pytest.raises(DeclaracaoInvalida) as exc:

        class SemNome(Capability):
            version = "0.1.0"
            description = "x"

            @tool(description="x", entrada=Entrada)
            def x(self, entrada: Entrada) -> dict[str, str]:
                return {}

    assert [p.campo for p in exc.value.problemas] == ["name"]


def test_nome_fora_do_slug_e_recusado() -> None:
    """O nome é diretório, branch e chave do registry ao mesmo tempo."""
    with pytest.raises(DeclaracaoInvalida) as exc:

        class NomeErrado(Capability):
            name = "NAS-Sync"
            version = "0.1.0"
            description = "x"

            @tool(description="x", entrada=Entrada)
            def x(self, entrada: Entrada) -> dict[str, str]:
                return {}

    assert exc.value.problemas[0].campo == "name"
    assert "slug" in exc.value.problemas[0].mensagem


def test_versao_fora_de_semver_e_recusada() -> None:
    with pytest.raises(DeclaracaoInvalida) as exc:

        class VersaoErrada(Capability):
            name = "versao_errada"
            version = "v1"
            description = "x"

            @tool(description="x", entrada=Entrada)
            def x(self, entrada: Entrada) -> dict[str, str]:
                return {}

    assert [p.campo for p in exc.value.problemas] == ["version"]


def test_capability_sem_tool_nao_faz_nada() -> None:
    with pytest.raises(DeclaracaoInvalida) as exc:

        class SemTool(Capability):
            name = "sem_tool"
            version = "0.1.0"
            description = "x"

    assert [p.campo for p in exc.value.problemas] == ["tools"]


def test_handler_com_assinatura_errada_e_recusado() -> None:
    """O SDK entrega (self, entrada); três parâmetros quebrariam na execução."""
    with pytest.raises(DeclaracaoInvalida) as exc:

        class Assinatura(Capability):
            name = "assinatura"
            version = "0.1.0"
            description = "x"

            @tool(description="x", entrada=Entrada)
            def x(self, entrada: Entrada, extra: int = 0) -> dict[str, str]:
                return {}

    assert exc.value.problemas[0].campo == "tools.x"


def test_duas_tools_com_o_mesmo_nome_e_erro() -> None:
    with pytest.raises(DeclaracaoInvalida) as exc:

        class Duplicada(Capability):
            name = "duplicada"
            version = "0.1.0"
            description = "x"

            @tool(description="x", entrada=Entrada, name="mesma")
            def uma(self, entrada: Entrada) -> dict[str, str]:
                return {}

            @tool(description="x", entrada=Entrada, name="mesma")
            def outra(self, entrada: Entrada) -> dict[str, str]:
                return {}

    assert exc.value.problemas[0].campo == "tools.mesma"


def test_problemas_de_declaracao_saem_todos_de_uma_vez() -> None:
    """Consertar um campo por execução é laço; a v3 pagaria em token cada volta."""
    with pytest.raises(DeclaracaoInvalida) as exc:

        class Tudo(Capability):
            version = "x"
            description = ""

    campos = sorted(p.campo for p in exc.value.problemas)
    assert campos == ["description", "name", "tools", "version"]


# --------------------------------------------------------------------------- #
# entrypoint — a ponte para `packages/kernel/runtime/_child.py`
# --------------------------------------------------------------------------- #


def test_entrypoint_tem_a_assinatura_que_o_kernel_chama() -> None:
    """O kernel chama `atributo(tool, arguments)` e espera um mapa JSON."""
    handler = entrypoint(Eco)

    assert handler("eco_repetir", {"texto": "ok"}) == {"resultado": "ok"}


def test_entrypoint_so_constroi_na_primeira_chamada() -> None:
    """Construir lê o manifest do disco; o import do módulo tem de ser barato."""
    construcoes = 0

    def fabrica() -> Eco:
        nonlocal construcoes
        construcoes += 1
        return Eco()

    handler = entrypoint(fabrica)
    assert construcoes == 0

    handler("eco_repetir", {"texto": "a"})
    handler("eco_repetir", {"texto": "b"})
    assert construcoes == 1


def test_metodo_decorado_continua_chamavel_direto() -> None:
    """O decorator não embrulha: handler que reaproveita outro chama o método."""
    assert Eco().eco_repetir(Entrada(texto="ab", vezes=2)).resultado == "abab"
