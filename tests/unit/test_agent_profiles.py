"""Perfis de agente: prompt de arquivo, tools por papel, modelo e temperatura.

O que está sendo protegido aqui é a SEPARAÇÃO. Um perfil é só um dado — nada
impede que ele exista, seja lido em log, apareça na UI e mesmo assim não restrinja
coisa nenhuma, porque a restrição de verdade acontece no caminho da execução. Por
isso metade deste arquivo não olha para o perfil e sim para o que acontece quando
alguém tenta chamar a tool proibida: perfil que declara e não impede é pior do que
perfil nenhum, já que passa a sensação de que o planner não executa.

Nada aqui vai à rede nem lê `.env`: a resolução de modelo é função pura
(`packages/llm/profiles.py`) e o loop do agente roda sobre os dublês de
`tests/conftest.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final
from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.agents.chief import SYSTEM_PROMPT, ChiefAI
from packages.agents.profiles import (
    AGENT_PROFILE_NAMES,
    AGENT_PROFILES,
    CHIEF_PROFILE,
    EXECUTOR_PROFILE,
    PLANNER_PROFILE,
    PROMPTS_DIR,
    RESEARCHER_PROFILE,
    REVIEWER_PROFILE,
    AgentProfile,
    PromptNotFound,
    ToolPolicy,
    UnknownAgentProfile,
    agent_provider,
    clear_prompt_cache,
    get_agent_profile,
    load_prompt,
    resolve_agent_model,
)
from packages.agents.tool_guard import ProfiledToolExecutor, ToolDenied, guard_tools
from packages.llm.base import Completion, Message, StreamChunk
from packages.llm.profiles import PROFILE_MODELS
from packages.shared.contracts import ToolSpec
from packages.shared.ports import ToolExecutor
from tests.conftest import (
    FakeLLMProvider,
    InMemoryConversationStore,
    RecordingToolExecutor,
    make_tool_spec,
)

#: Roster do LM Studio, o mesmo medido em `tests/unit/test_model_profiles.py`.
#: Duplicado de propósito: este arquivo afirma coisas sobre o PAPEL, e importar o
#: roster do outro módulo acoplaria dois testes que falham por razões diferentes.
ROSTER_LMSTUDIO: Final = frozenset(
    {
        "google/gemma-4-e2b",
        "qwen3-vl-8b-instruct",
        "qwen3-reranker-0.6b",
        "text-embedding-qwen3-embedding-0.6b",
        "deepseek-coder-v2-lite-instruct",
    }
)

#: Os papéis que existem para NÃO agir. O oposto do executor, e a razão de a
#: camada existir.
RESTRITOS: Final = (PLANNER_PROFILE, RESEARCHER_PROFILE, REVIEWER_PROFILE)


# --------------------------------------------------------------------------- #
# Carregamento de perfil
# --------------------------------------------------------------------------- #


def test_os_quatro_papeis_existem_alem_do_chief() -> None:
    assert set(AGENT_PROFILES) == {
        "chief",
        "planner",
        "researcher",
        "executor",
        "reviewer",
    }
    assert AGENT_PROFILE_NAMES[0] == "chief"


@pytest.mark.parametrize("name", sorted(AGENT_PROFILES))
def test_perfil_e_recuperado_pelo_nome(name: str) -> None:
    assert get_agent_profile(name).name == name


def test_perfil_desconhecido_levanta_nomeando_os_validos() -> None:
    """Sem a lista na mensagem, um typo em `planer` vira meia hora de procura."""
    with pytest.raises(UnknownAgentProfile) as exc:
        get_agent_profile("planer")
    assert "planner" in str(exc.value)
    assert "planer" in str(exc.value)


@pytest.mark.parametrize("profile", list(AGENT_PROFILES.values()))
def test_todo_perfil_tem_arquivo_de_prompt_com_conteudo(profile: AgentProfile) -> None:
    """Perfil apontando para arquivo inexistente só falharia ao ser usado, que na
    prática é no primeiro pedido do dono para aquele papel."""
    assert profile.prompt_path.parent == PROMPTS_DIR
    assert profile.prompt_path.is_file()
    assert len(load_prompt(profile).strip()) > 100


@pytest.mark.parametrize("profile", list(AGENT_PROFILES.values()))
def test_prompt_vem_do_arquivo_e_nao_do_codigo(
    profile: AgentProfile, tmp_path: Path
) -> None:
    """A propriedade que dá sentido a `prompts/*.md`: trocar o arquivo troca o
    prompt, sem editar um `.py`. Se o texto estivesse hardcoded, este teste leria
    o mesmo conteúdo dos dois diretórios e passaria batido — por isso ele afirma
    a igualdade com o que ESCREVEU, não a diferença."""
    clear_prompt_cache()
    (tmp_path / profile.prompt_file).write_text("prompt trocado", encoding="utf-8")
    assert load_prompt(profile, prompts_dir=tmp_path) == "prompt trocado"
    clear_prompt_cache()


def test_prompt_ausente_levanta_em_vez_de_degradar(tmp_path: Path) -> None:
    """Ao contrário da resolução de modelo, aqui não há degradação sensata: um
    agente sem instrução responde algo plausível e ninguém percebe."""
    clear_prompt_cache()
    with pytest.raises(PromptNotFound) as exc:
        load_prompt(PLANNER_PROFILE, prompts_dir=tmp_path)
    assert "planner" in str(exc.value)


def test_cada_papel_tem_um_prompt_diferente() -> None:
    """Dois papéis com o mesmo texto seriam o mesmo papel com dois nomes."""
    textos = [load_prompt(p) for p in AGENT_PROFILES.values()]
    assert len(set(textos)) == len(textos)


def test_prompt_do_chief_e_o_historico_byte_a_byte() -> None:
    """Regressão da própria refatoração. O texto saiu de uma constante em
    `chief.py` para `prompts/chief.md`; qualquer diferença — inclusive um `\\n` a
    mais no fim — muda o comportamento do agente sem quebrar nenhum outro teste.
    """
    do_arquivo = (PROMPTS_DIR / "chief.md").read_text(encoding="utf-8")
    assert do_arquivo == SYSTEM_PROMPT
    assert SYSTEM_PROMPT.startswith("Você é o Jarvis")
    assert SYSTEM_PROMPT.endswith("sem pedir permissão ao usuário.\n")
    assert len(SYSTEM_PROMPT) == 911


# --------------------------------------------------------------------------- #
# Política de tools — a declaração
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("profile", RESTRITOS)
def test_papel_que_nao_age_nao_pode_criar_servidor_mcp(profile: AgentProfile) -> None:
    """`criar_servidor_mcp` escreve arquivo no repo e recarrega o processo. É a
    única tool de ação nativa hoje, e é ela que separa o executor dos outros."""
    assert profile.tools.permite("criar_servidor_mcp") is False


def test_executor_e_o_unico_que_age() -> None:
    assert EXECUTOR_PROFILE.tools.permite("criar_servidor_mcp") is True


@pytest.mark.parametrize("profile", list(AGENT_PROFILES.values()))
@pytest.mark.parametrize("tool", ["web_search", "search_memory"])
def test_leitura_e_liberada_para_todo_papel(profile: AgentProfile, tool: str) -> None:
    """Buscar não tem efeito colateral: negar isso ao planner só o faria planejar
    sobre suposição."""
    assert profile.tools.permite(tool) is True


@pytest.mark.parametrize("profile", RESTRITOS)
def test_tool_dinamica_desconhecida_e_negada_por_omissao(profile: AgentProfile) -> None:
    """O caso que uma denylist erraria: um servidor MCP novo aparece em runtime
    com um nome que ninguém escreveu no código. Para o papel que não age, o
    catálogo crescer não pode ampliar permissão."""
    assert profile.tools.permite("mcp_qualquer_coisa_nova") is False


def test_executor_alcanca_as_tools_de_mcp_que_nascem_em_runtime() -> None:
    """A contrapartida: negar o desconhecido ao executor o deixaria sem nada para
    executar, porque a superfície de ação do sistema é justamente o MCP."""
    assert EXECUTOR_PROFILE.tools.permite("mcp_qualquer_coisa_nova") is True


def test_deny_vence_allow() -> None:
    """Precedência fixa: negar é a decisão mais forte. Sem isso, a ordem de
    avaliação viraria detalhe de implementação de uma regra de segurança."""
    policy = ToolPolicy(allow=frozenset({"x"}), deny=frozenset({"x"}))
    assert policy.permite("x") is False


def test_deny_vence_ate_o_allow_unlisted() -> None:
    policy = ToolPolicy(deny=frozenset({"x"}), allow_unlisted=True)
    assert policy.permite("x") is False
    assert policy.permite("y") is True


def test_default_da_politica_e_negar() -> None:
    """Um `ToolPolicy()` vazio não pode liberar nada: perfil novo escrito às
    pressas tem de nascer inofensivo, não onipotente."""
    assert ToolPolicy().permite("qualquer_coisa") is False


def test_chief_preserva_o_catalogo_inteiro() -> None:
    """O papel histórico. Apertar a política dele mudaria o comportamento da v0."""
    assert CHIEF_PROFILE.tools.permite("criar_servidor_mcp") is True
    assert CHIEF_PROFILE.tools.permite("mcp_qualquer_coisa_nova") is True


# --------------------------------------------------------------------------- #
# Política de tools — a aplicação (é isto que vale)
# --------------------------------------------------------------------------- #

_CATALOGO: Final = ["web_search", "search_memory", "criar_servidor_mcp"]


def _executor_com_catalogo() -> RecordingToolExecutor:
    return RecordingToolExecutor([make_tool_spec(n) for n in _CATALOGO])


def test_envelope_satisfaz_a_mesma_porta_que_envolve() -> None:
    """Se não satisfizesse, quem consome teria de saber que está restrito — e a
    restrição viraria opcional."""
    guarded = guard_tools(_executor_com_catalogo(), PLANNER_PROFILE)
    assert isinstance(guarded, ToolExecutor)


async def test_planner_nao_consegue_executar_a_tool_proibida() -> None:
    """O teste central da fatia. Não basta o perfil DIZER que o planner não age:
    a chamada tem de morrer, e morrer ANTES de chegar no executor de baixo."""
    inner = _executor_com_catalogo()
    guarded = guard_tools(inner, PLANNER_PROFILE)

    with pytest.raises(ToolDenied) as exc:
        await guarded.execute("criar_servidor_mcp", {"nome": "x", "codigo_main_py": ""})

    assert exc.value.profile == "planner"
    assert exc.value.tool == "criar_servidor_mcp"
    # A prova de que a recusa veio antes do efeito, e não depois dele.
    assert inner.calls == []


async def test_executor_atravessa_o_envelope_e_chega_no_de_baixo() -> None:
    inner = _executor_com_catalogo()
    guarded = guard_tools(inner, EXECUTOR_PROFILE)

    resultado = await guarded.execute("criar_servidor_mcp", {"nome": "clima"})

    assert resultado == {"ok": True, "tool": "criar_servidor_mcp"}
    assert inner.calls == [("criar_servidor_mcp", {"nome": "clima"}, False)]


async def test_dry_run_atravessa_o_envelope_sem_ser_reinterpretado() -> None:
    """O envelope decide QUEM pode, não COMO executa: `dry_run` é do executor de
    baixo e não pode ser perdido no caminho."""
    inner = _executor_com_catalogo()
    guarded = guard_tools(inner, EXECUTOR_PROFILE)

    await guarded.execute("web_search", {"query": "x"}, dry_run=True)

    assert inner.calls == [("web_search", {"query": "x"}, True)]


@pytest.mark.parametrize("profile", RESTRITOS)
def test_catalogo_visto_pelo_papel_restrito_nao_contem_a_tool_de_acao(
    profile: AgentProfile,
) -> None:
    """Filtrar o catálogo é ergonomia — o modelo não pede o que não vê. A garantia
    é o `execute`, mas mostrar a tool e recusá-la depois desperdiça um round."""
    guarded = guard_tools(_executor_com_catalogo(), profile)
    nomes = {s.name for s in guarded.specs()}
    assert nomes == {"web_search", "search_memory"}


def test_catalogo_do_executor_e_o_completo() -> None:
    guarded = guard_tools(_executor_com_catalogo(), EXECUTOR_PROFILE)
    assert {s.name for s in guarded.specs()} == set(_CATALOGO)


async def test_get_all_specs_funciona_com_executor_que_so_tem_specs() -> None:
    """`SystemToolExecutor` tem `get_all_specs` (sistema + MCP) e o dublê não. O
    envelope precisa das duas formas: era este o `hasattr` que vivia no ChiefAI."""
    guarded = guard_tools(_executor_com_catalogo(), PLANNER_PROFILE)
    nomes = {s.name for s in await guarded.get_all_specs()}
    assert nomes == {"web_search", "search_memory"}


async def test_get_all_specs_prefere_o_catalogo_async_e_filtra_ele() -> None:
    """Com MCP no meio, o catálogo completo só existe no caminho async — filtrar
    apenas o `specs()` síncrono deixaria as tools de MCP passarem inteiras."""

    class ComMCP(RecordingToolExecutor):
        async def get_all_specs(self) -> list[ToolSpec]:
            return [*self.specs(), make_tool_spec("mcp_tool_nova")]

    guarded = guard_tools(ComMCP([make_tool_spec("web_search")]), PLANNER_PROFILE)
    assert {s.name for s in await guarded.get_all_specs()} == {"web_search"}


def test_has_responde_pela_permissao_e_nao_so_pela_existencia() -> None:
    """`has()` responde "dá para chamar?". Dizer `True` e explodir no `execute`
    empurraria a surpresa para o meio da execução."""
    guarded = guard_tools(_executor_com_catalogo(), PLANNER_PROFILE)
    assert guarded.has("web_search") is True
    assert guarded.has("criar_servidor_mcp") is False


def test_has_continua_falso_para_tool_que_nem_existe() -> None:
    guarded = guard_tools(_executor_com_catalogo(), EXECUTOR_PROFILE)
    assert guarded.has("nao_existe_em_lugar_nenhum") is False


def test_envelope_expoe_o_perfil_para_diagnostico() -> None:
    guarded = guard_tools(_executor_com_catalogo(), REVIEWER_PROFILE)
    assert isinstance(guarded, ProfiledToolExecutor)
    assert guarded.profile is REVIEWER_PROFILE


# --------------------------------------------------------------------------- #
# Modelo e temperatura por papel
# --------------------------------------------------------------------------- #


def test_cada_papel_tem_temperatura_propria() -> None:
    assert PLANNER_PROFILE.temperature == 0.2
    assert RESEARCHER_PROFILE.temperature == 0.3
    assert EXECUTOR_PROFILE.temperature == 0.0
    assert REVIEWER_PROFILE.temperature == 0.1


def test_executor_e_o_mais_deterministico_dos_papeis() -> None:
    """Ordem, não valores: execução não é lugar para variedade, e planejar admite
    mais do que revisar. Afirmar a relação sobrevive a um ajuste de número."""
    temperaturas = [
        p.temperature
        for p in (EXECUTOR_PROFILE, REVIEWER_PROFILE, PLANNER_PROFILE, RESEARCHER_PROFILE)
    ]
    assert all(t is not None for t in temperaturas)
    assert temperaturas == sorted(temperaturas)  # type: ignore[type-var]


def test_chief_nao_fixa_temperatura() -> None:
    """`None` é "não mande o parâmetro", não `0.7` escrito à mão: o default é uma
    decisão do provider, e o papel histórico a preserva."""
    assert CHIEF_PROFILE.temperature is None


def test_papel_escolhe_o_modelo_pelo_tipo_de_trabalho() -> None:
    """Os dois eixos que a camada separa: o PAPEL escolhe prompt e tools, o
    `task_profile` escolhe o modelo. O executor gera e chama código, então cai no
    modelo de código; o planner precisa de contexto longo."""
    do_executor = resolve_agent_model(
        EXECUTOR_PROFILE, "lmstudio", served=ROSTER_LMSTUDIO
    )
    do_planner = resolve_agent_model(PLANNER_PROFILE, "lmstudio", served=ROSTER_LMSTUDIO)

    assert do_executor.model == PROFILE_MODELS["lmstudio"]["code"]
    assert do_planner.model == PROFILE_MODELS["lmstudio"]["chief"]
    assert do_executor.model != do_planner.model
    assert do_executor.degraded is False


def test_researcher_usa_o_modelo_barato_porque_o_contexto_ja_vem_recuperado() -> None:
    res = resolve_agent_model(RESEARCHER_PROFILE, "lmstudio", served=ROSTER_LMSTUDIO)
    assert res.model == PROFILE_MODELS["lmstudio"]["cheap"]


def test_planner_e_reviewer_compartilham_modelo_sem_compartilhar_papel() -> None:
    """Modelo igual não é papel igual, e política de tools igual também não.

    Estes dois papéis coincidem em dois dos quatro eixos — mesmo `task_profile` e
    mesma `ToolPolicy` (nenhum dos dois age) — e ainda assim são papéis
    diferentes, porque o prompt e a temperatura são deles. É exatamente por isso
    que os eixos são independentes: se o perfil fosse um enum único, decidir o
    modelo do reviewer decidiria também o que ele pode chamar.
    """
    a = resolve_agent_model(PLANNER_PROFILE, "lmstudio", served=ROSTER_LMSTUDIO)
    b = resolve_agent_model(REVIEWER_PROFILE, "lmstudio", served=ROSTER_LMSTUDIO)

    assert a.model == b.model
    assert PLANNER_PROFILE.tools == REVIEWER_PROFILE.tools
    assert load_prompt(PLANNER_PROFILE) != load_prompt(REVIEWER_PROFILE)
    assert PLANNER_PROFILE.temperature != REVIEWER_PROFILE.temperature


@pytest.mark.parametrize("profile", list(AGENT_PROFILES.values()))
def test_nenhum_papel_derruba_a_resolucao_na_maquina_sem_lmstudio(
    profile: AgentProfile,
) -> None:
    """A máquina de casa: Gemini, nenhum modelo do LM Studio. A degradação é o
    requisito — papel que não pode ser servido loga e segue."""
    res = resolve_agent_model(
        profile, "gemini", provider_default="gemini-2.5-flash", served=None
    )
    assert res.model == "gemini-2.5-flash"
    assert res.source == "provider_default"


def test_override_do_dono_vence_o_task_profile_do_papel() -> None:
    res = resolve_agent_model(
        EXECUTOR_PROFILE,
        "lmstudio",
        override="qwen3-vl-8b-instruct",
        served=ROSTER_LMSTUDIO,
    )
    assert res.model == "qwen3-vl-8b-instruct"
    assert res.source == "override"


def test_papel_sem_provider_fixado_usa_o_do_sistema() -> None:
    assert EXECUTOR_PROFILE.provider is None
    assert agent_provider(EXECUTOR_PROFILE, "gemini") == "gemini"


def test_papel_pode_prender_o_proprio_provider() -> None:
    """O gancho de "este papel roda local, aquele roda remoto": preencher
    `provider` no perfil tira dele o provider default do sistema."""
    local = EXECUTOR_PROFILE.model_copy(update={"provider": "lmstudio"})
    assert agent_provider(local, "gemini") == "lmstudio"


def test_perfil_e_imutavel() -> None:
    """Perfil mutável seria configuração global disfarçada: um papel apertaria a
    política do outro em runtime e nada nesta suíte perceberia."""
    with pytest.raises(ValidationError):
        PLANNER_PROFILE.temperature = 0.9


# --------------------------------------------------------------------------- #
# O agente sob o perfil — a ponta que liga tudo
# --------------------------------------------------------------------------- #

#: Sentinela: distingue "não mandou temperatura" de "mandou 0.7". Sem ela, o
#: default do provider e uma escolha explícita de 0.7 seriam indistinguíveis, e o
#: teste do `CHIEF_PROFILE` não provaria nada.
NAO_MANDOU: Final = -1.0


class LLMQueRegistraTemperatura(FakeLLMProvider):
    """`FakeLLMProvider` que guarda a temperatura de cada chamada."""

    def __init__(self) -> None:
        super().__init__()
        self.temperaturas: list[float] = []

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float = NAO_MANDOU,
        max_tokens: int | None = None,
        system: str | None = None,
    ) -> Completion:
        self.temperaturas.append(temperature)
        self.recebeu_tools = list(tools or [])
        return await super().complete(messages, tools, temperature, max_tokens, system)


async def _responder(chief: ChiefAI) -> list[StreamChunk]:
    return [c async for c in chief.respond("faça algo", uuid4())]


async def test_chief_sem_perfil_continua_no_papel_historico() -> None:
    """O aceite da refatoração: construir `ChiefAI` como antes tem de dar o mesmo
    prompt, o mesmo catálogo e nenhuma temperatura."""
    llm = LLMQueRegistraTemperatura()
    chief = ChiefAI(
        llm=llm,
        tools=_executor_com_catalogo(),
        conversation_store=InMemoryConversationStore(),
    )

    await _responder(chief)

    assert chief.profile is CHIEF_PROFILE
    assert chief._system_prompt == SYSTEM_PROMPT
    assert llm.temperaturas == [NAO_MANDOU]
    assert {s.name for s in llm.recebeu_tools} == set(_CATALOGO)


async def test_chief_com_perfil_manda_a_temperatura_do_papel() -> None:
    llm = LLMQueRegistraTemperatura()
    chief = ChiefAI(
        llm=llm,
        tools=_executor_com_catalogo(),
        conversation_store=InMemoryConversationStore(),
        profile=PLANNER_PROFILE,
    )

    await _responder(chief)

    assert llm.temperaturas == [0.2]


async def test_agente_sob_o_planner_so_ve_as_tools_do_planner() -> None:
    llm = LLMQueRegistraTemperatura()
    chief = ChiefAI(
        llm=llm,
        tools=_executor_com_catalogo(),
        conversation_store=InMemoryConversationStore(),
        profile=PLANNER_PROFILE,
    )

    await _responder(chief)

    assert {s.name for s in llm.recebeu_tools} == {"web_search", "search_memory"}


async def test_agente_sob_o_planner_nao_executa_nem_se_o_modelo_pedir() -> None:
    """O modo de falha real: o modelo alucina o nome da tool, ou o histórico traz
    uma chamada feita por outro papel. O catálogo filtrado não cobre isso — a
    recusa no `execute` cobre."""
    inner = _executor_com_catalogo()
    llm = LLMQueRegistraTemperatura()
    llm.queue_tool_call("criar_servidor_mcp", {"nome": "x"})
    llm.queue_text("não posso criar servidor neste papel")

    chief = ChiefAI(
        llm=llm,
        tools=inner,
        conversation_store=InMemoryConversationStore(),
        profile=PLANNER_PROFILE,
    )
    chunks = await _responder(chief)

    # Nada executou...
    assert inner.calls == []
    # ...e mesmo assim o turno terminou com resposta, em vez de estourar.
    assert chunks[-1].type == "done"
    assert "não posso criar servidor" in "".join(c.text for c in chunks)


async def test_agente_sob_o_executor_executa_de_fato() -> None:
    """A contraprova do teste acima: a recusa é do papel, não do loop."""
    inner = _executor_com_catalogo()
    llm = LLMQueRegistraTemperatura()
    llm.queue_tool_call("criar_servidor_mcp", {"nome": "clima"})
    llm.queue_text("servidor criado")

    chief = ChiefAI(
        llm=llm,
        tools=inner,
        conversation_store=InMemoryConversationStore(),
        profile=EXECUTOR_PROFILE,
    )
    await _responder(chief)

    assert [c[0] for c in inner.calls] == ["criar_servidor_mcp"]


async def test_prompt_do_banco_continua_vencendo_o_do_perfil() -> None:
    """É por aqui que o dono sobrescreve o prompt pela UI
    (`apps/api/deps.get_chief_ai`). A camada de perfis não podia fechar essa
    porta."""
    llm = LLMQueRegistraTemperatura()
    chief = ChiefAI(
        llm=llm,
        tools=_executor_com_catalogo(),
        conversation_store=InMemoryConversationStore(),
        system_prompt="prompt vindo do banco",
        profile=REVIEWER_PROFILE,
    )

    await _responder(chief)

    assert llm.received[0][0].content.startswith("prompt vindo do banco")


async def test_perfil_aparece_no_prompt_de_sistema_do_papel_certo() -> None:
    llm = LLMQueRegistraTemperatura()
    chief = ChiefAI(
        llm=llm,
        tools=_executor_com_catalogo(),
        conversation_store=InMemoryConversationStore(),
        profile=REVIEWER_PROFILE,
    )

    await _responder(chief)

    assert "Você é o Reviewer do Jarvis" in llm.received[0][0].content
