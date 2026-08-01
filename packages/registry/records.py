"""Estado do catálogo que precisa sobreviver a um restart.

Até a v1.1 o registry era um dicionário reconstruído por varredura de disco a
cada boot. Manifest sai do disco e continua saindo — ele é versionado junto com
o código. O que **não** está no disco é o estado operacional: quando a
capability foi usada pela última vez e se ela está saudável. Isso morria a cada
`docker compose restart`, e é o que a tabela `capabilities` guarda
(`plan-execution.md` §3, v1.1).

`CapabilityRecord` é a linha dessa tabela em forma de contrato. O adaptador
SQLAlchemy vive em `apps/api/db/repository.py`, atrás da porta `CapabilityStore`
— `packages/` não conhece ORM.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from packages.shared.contracts import CapabilityPermissions, CapabilityStatus


class CapabilityHealth(StrEnum):
    """Saúde observada em execução, distinta de `status`.

    `status` é decisão humana (o gate aprovou, o dono desligou); `health` é
    consequência medida (a última execução falhou). Misturar os dois faria uma
    falha de rede desaprovar uma capability, e uma aprovação apagar o histórico
    de falha.
    """

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILING = "failing"


class CapabilityRecord(BaseModel):
    """Uma linha da tabela `capabilities`."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    version: str
    #: `CapabilityManifest.runtime` — `python`, `mcp` ou `http`. Era `transport`
    #: até a v1.2; a coluna já tinha nascido com o nome final, então o rename do
    #: contrato não mexeu em dado gravado nem exigiu migration.
    runtime: str
    status: CapabilityStatus
    permissions: CapabilityPermissions = Field(default_factory=CapabilityPermissions)
    dependencies: list[str] = Field(default_factory=list)
    approved_commit: str | None = None
    health: CapabilityHealth = CapabilityHealth.UNKNOWN
    last_used_at: datetime | None = None


__all__ = ["CapabilityHealth", "CapabilityRecord"]
