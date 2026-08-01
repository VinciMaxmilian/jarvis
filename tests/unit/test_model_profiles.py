"""Perfil de tarefa → modelo, e o `embed()` do provider OpenAI-compatible.

O que está sendo protegido aqui não é a tabela de perfis — é a DEGRADAÇÃO. O dono
tem duas máquinas: a do trabalho serve o LM Studio com o roster medido abaixo; a
de casa vai usar o Gemini e não tem nenhum daqueles modelos. Um mapa de perfis que
só funciona na máquina onde foi escrito é pior do que não ter mapa: falha longe da
causa, na primeira geração, com um 404 que não explica nada.

Nada aqui vai à rede. O roster é uma constante medida uma vez, e o `embed()` fala
com um `httpx.MockTransport` — teste de camada de LLM que depende de um servidor
ligado é teste que some do CI e volta como bug.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any, Final
from unittest import mock

import httpx
import pytest

from apps.api.deps import (
    build_llm_provider,
    build_llm_provider_for_profile,
    profile_override,
    resolve_profile_model,
)
from packages.llm.base import UnsupportedOperation
from packages.llm.openai_provider import OpenAIProvider
from packages.llm.profiles import (
    FALLBACK_MODEL,
    PROFILE_MODELS,
    TASK_PROFILES,
    profile_env_var,
    resolve_model,
)
from packages.shared.settings import Settings

#: Roster REAL do LM Studio da LAN, medido em `GET /api/v0/models`
#: (http://192.168.11.189:1234) na sessão em que este módulo foi escrito. É a
#: única fonte de verdade que temos sobre os ids: uma letra errada em
#: `PROFILE_MODELS` não dá erro de sintaxe nem de tipo, só um 404 em produção.
ROSTER_LMSTUDIO: Final = frozenset(
    {
        "google/gemma-4-e2b",
        "qwen3-vl-8b-instruct",
        "qwen3-reranker-0.6b",
        "text-embedding-qwen3-embedding-0.6b",
        "deepseek-coder-v2-lite-instruct",
        "paddleocr-vl-1.6",
        "phi-3.5-vision-instruct",
        "whisper-large-v3-turbo",
        "kokoro_gguf",
        "text-embedding-nomic-embed-text-v1.5",
    }
)

#: Roster plausível da máquina de casa: Gemini, nenhum modelo do LM Studio.
ROSTER_GEMINI: Final = frozenset(
    {"gemini-2.5-flash", "gemini-2.5-pro", "text-embedding-004"}
)


def _settings(**overrides: object) -> Settings:
    """Config mínima válida; o resto vem do default, que é o que queremos exercitar."""
    base: dict[str, object] = {
        "database_url": "postgresql+asyncpg://u:p@localhost:5432/db",
        "tavily_api_key": "tvly-test",
    }
    base.update(overrides)
    # Hermético: ver a nota igual em tests/unit/test_providers.py. O `.env` do
    # dono chega ao container pelo `env_file:` do Compose e sobrescreveria o
    # default que este arquivo existe para exercitar.
    with mock.patch.dict(os.environ, {}, clear=True):
        return Settings(_env_file=None, **base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# O mapa em si
# --------------------------------------------------------------------------- #


def test_todo_perfil_declarado_tem_modelo_no_lmstudio() -> None:
    """Perfil no `Literal` sem entrada no mapa cairia no fallback em silêncio —
    o dono acharia que configurou e o gemma responderia tudo."""
    assert frozenset(PROFILE_MODELS["lmstudio"]) == frozenset(TASK_PROFILES)


@pytest.mark.parametrize("profile", TASK_PROFILES)
def test_modelo_mapeado_existe_no_roster_medido(profile: str) -> None:
    """Guarda contra erro de digitação no id. É o único jeito de checar isso sem
    ligar para a LAN, e ids como `text-embedding-qwen3-embedding-0.6b` são
    exatamente o tipo de string que ninguém revisa direito."""
    assert PROFILE_MODELS["lmstudio"][profile] in ROSTER_LMSTUDIO


def test_fallback_declarado_esta_no_roster() -> None:
    assert FALLBACK_MODEL in ROSTER_LMSTUDIO


def test_so_o_lmstudio_tem_mapa_de_perfis() -> None:
    """`openai`/`local` apontam para outro backend e `gemini` é outra API. Herdar
    ids do LM Studio ali seria escolher errado em silêncio — o cenário que este
    módulo inteiro existe para impedir."""
    assert set(PROFILE_MODELS) == {"lmstudio"}


# --------------------------------------------------------------------------- #
# Resolução — o caminho feliz e as quatro degradações
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("profile", TASK_PROFILES)
def test_perfil_resolve_para_o_modelo_mapeado(profile: str) -> None:
    res = resolve_profile_model(profile, "lmstudio", _settings(), ROSTER_LMSTUDIO)
    assert res.model == PROFILE_MODELS["lmstudio"][profile]
    assert res.source == "profile_map"
    assert res.degraded is False


def test_chief_e_vision_pegam_o_modelo_de_maior_contexto() -> None:
    """A justificativa da tabela, verificada: `chief` planeja e `vision` lê tela,
    e os dois querem os 262144 do qwen3-vl, não os 131072 do gemma."""
    settings = _settings()
    for profile in ("chief", "vision"):
        res = resolve_profile_model(profile, "lmstudio", settings, ROSTER_LMSTUDIO)
        assert res.model == "qwen3-vl-8b-instruct"


def test_code_vai_para_o_deepseek_mesmo_estando_frio() -> None:
    """`state=not-loaded` é latência no primeiro request (o LM Studio carrega sob
    demanda), não indisponibilidade: o id está no roster e é o que vale."""
    res = resolve_profile_model("code", "lmstudio", _settings(), ROSTER_LMSTUDIO)
    assert res.model == "deepseek-coder-v2-lite-instruct"


def test_perfil_desconhecido_cai_no_gemma() -> None:
    res = resolve_profile_model(
        "perfil-que-nao-existe", "lmstudio", _settings(), ROSTER_LMSTUDIO
    )
    assert res.model == FALLBACK_MODEL
    assert res.source == "fallback"
    assert res.degraded is True
    assert "não está mapeado" in res.reason


def test_modelo_ausente_do_roster_cai_no_gemma() -> None:
    """O caso do dia a dia: o dono apaga o deepseek do LM Studio. O perfil `code`
    tem de continuar respondendo, pior porém vivo, e dizer por quê."""
    roster = ROSTER_LMSTUDIO - {"deepseek-coder-v2-lite-instruct"}
    res = resolve_profile_model("code", "lmstudio", _settings(), roster)
    assert res.model == FALLBACK_MODEL
    assert res.source == "fallback"
    assert res.degraded is True
    assert "deepseek-coder-v2-lite-instruct" in res.reason


def test_sem_gemma_no_roster_cai_no_default_do_provider() -> None:
    """Fim da cadeia: nem o mapeado nem o fallback estão lá."""
    roster = {"algum-modelo-que-o-dono-baixou"}
    res = resolve_profile_model("code", "lmstudio", _settings(), roster)
    assert res.model == _settings().lmstudio_model
    assert res.source == "provider_default"
    assert res.degraded is True


def test_roster_desconhecido_confia_no_mapa_mas_nao_no_gemma() -> None:
    """`served=None` é "não sei", não "não tem". O modelo mapeado PARA ESTE
    provider vale por confiança; o fallback global, não — é o que impede a
    máquina de casa de receber um id do LM Studio."""
    res = resolve_profile_model("code", "lmstudio", _settings(), None)
    assert res.model == "deepseek-coder-v2-lite-instruct"
    assert res.source == "profile_map"


# --------------------------------------------------------------------------- #
# A máquina de casa: Gemini, zero configuração de LM Studio
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("profile", TASK_PROFILES)
def test_gemini_resolve_todo_perfil_sem_nenhuma_config_de_lmstudio(profile: str) -> None:
    """CHIEF_PROVIDER=gemini tem de ser configuração completa. Nenhum perfil pode
    levantar, e nenhum id do LM Studio pode vazar para a resposta."""
    settings = _settings(chief_provider="gemini", gemini_api_key="k")
    res = resolve_profile_model(profile, "gemini", settings, ROSTER_GEMINI)
    assert res.model == settings.gemini_model
    assert res.source == "provider_default"
    assert res.model not in ROSTER_LMSTUDIO


@pytest.mark.parametrize("profile", TASK_PROFILES)
def test_gemini_offline_tambem_resolve_e_nunca_devolve_gemma(profile: str) -> None:
    """Sem roster (Gemini fora do ar, ou ninguém quis pagar a ida à rede) o
    fallback global continua proibido: `google/gemma-4-e2b` não existe na API do
    Google e escolhê-lo seria trocar "sem verificação" por "errado"."""
    settings = _settings(chief_provider="gemini", gemini_api_key="k")
    res = resolve_profile_model(profile, "gemini", settings, None)
    assert res.model == settings.gemini_model
    assert res.model != FALLBACK_MODEL


def test_build_para_perfil_no_gemini_constroi_sem_rede() -> None:
    settings = _settings(chief_provider="gemini", gemini_api_key="k")
    llm = build_llm_provider_for_profile("code", settings)
    assert llm.name == "gemini"
    assert llm.model == settings.gemini_model


@pytest.mark.parametrize("profile", TASK_PROFILES)
def test_build_para_perfil_no_lmstudio_aponta_o_modelo_do_perfil(profile: str) -> None:
    settings = _settings()
    llm = build_llm_provider_for_profile(profile, settings, provider="lmstudio")
    assert llm.model == PROFILE_MODELS["lmstudio"][profile]


def test_perfil_desconhecido_nao_levanta_no_build() -> None:
    """Requisito duro: perfil que não dá para servir degrada, nunca derruba."""
    llm = build_llm_provider_for_profile("nao-existe", _settings(), provider="lmstudio")
    assert llm.model  # sobrou o default do provider, não vazio


# --------------------------------------------------------------------------- #
# Override do dono
# --------------------------------------------------------------------------- #


def test_override_do_env_vence_o_mapa() -> None:
    settings = _settings(lmstudio_model_code="phi-3.5-vision-instruct")
    res = resolve_profile_model("code", "lmstudio", settings, ROSTER_LMSTUDIO)
    assert res.model == "phi-3.5-vision-instruct"
    assert res.source == "override"
    assert res.degraded is False


def test_override_com_id_errado_nao_e_obedecido_em_silencio() -> None:
    """Erro de digitação no .env viraria 404 na primeira geração. Cai para o mapa
    e o motivo cita a variável, que é o que o dono precisa para consertar."""
    settings = _settings(lmstudio_model_code="deepsek-coder")  # falta um 'e'
    res = resolve_profile_model("code", "lmstudio", settings, ROSTER_LMSTUDIO)
    assert res.model == "deepseek-coder-v2-lite-instruct"
    assert res.source == "profile_map"
    assert res.degraded is True
    assert "LMSTUDIO_MODEL_CODE" in res.reason


@pytest.mark.parametrize("profile", TASK_PROFILES)
def test_todo_perfil_tem_variavel_de_override_declarada(profile: str) -> None:
    """A convenção de nome é usada por `getattr` dinâmico; campo faltando em
    `Settings` faria o override do dono ser ignorado sem aviso nenhum."""
    settings = _settings(**{f"lmstudio_model_{profile}": "x"})
    assert profile_override("lmstudio", profile, settings) == "x"
    assert profile_env_var("lmstudio", profile) == f"LMSTUDIO_MODEL_{profile.upper()}"


def test_gemini_nao_tem_variavel_de_override_e_isso_e_ok() -> None:
    settings = _settings(chief_provider="gemini", gemini_api_key="k")
    assert profile_override("gemini", "code", settings) == ""


def test_resolve_model_e_funcao_pura_sem_settings() -> None:
    """A camada `packages/llm` não pode depender de `.env` para resolver perfil —
    é o que permite ao orchestrator usar a mesma resolução sem passar por HTTP."""
    res = resolve_model(
        "chief", "lmstudio", provider_default="x", served=ROSTER_LMSTUDIO
    )
    assert res.model == "qwen3-vl-8b-instruct"


# --------------------------------------------------------------------------- #
# embed() — HTTP mockado, nunca a LAN
# --------------------------------------------------------------------------- #

#: Dimensão medida em `POST /v1/embeddings` com o modelo do perfil `embed`.
EMBED_DIMS: Final = 1024


def _mock_provider(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    model: str = "chat-model",
    embed_model: str | None = None,
) -> tuple[OpenAIProvider, list[httpx.Request]]:
    """Provider com transporte falso. Devolve também as requisições vistas: o que
    interessa em metade destes testes é QUAL modelo foi pedido, não o que voltou.
    """
    vistas: list[httpx.Request] = []

    def _intercepta(request: httpx.Request) -> httpx.Response:
        vistas.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(_intercepta))
    provider = OpenAIProvider(
        api_key="lm-studio",
        base_url="http://192.168.11.189:1234/v1",
        model=model,
        embed_model=embed_model,
        http_client=client,
    )
    return provider, vistas


def _resposta_embeddings(
    request: httpx.Request, *, dims: int = EMBED_DIMS
) -> httpx.Response:
    """Resposta com a MESMA forma medida no LM Studio, inclusive `index`."""
    body = json.loads(request.content)
    entradas = body["input"]
    return httpx.Response(
        200,
        json={
            "object": "list",
            "model": body["model"],
            "data": [
                {"object": "embedding", "index": i, "embedding": [0.1 * i] * dims}
                for i, _ in enumerate(entradas)
            ],
            "usage": {"prompt_tokens": 0, "total_tokens": 0},
        },
    )


async def test_embed_devolve_um_vetor_por_texto_na_dimensao_certa() -> None:
    provider, _ = _mock_provider(_resposta_embeddings)
    vetores = await provider.embed(["ola", "mundo"])
    assert len(vetores) == 2
    assert all(len(v) == EMBED_DIMS for v in vetores)
    assert all(isinstance(x, float) for x in vetores[0])


async def test_embed_usa_o_modelo_do_perfil_embed_e_nao_o_de_chat() -> None:
    """O bug que isto trava: `embed()` indo para o modelo de conversa. No LM Studio
    os dois são `type` diferentes e a resposta seria 400 — ou pior, um vetor de
    dimensão inesperada."""
    provider, vistas = _mock_provider(
        _resposta_embeddings,
        model="qwen3-vl-8b-instruct",
        embed_model="text-embedding-qwen3-embedding-0.6b",
    )
    await provider.embed(["ola"])
    assert json.loads(vistas[0].content)["model"] == "text-embedding-qwen3-embedding-0.6b"


async def test_embed_sem_embed_model_cai_no_modelo_de_chat() -> None:
    provider, vistas = _mock_provider(_resposta_embeddings, model="so-esse")
    await provider.embed(["ola"])
    assert json.loads(vistas[0].content)["model"] == "so-esse"


async def test_embed_de_lista_vazia_nao_toca_na_rede() -> None:
    """Alguns backends respondem 400 a `input: []`; um erro fantasma por lista
    vazia é o tipo de coisa que se debuga uma vez e nunca se esquece."""
    provider, vistas = _mock_provider(_resposta_embeddings)
    assert await provider.embed([]) == []
    assert vistas == []


async def test_embed_preserva_a_ordem_dos_textos() -> None:
    """A especificação permite devolver fora de ordem; vetor casado com o texto
    errado não dá erro, só piora a busca de um jeito que ninguém rastreia."""

    def _fora_de_ordem(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": "m",
                "data": [
                    {"object": "embedding", "index": 1, "embedding": [1.0, 1.0]},
                    {"object": "embedding", "index": 0, "embedding": [0.0, 0.0]},
                ],
            },
        )

    provider, _ = _mock_provider(_fora_de_ordem)
    vetores = await provider.embed(["primeiro", "segundo"])
    assert vetores == [[0.0, 0.0], [1.0, 1.0]]


async def test_embed_em_backend_sem_a_rota_vira_unsupported_operation() -> None:
    """Era esta a preocupação do comentário antigo: backend compatível que não
    serve embeddings. Continua atendida — mas como erro nomeado, não como recusa
    a priori de uma capacidade que o LM Studio tem."""

    def _sem_rota(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "Unexpected endpoint"}})

    provider, _ = _mock_provider(_sem_rota)
    with pytest.raises(UnsupportedOperation) as exc:
        await provider.embed(["ola"])
    assert "192.168.11.189" in str(exc.value)


async def test_embed_com_modelo_de_geracao_vira_unsupported_operation() -> None:
    def _modelo_errado(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"message": "Model does not support embeddings"}},
        )

    provider, _ = _mock_provider(_modelo_errado, model="qwen3-vl-8b-instruct")
    with pytest.raises(UnsupportedOperation) as exc:
        await provider.embed(["ola"])
    assert "qwen3-vl-8b-instruct" in str(exc.value)


async def test_list_models_devolve_o_roster_do_backend() -> None:
    """É a fonte do `served` da resolução de perfil."""

    def _roster(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"id": mid, "object": "model"} for mid in sorted(ROSTER_LMSTUDIO)
                ],
            },
        )

    provider, _ = _mock_provider(_roster)
    assert frozenset(await provider.list_models()) == ROSTER_LMSTUDIO


# --------------------------------------------------------------------------- #
# GET /api/settings/profiles — o diagnóstico que o PWA lê
# --------------------------------------------------------------------------- #


class _FakeResult:
    def __init__(self, row: object) -> None:
        self._row = row

    def scalar_one_or_none(self) -> object:
        return self._row


class _FakeSession:
    """Só o suficiente para `effective_provider_and_model`. Sem Postgres: o
    assunto do teste é a resolução, não o ORM."""

    def __init__(self, row: object = None) -> None:
        self._row = row

    async def execute(self, stmt: object) -> _FakeResult:
        return _FakeResult(self._row)


async def test_endpoint_de_perfis_mostra_quem_serve_o_que(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api import deps as deps_mod
    from apps.api.routers import settings as router_mod

    monkeypatch.setattr(router_mod, "get_app_settings", _settings)
    # `effective_provider_and_model` vive em `deps` e resolve o provider pelo
    # `get_settings()` de lá, não pelo nome importado no router. Sem este patch o
    # teste lê o CHIEF_PROVIDER real da máquina do dono em vez do default.
    monkeypatch.setattr(deps_mod, "get_settings", _settings)
    monkeypatch.setattr(
        router_mod, "served_models", lambda p, s: _async(sorted(ROSTER_LMSTUDIO))
    )

    catalogo = await router_mod.list_profiles(_FakeSession())  # type: ignore[arg-type]

    assert catalogo.provider == "lmstudio"
    assert catalogo.roster_available is True
    assert catalogo.fallback_model == FALLBACK_MODEL
    por_perfil = {p.profile: p.model for p in catalogo.profiles}
    assert por_perfil == dict(PROFILE_MODELS["lmstudio"])
    assert not any(p.degraded for p in catalogo.profiles)


async def test_endpoint_de_perfis_responde_com_provider_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LM Studio desligado não pode virar 500: o dono consulta esta tela
    justamente quando algo está errado."""
    from apps.api.routers import settings as router_mod

    monkeypatch.setattr(router_mod, "get_app_settings", _settings)
    monkeypatch.setattr(router_mod, "served_models", lambda p, s: _async(None))

    catalogo = await router_mod.list_profiles(_FakeSession())  # type: ignore[arg-type]

    assert catalogo.roster_available is False
    assert len(catalogo.profiles) == len(TASK_PROFILES)


async def _async(value: Any) -> Any:
    return value


def test_fabrica_do_lmstudio_aponta_embed_para_o_modelo_de_embedding() -> None:
    """A ponta solta que faria tudo acima ser teoria: a fábrica do `deps.py` tem
    de passar o modelo do perfil `embed` para o provider que ela constrói."""
    llm = build_llm_provider("lmstudio", "", _settings())
    assert isinstance(llm, OpenAIProvider)
    assert llm.model == "google/gemma-4-e2b"  # chat: escolha do dono
    assert llm._embed_model == "text-embedding-qwen3-embedding-0.6b"
