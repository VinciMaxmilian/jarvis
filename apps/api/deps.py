"""FastAPI Depends wiring.

Todas as dependências do sistema passam por aqui. Nenhum router instancia
engine, provider ou store diretamente.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Collection, Mapping
from typing import Final, get_args

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.engine import get_session_factory
from apps.api.db.repository import PgConversationStore, PgGoalStore
from packages.agents.chief import ChiefAI
from packages.agents.tools.executor import SystemToolExecutor
from packages.llm.anthropic_provider import AnthropicProvider
from packages.llm.base import LLMError, LLMProvider
from packages.llm.gemini_provider import GeminiProvider
from packages.llm.ollama_provider import OllamaProvider
from packages.llm.openai_provider import OpenAIProvider
from packages.llm.profiles import TASK_PROFILES, ModelResolution, resolve_model
from packages.shared.contracts import ProviderId
from packages.shared.settings import Settings, get_settings
from packages.memory.factory import build_vector_store
from packages.shared.ports import VectorStore
from packages.registry.registry import CapabilityRegistry
from packages.kernel.event_bus.in_proc import InProcEventBus
from packages.kernel.event_bus.redis_bus import RedisEventBus
import os

_CHAT_HISTORY_STORE: VectorStore | None = None
_MEMORY_VECTOR_STORE: VectorStore | None = None
_REGISTRY: CapabilityRegistry | None = None

_settings = get_settings()
if _settings.redis_url:
    _DUMMY_BUS = RedisEventBus(redis_url=str(_settings.redis_url), consumer_name="api_1")
else:
    _DUMMY_BUS = InProcEventBus()


def get_capability_registry() -> CapabilityRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        cap_dir = os.path.join(os.path.dirname(__file__), "..", "..", "capabilities")
        _REGISTRY = CapabilityRegistry(base_dir=cap_dir, event_bus=_DUMMY_BUS)
    return _REGISTRY

def get_chat_history_store() -> VectorStore:
    global _CHAT_HISTORY_STORE
    if _CHAT_HISTORY_STORE is None:
        from packages.memory.factory import vector_backend
        _CHAT_HISTORY_STORE = build_vector_store(backend=vector_backend(), table="chat_history")
    return _CHAT_HISTORY_STORE

def get_memory_vector_store() -> VectorStore:
    global _MEMORY_VECTOR_STORE
    if _MEMORY_VECTOR_STORE is None:
        from packages.memory.factory import vector_backend
        _MEMORY_VECTOR_STORE = build_vector_store(backend=vector_backend(), table="memory")
    return _MEMORY_VECTOR_STORE


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield de session com commit automático ao final (ou rollback em exceção)."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_goal_store(session: AsyncSession) -> PgGoalStore:
    return PgGoalStore(session)


async def get_conversation_store(session: AsyncSession) -> PgConversationStore:
    return PgConversationStore(session)


# --------------------------------------------------------------------------- #
# Providers de LLM — mapa de fábricas, não ramificação
# --------------------------------------------------------------------------- #

#: Uma fábrica recebe a config validada e o modelo pedido, e devolve o provider.
#: Modelo vazio significa "use o default deste provider".
ProviderFactory = Callable[[Settings, str], LLMProvider]


def _build_gemini(settings: Settings, model: str) -> LLMProvider:
    return GeminiProvider(
        api_key=settings.gemini_api_key,
        model=model or settings.gemini_model,
        embed_model="gemini-embedding-2",
    )


def _build_anthropic(settings: Settings, model: str) -> LLMProvider:
    return AnthropicProvider(
        api_key=settings.anthropic_api_key,
        model=model or settings.chief_model,
    )


def _build_lmstudio(settings: Settings, model: str) -> LLMProvider:
    """LM Studio na LAN. Mesma classe do `openai` — o LM Studio serve a API
    OpenAI — mas com base_url, chave e modelo próprios, para que apontar um não
    desaponte o outro.

    O modelo de CHAT continua sendo o escolhido pelo dono (`model`, ou
    `LMSTUDIO_MODEL`): quem grava provider e modelo na tela de configurações
    espera que a conversa use aquilo, e sobrescrever isso pelo perfil `chief`
    tiraria o controle de quem o tem. O modelo de EMBEDDING não tem essa escolha
    na UI e é um `type` diferente no LM Studio, então vem do perfil `embed` — sem
    isso, `embed()` iria para o modelo de conversa e devolveria 400.
    """
    return OpenAIProvider(
        api_key=settings.lmstudio_api_key,
        base_url=settings.lmstudio_base_url,
        model=model or settings.lmstudio_model,
        embed_model=resolve_profile_model("embed", "lmstudio", settings).model or None,
    )


def _build_openai_compatible(settings: Settings, model: str) -> LLMProvider:
    """Serve tanto `openai` quanto `local` — LM Studio, vLLM e Koboldcpp falam a
    mesma API; o que muda é só a `base_url`.

    Sem `embed_model` de propósito: não há mapa de perfis para `openai`/`local`
    (o backend por trás desta base_url é desconhecido), então resolver o perfil
    devolveria o próprio modelo de chat — o mesmo que o default da classe faz,
    só que fingindo que houve uma decisão.
    """
    return OpenAIProvider(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=model or settings.chief_model,
    )


def _build_ollama(settings: Settings, model: str) -> LLMProvider:
    """Entrada separada de `local` de propósito: o Ollama é servido pela API
    nativa (`/api/chat`), não pela camada OpenAI-compatible.
    """
    return OllamaProvider(
        base_url=settings.ollama_url,
        model=model or settings.ollama_model,
    )


#: Somar um provider é somar uma entrada aqui — nunca um `elif` em
#: `get_llm_provider`. É esta tabela que a API expõe para a UI não ter lista
#: hardcoded, e é ela que define os defaults de modelo por provider.
#:
#: A ORDEM é a preferência de fallback declarada: lmstudio → gemini → anthropic →
#: openai → ollama. Nada consome essa ordem para failover automático hoje; ela
#: existe para que a UI ofereça na ordem certa e para que o failover, quando
#: entrar, não precise inventar prioridade. `lmstudio` vem primeiro porque é
#: inferência local sem custo por token; `ollama` vem por último porque é o
#: último recurso (roda fora do Docker, ver infrastructure/README.md). `local` é
#: apelido histórico de `openai` (mesma API, outra base_url) e fica ao lado dele.
PROVIDER_FACTORIES: Final[Mapping[str, ProviderFactory]] = {
    "lmstudio": _build_lmstudio,
    "gemini": _build_gemini,
    "anthropic": _build_anthropic,
    "openai": _build_openai_compatible,
    "local": _build_openai_compatible,
    "ollama": _build_ollama,
}

#: Modelo sugerido por provider. A UI usa para trocar o campo de modelo junto com
#: o provider — sem isso, trocar para `ollama` mantendo `gemini-2.5-flash` só
#: falha na primeira geração.
PROVIDER_DEFAULT_MODEL_ATTR: Final[Mapping[str, str]] = {
    "lmstudio": "lmstudio_model",
    "gemini": "gemini_model",
    "anthropic": "chief_model",
    "openai": "chief_model",
    "local": "chief_model",
    "ollama": "ollama_model",
}

# Fail-fast no import: `ProviderId` valida a entrada da API e este mapa serve a
# requisição. Divergência entre os dois deixaria um provider aceitável pelo
# contrato sem ninguém para atendê-lo — erro que só apareceria em produção.
_DECLARED_PROVIDERS: Final = frozenset(get_args(ProviderId))
if frozenset(PROVIDER_FACTORIES) != _DECLARED_PROVIDERS:
    raise RuntimeError(
        "ProviderId e PROVIDER_FACTORIES divergiram: "
        f"sem fábrica={sorted(_DECLARED_PROVIDERS - set(PROVIDER_FACTORIES))}, "
        f"sem contrato={sorted(set(PROVIDER_FACTORIES) - _DECLARED_PROVIDERS)}"
    )


def valid_provider_ids() -> list[str]:
    """Providers atendíveis agora, em ordem de preferência (não alfabética).

    Fonte única para a API e para as mensagens de erro. A ordem é a do mapa, para
    que a UI mostre o principal primeiro.
    """
    return list(PROVIDER_FACTORIES)


def provider_default_model(provider: str, settings: Settings | None = None) -> str:
    """Modelo default de um provider, ou "" se o provider não existe."""
    attr = PROVIDER_DEFAULT_MODEL_ATTR.get(provider)
    if attr is None:
        return ""
    resolved = settings or get_settings()
    value = getattr(resolved, attr)
    return value if isinstance(value, str) else ""


# --------------------------------------------------------------------------- #
# Perfis de tarefa — a ponte entre `packages.llm.profiles` (função pura) e a config
# --------------------------------------------------------------------------- #


def profile_override(provider: str, profile: str, settings: Settings) -> str:
    """Override do dono para (provider, perfil), ou "" se não declarado.

    `getattr` dinâmico em vez de uma tabela: o nome do campo em `Settings` JÁ é a
    convenção (`lmstudio_model_embed` ↔ `LMSTUDIO_MODEL_EMBED`), e uma tabela
    paralela seria a quarta lista a manter em sincronia neste arquivo — as três
    que já existem custaram um teste cada. Provider sem campo declarado (todo
    `gemini`, por exemplo) devolve "" e a resolução segue para o mapa, que é
    exatamente o comportamento desejado na máquina de casa.
    """
    if profile not in TASK_PROFILES:
        return ""
    value = getattr(settings, f"{provider}_model_{profile}", "")
    return value if isinstance(value, str) else ""


def resolve_profile_model(
    profile: str,
    provider: str,
    settings: Settings,
    served: Collection[str] | None = None,
) -> ModelResolution:
    """Perfil → modelo para o provider dado. Não vai à rede e não levanta.

    `served` é opcional porque o custo de descobrir o roster é uma ida à rede que
    o caminho de construção do provider não pode pagar: `_build_lmstudio` roda
    dentro de um `Depends`, e um LM Studio fora do ar transformaria toda
    requisição em timeout. Quem quer a resposta verificada (o endpoint de
    diagnóstico) busca o roster com `served_models()` e passa aqui.
    """
    return resolve_model(
        profile,
        provider,
        override=profile_override(provider, profile, settings),
        provider_default=provider_default_model(provider, settings),
        served=served,
    )


async def served_models(provider: str, settings: Settings) -> list[str] | None:
    """Ids que o provider diz servir agora, ou `None` se não deu para saber.

    `None` não é lista vazia: vazio afirmaria que o provider não serve nada e
    faria todo perfil degradar. Provider sem `list_models` (o `anthropic`) e
    provider fora do ar caem os dois em `None` — desconhecido.

    O `except Exception` é largo de propósito: esta função só alimenta um
    diagnóstico, e um roster que explode não pode derrubar a resposta que ele
    existia para explicar.
    """
    lister = getattr(build_llm_provider(provider, "", settings), "list_models", None)
    if lister is None:
        return None
    try:
        models = await lister()
    except LLMError:
        return None
    except Exception:  # noqa: BLE001 — diagnóstico nunca derruba o endpoint
        return None
    return [m for m in models if isinstance(m, str)] if isinstance(models, list) else None


def build_llm_provider(provider: str, model: str, settings: Settings) -> LLMProvider:
    """Resolve o provider pelo mapa. Desconhecido falha nomeando os válidos.

    Fora do FastAPI de propósito: o orchestrator monta provider sem requisição
    HTTP e precisa do mesmo caminho de resolução.
    """
    factory = PROVIDER_FACTORIES.get(provider)
    if factory is None:
        raise ValueError(
            f"Provider de LLM desconhecido: {provider!r}. "
            f"Válidos: {', '.join(valid_provider_ids())}."
        )
    return factory(settings, model)


def build_llm_provider_for_profile(
    profile: str,
    settings: Settings,
    *,
    provider: str | None = None,
    served: Collection[str] | None = None,
) -> LLMProvider:
    """Provider já apontado para o modelo do perfil. Nunca levanta por perfil.

    É a porta que os chamadores internos usam ("me dá um LLM para gerar código"),
    em vez de lerem `Settings.lmstudio_model` e escolherem sozinhos. Perfil
    desconhecido não é erro aqui: `resolve_model` degrada e loga, e a alternativa
    — 500 — trocaria um modelo pior por indisponibilidade total.
    """
    escolhido = provider or settings.chief_provider
    resolucao = resolve_profile_model(profile, escolhido, settings, served)
    return build_llm_provider(escolhido, resolucao.model, settings)


async def effective_provider_and_model(session: AsyncSession) -> tuple[str, str]:
    """Provider e modelo em vigor: o do banco, senão o do `.env`.

    Extraído de `get_llm_provider` para que o endpoint de diagnóstico responda
    sobre o MESMO provider que atende as gerações. Duas leituras independentes
    dessa escolha divergiriam no dia em que uma delas mudasse.
    """
    from sqlalchemy import select

    from apps.api.db.models import SystemSettingsRow

    stmt = select(SystemSettingsRow).where(SystemSettingsRow.id == 1)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()

    if row is None:
        # Sem linha persistida, modelo vazio: cada fábrica sabe o seu default.
        # Herdar `chief_model` aqui mandaria um modelo Anthropic para o Gemini.
        return get_settings().chief_provider, ""
    return row.provider, row.model


async def get_llm_provider(session: AsyncSession) -> LLMProvider:
    """Injeta provedor de LLM baseado nas configs do banco (ou .env)."""
    settings = get_settings()
    provider, model = await effective_provider_and_model(session)

    try:
        return build_llm_provider(provider, model, settings)
    except ValueError as exc:
        # A coluna `provider` é String livre: linha antiga ou escrita à mão pode
        # trazer valor morto. Vira 500 com a mensagem acionável em vez de
        # atender silenciosamente com o provider errado.
        raise HTTPException(status_code=500, detail=str(exc)) from exc


_MCP_MANAGER = None

async def get_mcp_manager():
    global _MCP_MANAGER
    if _MCP_MANAGER is None:
        from packages.mcp.client_manager import MCPClientManager
        from pathlib import Path
        mcp_dir = Path(os.path.dirname(__file__)).parent.parent / "mcp"
        mcp_dir.mkdir(exist_ok=True)
        _MCP_MANAGER = MCPClientManager(mcp_dir)
        await _MCP_MANAGER.discover_and_connect()
    return _MCP_MANAGER

async def get_tool_executor(session: AsyncSession) -> SystemToolExecutor:
    settings = get_settings()
    llm = await get_llm_provider(session)
    history_store = get_chat_history_store()
    memory_store = get_memory_vector_store()
    mcp_manager = await get_mcp_manager()
    embed_llm = None
    if settings.gemini_api_key:
        embed_llm = _build_gemini(settings, "")

    agno_knowledge = None
    try:
        from packages.rag.agno_knowledge import get_agno_knowledge
        agno_knowledge = get_agno_knowledge()
    except Exception as exc:
        import structlog
        logger = structlog.get_logger(__name__)
        logger.warning("deps.tool_executor.agno_knowledge.failed", error=str(exc))

    return SystemToolExecutor(
        tavily_api_key=settings.tavily_api_key,
        llm=llm,
        chat_history_store=history_store,
        mcp_manager=mcp_manager,
        memory_vector_store=memory_store,
        embed_llm=embed_llm,
        agno_knowledge=agno_knowledge,
    )

async def get_chief_ai(
    session: AsyncSession,
) -> ChiefAI:
    """Chief AI com todas as dependências injetadas."""
    settings = get_settings()
    llm = await get_llm_provider(session)
    tools = await get_tool_executor(session)
    conv_store = PgConversationStore(session)

    from sqlalchemy import select

    from apps.api.db.models import SystemSettingsRow

    stmt = select(SystemSettingsRow).where(SystemSettingsRow.id == 1)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    system_prompt = row.system_prompt if row and row.system_prompt else ""
    
    visual_instructions = """
Você tem suporte total a HTML e CSS (inline styles). Use tags HTML livremente para criar respostas visualmente atrativas, tabelas ricas, botões falsos, emotes ou até animações CSS quando fizer sentido para enriquecer a experiência do usuário. 
Você é uma IA multimodal avançada. Você PODE VER E ANALISAR imagens fornecidas pelo usuário em anexo. 
Se o usuário pedir para buscar uma imagem (ex: foto de animal, pessoa, lugar), USE A TOOL `web_search` para buscar na internet e exiba o resultado usando Markdown: `![descrição](url da imagem)`. Nunca diga que você não pode pesquisar ou ver imagens!
Se o usuário ajustar os filtros de uma imagem no frontend e pedir para salvá-la, use a tool `save_modified_image`.
"""
    system_prompt += visual_instructions

    # Provider dedicado para embeddings: sempre Gemini (tem API de embedding
    # gratuita e confiável). O provider de chat (ex: LM Studio com qwen/gemma)
    # frequentemente NÃO tem modelo de embedding carregado, o que faz o RAG
    # falhar silenciosamente e o agente alucinar.
    embed_llm = None
    if settings.gemini_api_key:
        embed_llm = _build_gemini(settings, "")

    # Inicializa Agno Knowledge (se falhar, loga erro e continua sem Agno)
    agno_knowledge = None
    try:
        from packages.rag.agno_knowledge import get_agno_knowledge
        agno_knowledge = get_agno_knowledge()
    except Exception as exc:
        import structlog
        logger = structlog.get_logger(__name__)
        logger.warning("deps.agno_knowledge.failed", error=str(exc))

    return ChiefAI(
        llm=llm,
        tools=tools,
        conversation_store=conv_store,
        system_prompt=system_prompt,
        chat_history_store=get_chat_history_store(),
        memory_vector_store=get_memory_vector_store(),
        embed_llm=embed_llm,
        agno_knowledge=agno_knowledge,
    )
