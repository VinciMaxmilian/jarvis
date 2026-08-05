"""Perfil de agente → prompt, tools, temperatura e modelo.

Antes disto o `ChiefAI` era um papel só: um `SYSTEM_PROMPT` hardcoded no meio do
código, o catálogo inteiro de tools sempre disponível e a temperatura do provider
valendo para tudo. Isso mistura decisões que têm donos diferentes — quem planeja
não deveria conseguir rodar código, e quem revisa não deveria conseguir escrever
arquivo — e transforma "restringir o agente" em "editar a classe".

**Por que o prompt vem de arquivo e não de constante.** Prompt é conteúdo, não
código: quem o ajusta está fazendo edição de texto, e diff de prompt dentro de um
`.py` some no meio da lógica. Os prompts vivem em `packages/agents/prompts/*.md`,
um por perfil, e o perfil só guarda o nome do arquivo.

**Por que este módulo não conhece `Settings` nem `apps/`.** Mesma razão de
`packages/llm/profiles.py`: a resolução precisa rodar no wiring do FastAPI (que
tem `Settings`), no orchestrator (que não passa por HTTP) e no teste (que não tem
nem um nem outro). `packages/` define a porta, `apps/` fornece o adaptador — e
`tests/test_architecture.py` reprova o contrário mecanicamente.

**A restrição de tools é allowlist, não denylist.** O catálogo de tools é
dinâmico: um servidor MCP novo aparece em runtime com um nome que ninguém
escreveu aqui. Uma denylist deixaria toda tool futura liberada por omissão para
todo perfil — exatamente o modo de falha silencioso que a separação de papéis
existe para impedir. Por isso o default de `allow_unlisted` é `False`: tool
desconhecida é negada até que alguém decida o contrário, e o único perfil que
decide o contrário é o que existe para agir.

**A camada divide dois eixos que costumam ser confundidos.** `name` é o PAPEL
(planner, executor); `task_profile` é o TIPO DE TRABALHO que o papel dá ao modelo
e é resolvido por `packages/llm/profiles.py`. Dois papéis podem compartilhar o
mesmo modelo sem compartilhar prompt nem tools, que é o caso do planner e do
reviewer aqui.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from packages.llm.profiles import ModelResolution, resolve_model

#: Onde moram os prompts. Diretório irmão deste módulo para que o perfil e o
#: texto que ele carrega viajem juntos no mesmo pacote.
PROMPTS_DIR: Final = Path(__file__).parent / "prompts"


class UnknownAgentProfile(LookupError):
    """Papel pedido que não existe. Nomeia os válidos porque a causa é sempre
    erro de digitação ou perfil renomeado, e a lista resolve os dois."""

    def __init__(self, name: str, validos: Collection[str]) -> None:
        super().__init__(
            f"perfil de agente desconhecido: {name!r}. "
            f"Válidos: {', '.join(sorted(validos))}."
        )
        self.name = name


class PromptNotFound(FileNotFoundError):
    """Arquivo de prompt ausente.

    Levanta de propósito, ao contrário da resolução de modelo (que degrada): um
    modelo pior ainda responde, mas um agente sem prompt roda sem instrução
    nenhuma e o resultado é plausível o bastante para ninguém notar. Falhar aqui
    é barulhento uma vez; degradar seria errado para sempre.
    """

    def __init__(self, profile: str, path: Path) -> None:
        super().__init__(f"prompt do perfil {profile!r} não encontrado em {path}")
        self.profile = profile
        self.path = path


class ToolPolicy(BaseModel):
    """Quais tools um papel pode chamar.

    Três campos e uma ordem de precedência fixa: `deny` vence tudo, depois
    `allow`, e o que sobra cai em `allow_unlisted`. `deny` existe mesmo com
    allowlist porque um perfil que libera o catálogo dinâmico (`allow_unlisted`)
    ainda precisa poder proibir uma tool nominalmente.
    """

    model_config = ConfigDict(frozen=True)

    #: Nomes exatos liberados.
    allow: frozenset[str] = frozenset()
    #: Nomes exatos proibidos. Vence `allow` — negar é a decisão mais forte.
    deny: frozenset[str] = frozenset()
    #: Tool que não está em `allow` nem em `deny` passa? Default `False`: o
    #: catálogo cresce sozinho (MCP) e crescer não pode ampliar permissão.
    allow_unlisted: bool = False

    def permite(self, tool: str) -> bool:
        """`True` se este papel pode chamar `tool`."""
        if tool in self.deny:
            return False
        if tool in self.allow:
            return True
        return self.allow_unlisted


class AgentProfile(BaseModel):
    """Um papel: prompt, tools, temperatura e para onde vai a chamada de LLM."""

    model_config = ConfigDict(frozen=True)

    #: O papel. É a chave de `AGENT_PROFILES` e o que aparece em log.
    name: str
    #: Uma linha sobre o que este papel produz, para a UI e para quem lê o mapa.
    description: str = ""
    #: Arquivo em `PROMPTS_DIR`. Só o nome — o diretório é do módulo.
    prompt_file: str
    #: Tipo de trabalho para `packages.llm.profiles.resolve_model`. É o que
    #: escolhe o MODELO; o papel escolhe o prompt e as tools.
    task_profile: str = "chief"
    #: `None` significa "não mande temperatura, use o default do provider".
    #: Distinto de `0.0`, que é uma escolha de determinismo.
    temperature: float | None = None
    #: `None` significa "use o provider default do sistema". Preenchido, PRENDE o
    #: papel a um provider — é o gancho para rodar um papel local e outro remoto.
    provider: str | None = None
    tools: ToolPolicy = Field(default_factory=ToolPolicy)

    @property
    def prompt_path(self) -> Path:
        return PROMPTS_DIR / self.prompt_file


# --------------------------------------------------------------------------- #
# Os perfis
# --------------------------------------------------------------------------- #
#
# `web_search` e `search_memory` são leitura e aparecem em todo papel: nenhum
# deles tem efeito colateral fora de uma requisição HTTP de busca.
# `criar_servidor_mcp` escreve arquivo no repo e recarrega o processo — é a única
# tool de ação nativa hoje, e por isso é ela que separa o executor dos outros.

_LEITURA: Final = frozenset({"web_search", "search_memory"})
_ACAO: Final = frozenset({"criar_servidor_mcp", "knowledge_save", "knowledge_forget"})


#: O papel histórico, preservado byte a byte.
#:
#: Existe para que a refatoração não mude comportamento: `ChiefAI` sem perfil
#: explícito continua com o mesmo prompt, o catálogo inteiro de tools e a
#: temperatura default do provider (`temperature=None`, não `0.7` escrito à mão —
#: fixar o número aqui roubaria do provider uma decisão que era dele).
CHIEF_PROFILE: Final = AgentProfile(
    name="chief",
    description="Conversa com o dono e delega. O papel generalista da v0.",
    prompt_file="chief.md",
    task_profile="chief",
    temperature=None,
    tools=ToolPolicy(allow_unlisted=True),
)

PLANNER_PROFILE: Final = AgentProfile(
    name="planner",
    description="Decompõe objetivo em etapas. Não executa nada.",
    prompt_file="planner.md",
    task_profile="chief",
    # Plano é contrato entre os outros papéis: o mesmo objetivo deve render o
    # mesmo plano duas vezes seguidas, ou o reviewer nunca fecha.
    temperature=0.2,
    tools=ToolPolicy(allow=_LEITURA, deny=_ACAO, allow_unlisted=False),
)

RESEARCHER_PROFILE: Final = AgentProfile(
    name="researcher",
    description="Busca e verifica informação. Só lê.",
    prompt_file="researcher.md",
    # `cheap`: o contexto difícil já vem recuperado pela busca, então o trabalho
    # do modelo é condensar — volume alto, resposta curta.
    task_profile="cheap",
    temperature=0.3,
    tools=ToolPolicy(allow=_LEITURA, deny=_ACAO, allow_unlisted=False),
)

EXECUTOR_PROFILE: Final = AgentProfile(
    name="executor",
    description="Executa a etapa. Único papel com tools de ação.",
    prompt_file="executor.md",
    task_profile="code",
    # Zero: execução não é lugar para variedade. Duas execuções da mesma etapa
    # devem chamar a mesma tool com os mesmos argumentos.
    temperature=0.0,
    # Único perfil com `allow_unlisted`: as tools de MCP nascem em runtime e são
    # a superfície de ação do sistema. Negá-las por omissão aqui deixaria o
    # executor sem nada para executar.
    tools=ToolPolicy(allow=_LEITURA | _ACAO, allow_unlisted=True),
)

REVIEWER_PROFILE: Final = AgentProfile(
    name="reviewer",
    description="Julga o resultado. Não conserta e não escreve.",
    prompt_file="reviewer.md",
    task_profile="chief",
    # Mais baixa que a do planner: veredito é a saída menos criativa do sistema.
    temperature=0.1,
    tools=ToolPolicy(allow=_LEITURA, deny=_ACAO, allow_unlisted=False),
)


#: O `chief` numa chamada de voz.
#:
#: Existe como perfil próprio, e não como `chief` com outro prompt no banco, por
#: uma razão concreta: o prompt do `chief` PEDE markdown e HTML ("respostas
#: visualmente atrativas", tabelas, botões — ver `apps/api/deps.get_chief_ai`), e
#: markdown lido por um sintetizador de voz vira "asterisco asterisco". São dois
#: canais com exigências opostas sobre a mesma resposta, e é exatamente o tipo de
#: divergência que a camada de perfis existe para separar.
#:
#: `allow_unlisted=True` como o `chief`: a voz precisa do catálogo inteiro,
#: incluindo as tools de MCP que nascem em runtime. Restringir aqui deixaria o
#: Jarvis falado mais burro que o escrito, que é o problema que este perfil vem
#: consertar — até esta versão o caminho de voz não passava tools NENHUMA.
#:
#: `temperature=0.6`: um pouco abaixo do default conversacional. Fala não tem
#: revisão — o dono não relê, ele ouve uma vez — então divagação custa mais caro
#: aqui do que no texto.
VOICE_PROFILE: Final = AgentProfile(
    name="voice",
    description="O Jarvis numa chamada de voz. Sem markdown, frases curtas.",
    prompt_file="voice.md",
    task_profile="chief",
    temperature=0.6,
    tools=ToolPolicy(allow_unlisted=True),
)

AGENT_PROFILES: Final[Mapping[str, AgentProfile]] = {
    p.name: p
    for p in (
        CHIEF_PROFILE,
        PLANNER_PROFILE,
        RESEARCHER_PROFILE,
        EXECUTOR_PROFILE,
        REVIEWER_PROFILE,
        VOICE_PROFILE,
    )
}

#: Ordem estável para UI e teste.
AGENT_PROFILE_NAMES: Final[tuple[str, ...]] = tuple(AGENT_PROFILES)


def get_agent_profile(name: str) -> AgentProfile:
    """Papel pelo nome. Levanta `UnknownAgentProfile` se não existir.

    Levanta, ao contrário de `resolve_model`, porque perfil errado não tem
    degradação sensata: servir o prompt do executor a quem pediu o reviewer é
    pior do que não responder.
    """
    profile = AGENT_PROFILES.get(name)
    if profile is None:
        raise UnknownAgentProfile(name, AGENT_PROFILES)
    return profile


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #

#: Cache por caminho resolvido. O prompt é imutável em runtime e é lido no
#: caminho quente (toda construção de agente); reler o arquivo a cada chamada
#: seria I/O síncrono dentro de um handler async.
_CACHE_PROMPT: dict[Path, str] = {}


def load_prompt(profile: AgentProfile, *, prompts_dir: Path | None = None) -> str:
    """Texto do prompt de um papel.

    `prompts_dir` sobrescreve o diretório e existe para o teste: exercitar
    "prompt ausente" e "prompt trocado" sem mexer nos arquivos do pacote.
    """
    path = (prompts_dir / profile.prompt_file) if prompts_dir else profile.prompt_path

    cached = _CACHE_PROMPT.get(path)
    if cached is not None:
        return cached

    try:
        # `read_text` normaliza CRLF para LF: o repo é clonado no Windows e o
        # prompt não pode mudar de bytes conforme o `core.autocrlf` de quem
        # clonou.
        texto = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PromptNotFound(profile.name, path) from exc

    _CACHE_PROMPT[path] = texto
    return texto


def clear_prompt_cache() -> None:
    """Esvazia o cache. Para o teste que troca arquivo de prompt entre casos."""
    _CACHE_PROMPT.clear()


# --------------------------------------------------------------------------- #
# Modelo
# --------------------------------------------------------------------------- #


def resolve_agent_model(
    profile: AgentProfile,
    provider: str,
    *,
    override: str = "",
    provider_default: str = "",
    served: Collection[str] | None = None,
) -> ModelResolution:
    """Modelo para um papel, com a razão da escolha. Nunca levanta.

    Fina de propósito: o papel só contribui com `task_profile`, e toda a cadeia
    de fallback continua morando em `packages/llm/profiles.py`. Reimplementar a
    degradação aqui daria duas respostas diferentes para "qual modelo serve isto"
    no dia em que uma das duas mudasse.
    """
    return resolve_model(
        profile.task_profile,
        provider,
        override=override,
        provider_default=provider_default,
        served=served,
    )


def agent_provider(profile: AgentProfile, default_provider: str) -> str:
    """Provider efetivo do papel: o que ele fixou, senão o do sistema.

    É o ponto único onde "este papel roda local, aquele roda remoto" é decidido.
    Sem ele, cada chamador leria `profile.provider` e trataria o `None` do seu
    jeito.
    """
    return profile.provider or default_provider


__all__ = [
    "AGENT_PROFILES",
    "AGENT_PROFILE_NAMES",
    "CHIEF_PROFILE",
    "EXECUTOR_PROFILE",
    "PLANNER_PROFILE",
    "PROMPTS_DIR",
    "RESEARCHER_PROFILE",
    "REVIEWER_PROFILE",
    "AgentProfile",
    "PromptNotFound",
    "ToolPolicy",
    "UnknownAgentProfile",
    "agent_provider",
    "clear_prompt_cache",
    "get_agent_profile",
    "load_prompt",
    "resolve_agent_model",
]
