"""Scheduler package — os três jobs recorrentes da v1.4.

Nada aqui importa `lancedb`: o snapshot do backup é cópia de diretório e a
reindexação fala com a porta `KnowledgeIndex`. Ver `packages/scheduler/ports.py`.
"""

from packages.scheduler.backup import (
    BackupError,
    BackupService,
    read_manifest,
    verify_backup,
)
from packages.scheduler.cleanup import CleanupService
from packages.scheduler.config import SchedulerConfig
from packages.scheduler.jobs import SchedulerManager
from packages.scheduler.models import (
    BackupManifest,
    BackupResult,
    CleanupResult,
    PostgresTarget,
    ReindexResult,
)
from packages.scheduler.ports import CommandRunner, KnowledgeIndex, ShortTermKeyspace
from packages.scheduler.reindex import InMemoryKnowledgeIndex, ReindexService
from packages.scheduler.runner import AsyncSubprocessRunner

__all__ = [
    "AsyncSubprocessRunner",
    "BackupError",
    "BackupManifest",
    "BackupResult",
    "BackupService",
    "CleanupResult",
    "CleanupService",
    "CommandRunner",
    "InMemoryKnowledgeIndex",
    "KnowledgeIndex",
    "PostgresTarget",
    "ReindexResult",
    "ReindexService",
    "SchedulerConfig",
    "SchedulerManager",
    "ShortTermKeyspace",
    "read_manifest",
    "verify_backup",
]
