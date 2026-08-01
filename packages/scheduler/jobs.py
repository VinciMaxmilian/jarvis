"""Scheduler: os três jobs recorrentes da v1.4 (`plan-execution.md` §3, D-11).

    03:00  run_backup          pg_dump + snapshot do LanceDB  -> backup.completed
    04:00  cleanup_logs         log velho + short-memory vazada
    05:00  reindex_knowledge    diff por SHA-256 do corpus de knowledge

O `SchedulerManager` é **só orquestração**: cada job delega a um serviço
(`BackupService`, `CleanupService`, `ReindexService`) e converte o resultado
tipado em evento. Toda a lógica testável mora nos serviços; o que sobra aqui é o
que só o APScheduler exercita.

Regra de falha: um job **nunca** derruba o scheduler. Exceção vira log em `error`
e o job seguinte roda na hora dele — o oposto do D-6, onde `except Exception` com
`sleep` transformava falha permanente em loop silencioso. Aqui a falha é
terminal para *aquela execução*, aparece no log com a causa, e não emite evento
de sucesso.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import structlog

from packages.scheduler.backup import BackupService
from packages.scheduler.cleanup import CleanupService
from packages.scheduler.config import SchedulerConfig, resolve_path
from packages.scheduler.models import PostgresTarget
from packages.scheduler.ports import KnowledgeIndex, ShortTermKeyspace
from packages.scheduler.reindex import InMemoryKnowledgeIndex, ReindexService
from packages.scheduler.runner import AsyncSubprocessRunner
from packages.shared.contracts import Event, EventType
from packages.shared.ports import EventBus

if TYPE_CHECKING:
    # Só para tipo: o import real continua dentro de `start()`, atrás do
    # try/ImportError, porque o apscheduler é dependência opcional da v1.4.
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = structlog.get_logger(__name__)

#: `source` dos eventos emitidos daqui. Constante para que um consumidor possa
#: filtrar por origem sem casar string escrita à mão em três lugares.
EVENT_SOURCE = "packages.scheduler.jobs"


class SchedulerManager:
    """Registra e roda os jobs periódicos do sistema."""

    def __init__(
        self,
        *,
        event_bus: EventBus | None = None,
        backup: BackupService | None = None,
        cleanup: CleanupService | None = None,
        reindex: ReindexService | None = None,
        config: SchedulerConfig | None = None,
    ) -> None:
        # Anotado: sem isto o mypy infere o tipo `None` do valor inicial e marca
        # todo `add_job`/`start` abaixo como [attr-defined], deixando o módulo
        # inteiro fora da verificação real.
        self._scheduler: AsyncIOScheduler | None = None
        self._bus = event_bus
        self._backup = backup
        self._cleanup = cleanup
        self._reindex = reindex
        self._config = config or SchedulerConfig()

    # -- construção --------------------------------------------------------- #

    @classmethod
    def from_database_url(
        cls,
        database_url: str,
        *,
        event_bus: EventBus | None = None,
        config: SchedulerConfig | None = None,
        knowledge_index: KnowledgeIndex | None = None,
        short_term_keyspace: ShortTermKeyspace | None = None,
    ) -> SchedulerManager:
        """Monta os três serviços a partir do DSN da aplicação e do ambiente.

        Recebe o DSN em vez de `Settings` inteiro para não amarrar o scheduler ao
        objeto de configuração da app — quem chama já tem o `Settings` e passa o
        campo. `lancedb_path` sai de `SchedulerConfig` só se existir no disco; a
        ausência é tratada como caso normal pelo `BackupService`.
        """
        cfg = config or SchedulerConfig()
        alvo = PostgresTarget.from_dsn(database_url)
        runner = AsyncSubprocessRunner()

        lancedb = _lancedb_dir()

        return cls(
            event_bus=event_bus,
            config=cfg,
            backup=BackupService(
                target=alvo,
                backup_root=cfg.backup_root,
                runner=runner,
                lancedb_path=lancedb,
                pg_dump_argv=(cfg.pg_dump_bin,),
                retention=cfg.backup_retention,
                timeout_seconds=cfg.backup_timeout_seconds,
            ),
            cleanup=CleanupService(
                log_dir=cfg.log_dir,
                max_age_days=cfg.log_max_age_days,
                keyspace=short_term_keyspace,
                short_term_pattern=cfg.short_term_pattern,
            ),
            reindex=ReindexService(
                source_dir=cfg.knowledge_dir,
                index=knowledge_index or InMemoryKnowledgeIndex(),
            ),
        )

    # -- ciclo de vida ------------------------------------------------------ #

    def start(self) -> None:
        """Starts the APScheduler and registers jobs."""
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
        except ImportError:
            logger.error("scheduler.missing_dependency", dep="apscheduler")
            return

        cfg = self._config
        self._scheduler = AsyncIOScheduler()

        # `coalesce` + `max_instances=1`: máquina desligada a noite inteira faz o
        # APScheduler acumular disparos perdidos. Sem isso, ao religar ele tenta
        # rodar os backups atrasados todos de uma vez, em paralelo, contra o
        # mesmo banco. Um disparo, um backup.
        comum: dict[str, Any] = {
            "trigger": "cron",
            "minute": 0,
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 3600,
            "replace_existing": True,
        }
        self._scheduler.add_job(
            self.run_backup, id="jarvis.backup", hour=cfg.backup_hour, **comum
        )
        self._scheduler.add_job(
            self.cleanup_logs, id="jarvis.cleanup_logs", hour=cfg.cleanup_hour, **comum
        )
        self._scheduler.add_job(
            self.reindex_knowledge,
            id="jarvis.reindex_knowledge",
            hour=cfg.reindex_hour,
            **comum,
        )

        self._scheduler.start()
        logger.info(
            "scheduler.started",
            backup_hour=cfg.backup_hour,
            cleanup_hour=cfg.cleanup_hour,
            reindex_hour=cfg.reindex_hour,
            backup_root=str(cfg.backup_root),
        )

    def stop(self) -> None:
        """Stops the scheduler."""
        if self._scheduler:
            self._scheduler.shutdown()
            self._scheduler = None
            logger.info("scheduler.stopped")

    @property
    def running(self) -> bool:
        return self._scheduler is not None

    # -- jobs --------------------------------------------------------------- #

    async def run_backup(self) -> None:
        """Backup do Postgres (`pg_dump`) e do diretório do LanceDB.

        Emite `backup.completed` **só quando o backup existe e está íntegro**.
        Evento de sucesso emitido em cima de falha é pior do que evento nenhum:
        vira a prova falsa que faz o dono não olhar o backup por meses.
        """
        logger.info("scheduler.job.backup.started")
        if self._backup is None:
            logger.error("scheduler.job.backup.unavailable", reason="sem BackupService")
            return

        try:
            resultado = await self._backup.run()
        except Exception as exc:
            # Amplo de propósito: `pg_dump` ausente, disco cheio, permissão de
            # diretório e erro de rede chegam aqui como tipos diferentes, e
            # nenhum deles pode matar o scheduler inteiro.
            logger.error(
                "scheduler.job.backup.failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return

        manifesto = resultado.manifest
        await self._publish(
            Event(
                type=EventType.BACKUP_COMPLETED,
                source=EVENT_SOURCE,
                trace_id=uuid4().hex,
                payload={
                    "backup_id": manifesto.backup_id,
                    "root": resultado.root,
                    "database": manifesto.database,
                    "postgres_bytes": manifesto.postgres.bytes,
                    "postgres_sha256": manifesto.postgres.sha256,
                    "lancedb_files": (
                        manifesto.lancedb.files if manifesto.lancedb else 0
                    ),
                    "lancedb_bytes": (
                        manifesto.lancedb.bytes if manifesto.lancedb else 0
                    ),
                    "pruned": list(resultado.pruned),
                    "duration_seconds": resultado.duration_seconds,
                },
            )
        )
        logger.info(
            "scheduler.job.backup.completed",
            backup_id=manifesto.backup_id,
            root=resultado.root,
            total_bytes=resultado.total_bytes,
        )

    async def cleanup_logs(self) -> None:
        """Log antigo e chaves de short-term memory sem TTL."""
        logger.info("scheduler.job.cleanup_logs.started")
        if self._cleanup is None:
            logger.error(
                "scheduler.job.cleanup_logs.unavailable", reason="sem CleanupService"
            )
            return

        try:
            resultado = await self._cleanup.run()
        except Exception as exc:
            logger.error(
                "scheduler.job.cleanup_logs.failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return

        logger.info(
            "scheduler.job.cleanup_logs.completed",
            log_files_removed=resultado.log_files_removed,
            log_bytes_freed=resultado.log_bytes_freed,
            short_term_keys_removed=resultado.short_term_keys_removed,
        )

    async def reindex_knowledge(self) -> None:
        """Reindexação incremental do knowledge."""
        logger.info("scheduler.job.reindex_knowledge.started")
        if self._reindex is None:
            logger.error(
                "scheduler.job.reindex_knowledge.unavailable", reason="sem ReindexService"
            )
            return

        try:
            resultado = await self._reindex.run()
        except Exception as exc:
            logger.error(
                "scheduler.job.reindex_knowledge.failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return

        if resultado.changed:
            # `memory.updated` já existe no catálogo (`EventType`); o índice de
            # conhecimento mudar é exatamente o fato que ele nomeia. Sem mudança,
            # nenhum evento — bus não é lugar de anunciar que nada aconteceu.
            await self._publish(
                Event(
                    type=EventType.MEMORY_UPDATED,
                    source=EVENT_SOURCE,
                    trace_id=uuid4().hex,
                    payload={
                        "level": "knowledge",
                        "added": resultado.added,
                        "updated": resultado.updated,
                        "removed": resultado.removed,
                        "unchanged": resultado.unchanged,
                    },
                )
            )

        logger.info(
            "scheduler.job.reindex_knowledge.completed",
            scanned=resultado.scanned,
            changed=resultado.changed,
            skipped_reason=resultado.skipped_reason or None,
        )

    # -- interno ------------------------------------------------------------ #

    async def _publish(self, event: Event) -> None:
        """Publica no bus. Bus ausente ou com defeito não invalida o job feito."""
        if self._bus is None:
            logger.warning(
                "scheduler.event.dropped", type=event.type, reason="sem EventBus"
            )
            return
        try:
            await self._bus.publish(event)
        except Exception as exc:  # pragma: no cover — depende do transporte real
            logger.error(
                "scheduler.event.publish_failed", type=event.type, error=str(exc)
            )


def _lancedb_dir() -> Path | None:
    """Diretório de vetores, lido do ambiente **sem importar `lancedb`**.

    `LANCEDB_PATH` é a variável que `Settings.lancedb_path` já declara; lida
    daqui direto do ambiente para não obrigar o scheduler a construir o
    `Settings` inteiro (que derruba o processo se faltar `TAVILY_API_KEY`) só
    para descobrir um caminho de diretório.
    """
    bruto = os.environ.get("LANCEDB_PATH", "").strip()
    if not bruto:
        return None
    return resolve_path(bruto)


__all__ = ["EVENT_SOURCE", "SchedulerManager"]
