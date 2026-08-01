"""Contrato do mapa de providers de LLM (`apps/api/deps.py`).

Cobre a fronteira que já quebrou uma vez: o `Literal ProviderId`, o mapa de
fábricas e a tabela de modelo default são três listas que precisam concordar.
`deps.py` derruba a app no import quando as duas primeiras divergem — aqui
verificamos que essa guarda existe de verdade, e cobrimos a terceira, que
ninguém checava.

Nada aqui faz chamada de rede: construir um provider é instanciar um cliente,
não falar com ele.
"""

from __future__ import annotations

import os
from typing import get_args
from unittest import mock

import pytest

from apps.api.deps import (
    PROVIDER_DEFAULT_MODEL_ATTR,
    PROVIDER_FACTORIES,
    build_llm_provider,
    provider_default_model,
    valid_provider_ids,
)
from packages.shared.contracts import ProviderId, SystemSettings
from packages.shared.settings import Settings


#: Config mínima válida. `Settings` exige DATABASE_URL async e TAVILY_API_KEY;
#: o resto vem do default, que é justamente o que queremos exercitar.
def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "postgresql+asyncpg://u:p@localhost:5432/db",
        "tavily_api_key": "tvly-test",
    }
    base.update(overrides)
    # Hermético de propósito. `Settings` lê os.environ, e o `.env` do dono entra
    # no container de teste pelo `env_file:` do Compose. Sem limpar, um
    # CHIEF_PROVIDER=anthropic na máquina dele reprova o teste de default: o
    # teste passaria a medir a configuração da máquina, não o default declarado.
    # `_env_file=None` desliga o DotEnvSettingsSource: o repo inteiro é montado
    # em /app no container de teste, então o `.env` do dono está lá para ser lido.
    with mock.patch.dict(os.environ, {}, clear=True):
        return Settings(_env_file=None, **base)  # type: ignore[arg-type]


def test_contrato_e_mapa_de_fabricas_nao_divergem() -> None:
    """A guarda de import de `deps.py`, verificada em vez de assumida."""
    assert frozenset(get_args(ProviderId)) == frozenset(PROVIDER_FACTORIES)


def test_todo_provider_tem_modelo_default_declarado() -> None:
    """A terceira lista. Sem isto, a UI troca de provider e mantém o modelo do
    anterior — falha só na primeira geração, longe da causa."""
    assert frozenset(PROVIDER_DEFAULT_MODEL_ATTR) == frozenset(PROVIDER_FACTORIES)


@pytest.mark.parametrize("provider", sorted(get_args(ProviderId)))
def test_modelo_default_resolve_para_string_nao_vazia(provider: str) -> None:
    assert provider_default_model(provider, _settings())


@pytest.mark.parametrize("provider", sorted(get_args(ProviderId)))
def test_toda_fabrica_constroi_sem_rede(provider: str) -> None:
    llm = build_llm_provider(provider, "", _settings())
    assert llm.model, f"{provider} construiu sem modelo resolvido"


def test_provider_desconhecido_falha_nomeando_os_validos() -> None:
    with pytest.raises(ValueError) as exc:
        build_llm_provider("nao-existe", "", _settings())
    msg = str(exc.value)
    assert "nao-existe" in msg
    for pid in valid_provider_ids():
        assert pid in msg, f"mensagem de erro omite {pid}"


def test_ordem_de_preferencia_e_a_do_mapa() -> None:
    """A ordem é contrato de UI, não detalhe: `valid_provider_ids()` alimenta o
    catálogo e a primeira entrada é o que o dono vê primeiro."""
    assert valid_provider_ids() == list(PROVIDER_FACTORIES)
    assert valid_provider_ids()[0] == "lmstudio"


def test_default_de_boot_e_de_banco_concordam() -> None:
    """`Settings.chief_provider` e `SystemSettings.provider` são o mesmo default
    visto de dois lugares. Divergir faz o sistema mudar de provider ao gravar a
    primeira linha de configuração, sem ninguém ter escolhido."""
    assert _settings().chief_provider == SystemSettings().provider


def test_lmstudio_usa_a_propria_base_url_e_nao_a_do_openai() -> None:
    """Foi por isso que `lmstudio` virou entrada própria: apontar o LM Studio
    reaproveitando OPENAI_BASE_URL tornava impossível ter os dois configurados.
    """
    settings = _settings(
        lmstudio_base_url="http://10.0.0.9:1234/v1",
        lmstudio_model="modelo-local",
        openai_base_url="https://api.openai.com/v1",
    )
    lmstudio = build_llm_provider("lmstudio", "", settings)
    openai = build_llm_provider("openai", "", settings)

    assert lmstudio.model == "modelo-local"
    assert openai.model == settings.chief_model
    assert lmstudio.model != openai.model


def test_modelo_explicito_vence_o_default_do_provider() -> None:
    llm = build_llm_provider("lmstudio", "outro-modelo", _settings())
    assert llm.model == "outro-modelo"
