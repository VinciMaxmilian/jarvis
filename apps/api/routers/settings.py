"""Router para as configurações dinâmicas de sistema."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.models import SystemSettingsRow
from apps.api.deps import (
    effective_provider_and_model,
    get_db,
    provider_default_model,
    resolve_profile_model,
    served_models,
    valid_provider_ids,
)
from packages.llm.profiles import FALLBACK_MODEL, TASK_PROFILES
from packages.shared.contracts import SystemSettings
from packages.shared.settings import get_settings as get_app_settings

router = APIRouter(tags=["settings"])


class ProviderOption(BaseModel):
    """Um provider oferecível na UI, com o modelo que ele espera por default."""

    id: str
    default_model: str


class ProviderCatalog(BaseModel):
    """Catálogo de providers atendíveis agora."""

    providers: list[ProviderOption]


class ProfileAssignment(BaseModel):
    """Que modelo está servindo um perfil de tarefa, e por quê."""

    profile: str
    model: str
    source: str
    degraded: bool
    reason: str


class ProfileCatalog(BaseModel):
    """Resolução perfil → modelo para o provider em vigor.

    `roster_available=False` significa que não deu para perguntar ao provider o
    que ele serve (fora do ar, ou sem endpoint de listagem). A resposta continua
    válida — é a mesma resolução que as gerações usam —, mas não foi verificada,
    e a UI precisa poder dizer isso em vez de exibir uma certeza que não existe.
    """

    provider: str
    roster_available: bool
    fallback_model: str
    profiles: list[ProfileAssignment]


@router.get("/providers", response_model=ProviderCatalog)
async def list_providers() -> ProviderCatalog:
    """Providers válidos, derivados do mapa de fábricas do `deps.py`.

    Existe para que o frontend não carregue lista hardcoded: somar provider é uma
    entrada no mapa e a UI acompanha sozinha. O `default_model` vai junto porque
    trocar de provider mantendo o modelo do anterior é o erro mais fácil de
    cometer na tela de configurações.
    """
    return ProviderCatalog(
        providers=[
            ProviderOption(id=pid, default_model=provider_default_model(pid))
            for pid in valid_provider_ids()
        ]
    )


@router.get("/profiles", response_model=ProfileCatalog)
async def list_profiles(session: AsyncSession = Depends(get_db)) -> ProfileCatalog:
    """Quem está servindo o quê, verificado contra o roster real do provider.

    **Endpoint separado de `/providers`, e não um campo a mais nele.** Os dois
    respondem perguntas diferentes com custos diferentes: `/providers` responde "o
    que posso escolher", é puro mapa em memória e nunca falha; este responde "o
    que está servindo agora", e para isso precisa PERGUNTAR ao provider — uma ida
    à rede que pode demorar ou falhar. Fundir os dois faria o seletor de provider
    do PWA travar quando o LM Studio estivesse desligado, por um motivo que não
    tem nada a ver com o seletor de provider. Domínios de falha separados.

    Não usa `Depends(get_llm_provider)`: aqui a resolução é o assunto, e construir
    o provider da conversa para depois ignorá-lo confundiria as duas coisas.
    """
    settings = get_app_settings()
    provider, _ = await effective_provider_and_model(session)

    if provider not in valid_provider_ids():
        # Mesma checagem (e mesma mensagem) do GET "/": a coluna é String livre e
        # um provider morto aqui viraria um ValueError de `build_llm_provider`
        # disfarçado de erro de roster, três funções longe da causa.
        raise HTTPException(
            status_code=500,
            detail=(
                f"Provider persistido inválido: {provider!r}. "
                f"Válidos: {', '.join(valid_provider_ids())}."
            ),
        )

    roster = await served_models(provider, settings)
    atribuicoes: list[ProfileAssignment] = []
    for profile in TASK_PROFILES:
        res = resolve_profile_model(profile, provider, settings, roster)
        atribuicoes.append(
            ProfileAssignment(
                profile=profile,
                model=res.model,
                source=res.source,
                degraded=res.degraded,
                reason=res.reason,
            )
        )

    return ProfileCatalog(
        provider=provider,
        roster_available=roster is not None,
        fallback_model=FALLBACK_MODEL,
        profiles=atribuicoes,
    )


@router.get("/", response_model=SystemSettings)
async def get_settings(session: AsyncSession = Depends(get_db)) -> SystemSettings:
    """Busca as configurações do banco ou retorna o default se vazio."""
    stmt = select(SystemSettingsRow).where(SystemSettingsRow.id == 1)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()

    if not row:
        return SystemSettings()

    if row.provider not in valid_provider_ids():
        # A coluna é String livre: linha antiga pode citar provider já removido.
        # Melhor dizer qual valor está lá do que devolver default e mentir.
        raise HTTPException(
            status_code=500,
            detail=(
                f"Provider persistido inválido: {row.provider!r}. "
                f"Válidos: {', '.join(valid_provider_ids())}."
            ),
        )

    return SystemSettings(
        provider=row.provider,  # type: ignore[arg-type]  # validado logo acima
        model=row.model,
        temperature=row.temperature,
        system_prompt=row.system_prompt,
    )


@router.put("/", response_model=SystemSettings)
async def update_settings(
    settings: SystemSettings, session: AsyncSession = Depends(get_db)
) -> SystemSettings:
    """Atualiza as configurações (singleton id=1).

    `settings.provider` já passou pelo Literal `ProviderId` do pydantic, então
    valor fora do contrato vira 422 antes de chegar aqui. A checagem contra o mapa
    de fábricas cobre o resto: provider declarado no contrato mas sem fábrica
    registrada seria aceito e só quebraria na primeira geração.
    """
    if settings.provider not in valid_provider_ids():
        raise HTTPException(
            status_code=422,
            detail=(
                f"Provider sem implementação registrada: {settings.provider!r}. "
                f"Válidos: {', '.join(valid_provider_ids())}."
            ),
        )

    stmt = select(SystemSettingsRow).where(SystemSettingsRow.id == 1)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()

    if not row:
        row = SystemSettingsRow(id=1)
        session.add(row)

    row.provider = settings.provider
    # Modelo vazio cai no default do provider escolhido; sem isso, trocar para
    # `ollama` deixaria um modelo de API remota persistido e a geração falharia.
    row.model = settings.model or provider_default_model(settings.provider)
    row.temperature = settings.temperature
    row.system_prompt = settings.system_prompt

    await session.flush()

    return SystemSettings(
        provider=settings.provider,
        model=row.model,
        temperature=row.temperature,
        system_prompt=row.system_prompt,
    )
