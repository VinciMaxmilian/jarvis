"""Capability Registry — catálogo, casamento de intenção e integridade.

Superfície pública do pacote. Quem consome importa daqui; os submódulos são
detalhe de organização e podem mudar de nome sem quebrar chamador.
"""

from packages.registry.exceptions import (
    CapabilityGapDetected,
    InvalidCapabilityStateError,
    ManifestLoadError,
    RegistryError,
)
from packages.registry.gap import GoalBlocker, gap_event
from packages.registry.integrity import (
    compute_capability_digest,
    integridade_confere,
)
from packages.registry.manifest import load_manifest
from packages.registry.matching import CatalogIndex, build_index, match_intent
from packages.registry.ports import CapabilityStore
from packages.registry.records import CapabilityHealth, CapabilityRecord
from packages.registry.registry import CapabilityRegistry, capability_id

__all__ = [
    "CapabilityGapDetected",
    "CapabilityHealth",
    "CapabilityRecord",
    "CapabilityRegistry",
    "CapabilityStore",
    "CatalogIndex",
    "GoalBlocker",
    "InvalidCapabilityStateError",
    "ManifestLoadError",
    "RegistryError",
    "build_index",
    "capability_id",
    "compute_capability_digest",
    "gap_event",
    "integridade_confere",
    "load_manifest",
    "match_intent",
]
