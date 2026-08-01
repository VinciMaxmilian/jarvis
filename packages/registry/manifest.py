"""Carga e validação do `manifest.yaml` de uma capability.

Até a v1.2 este módulo devolvia um par (`LoadedManifest`): o `CapabilityManifest`
validado **mais** `trigger_intents`, que o YAML trazia e o contrato não declarava.
O par existia porque o pydantic descarta campo extra em silêncio, e o campo que
`plan.md` §6 usa para casar intenção não podia sumir entre o disco e o registry.

O campo virou contrato (`CapabilityManifest.trigger_intents`), então o par sumiu:
`load_manifest()` devolve o manifest e nada mais. Isso apaga a segunda leitura do
mesmo YAML — o Capability SDK tinha a dele, paralela, e duas leituras do mesmo
arquivo é a forma mais barata de as duas discordarem sem ninguém notar.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from packages.registry.exceptions import ManifestLoadError
from packages.shared.contracts import CapabilityManifest


def _ler_yaml(path: str | Path) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError as exc:
        raise ManifestLoadError(f"Manifest não encontrado: {path}") from exc
    except yaml.YAMLError as exc:
        raise ManifestLoadError(f"YAML inválido em {path}: {exc}") from exc

    if not data:
        raise ManifestLoadError(f"Manifest vazio em {path}")
    if not isinstance(data, dict):
        raise ManifestLoadError(
            f"Manifest em {path} deve ser um mapa, veio {type(data).__name__}"
        )
    return data


def load_manifest(path: str | Path) -> CapabilityManifest:
    """Carrega um `CapabilityManifest` de um arquivo YAML.

    A chave legada `trigger_intent` (singular) continua carregando: quem a
    traduz é o próprio contrato, num só lugar, e não cada leitor do arquivo.

    Raises:
        ManifestLoadError: arquivo ausente, YAML inválido ou schema inválido.
    """
    data = _ler_yaml(path)
    try:
        return CapabilityManifest.model_validate(data)
    except Exception as exc:
        raise ManifestLoadError(f"Schema inválido em {path}: {exc}") from exc


__all__ = ["load_manifest"]
