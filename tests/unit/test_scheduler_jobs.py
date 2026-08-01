"""`SchedulerManager` — os três jobs e o que eles publicam no `EventBus`.

O aceite da v1.4 (`plan-execution.md` §3) começa com "backup roda sozinho e
emite `backup.completed`". A metade "emite" é verificável aqui; a metade "roda
sozinho" é o `start()`, que registra os três jobs no APScheduler.

O bus é o `InMemoryEventBus` do `conftest.py`, que grava tudo — sem registro do
publicado, "emitiu o evento" não é afirmação verificável.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from packages.scheduler.backup import BackupError, BackupService
from packages.scheduler.cleanup import CleanupService
from packages.scheduler.config import SchedulerConfig
from packages.scheduler.jobs import EVENT_SOURCE, SchedulerManager
from packages.scheduler.models import CommandResult, PostgresTarget
from packages.scheduler.reindex import InMemoryKnowledgeIndex, ReindexService
from packages.shared.contracts import EventType
from packages.shared.ports import EventBus
from tests.conftest import InMemoryEventBus

INSTANTE = datetime(2026, 7, 30, 3, 0, 0, tzinfo=UTC)


class DumpQueEscreve:
    """`CommandRunner` mínimo: escreve o arquivo pedido e devolve sucesso."""

    def __init__(self, *, returncode: int = 0) -> None:
        self.returncode = returncode

    async def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        comando = tuple(argv)
        if self.returncode == 0:
            Path(comando[comando.index("--file") + 1]).write_bytes(b"dump")
        return CommandResult(argv=comando, returncode=self.returncode, stderr="boom")


class BusQuebrado:
    """`EventBus` que sempre falha. Bus com defeito não invalida backup feito."""

    async def publish(self, event: object) -> None:
        raise RuntimeError("fila cheia")


def make_manager(
    tmp_path: Path,
    bus: EventBus | None,
    *,
    returncode: int = 0,
) -> SchedulerManager:
    return SchedulerManager(
        event_bus=bus,
        backup=BackupService(
            target=PostgresTarget(
                host="postgres", port=5432, user="jarvis", password="s", database="jarvis"
            ),
            backup_root=tmp_path / "backups",
            runner=DumpQueEscreve(returncode=returncode),
            clock=lambda: INSTANTE,
        ),
    )


# --------------------------------------------------------------------------- #
# run_backup — o aceite da fatia
# --------------------------------------------------------------------------- #


async def test_backup_emite_backup_completed(
    tmp_path: Path, event_bus: InMemoryEventBus
) -> None:
    await make_manager(tmp_path, event_bus).run_backup()

    assert event_bus.types == [EventType.BACKUP_COMPLETED]
    assert event_bus.types == ["backup.completed"]  # o nome no fio, literal


async def test_o_evento_diz_onde_o_backup_ficou(
    tmp_path: Path, event_bus: InMemoryEventBus
) -> None:
    """Evento sem o caminho obrigaria o consumidor a adivinhar — e o consumidor
    mais importante deste evento é quem vai precisar restaurar."""
    await make_manager(tmp_path, event_bus).run_backup()

    evento = event_bus.of_type(EventType.BACKUP_COMPLETED)[0]
    assert evento.source == EVENT_SOURCE
    assert evento.trace_id
    assert evento.payload["backup_id"] == "20260730T030000Z"
    assert Path(str(evento.payload["root"])).is_dir()
    assert evento.payload["database"] == "jarvis"
    assert evento.payload["postgres_bytes"] == 4
    assert len(str(evento.payload["postgres_sha256"])) == 64


async def test_backup_que_falha_nao_emite_evento_de_sucesso(
    tmp_path: Path, event_bus: InMemoryEventBus
) -> None:
    """Evento de sucesso em cima de falha é pior do que evento nenhum: vira a
    prova falsa que faz o dono não olhar o backup por meses."""
    await make_manager(tmp_path, event_bus, returncode=1).run_backup()

    assert event_bus.published == []


async def test_falha_no_backup_nao_propaga_para_o_scheduler(
    tmp_path: Path, event_bus: InMemoryEventBus
) -> None:
    """Job que levanta mata o `AsyncIOScheduler` e leva junto os outros dois."""
    await make_manager(tmp_path, event_bus, returncode=1).run_backup()  # não levanta


async def test_bus_quebrado_nao_derruba_o_job(tmp_path: Path) -> None:
    manager = make_manager(tmp_path, BusQuebrado())
    await manager.run_backup()

    # O backup no disco continua lá: publicar é consequência, não pré-requisito.
    assert (tmp_path / "backups" / "20260730T030000Z" / "manifest.json").is_file()


async def test_sem_bus_o_backup_ainda_acontece(tmp_path: Path) -> None:
    await make_manager(tmp_path, None).run_backup()
    assert (tmp_path / "backups" / "20260730T030000Z" / "postgres.dump").is_file()


async def test_sem_servico_o_job_nao_finge_sucesso(event_bus: InMemoryEventBus) -> None:
    """Manager cru (sem serviços) não pode publicar `backup.completed` — era
    exatamente o que o D-11 fazia: log de 'completed' sem backup nenhum."""
    await SchedulerManager(event_bus=event_bus).run_backup()

    assert event_bus.published == []


async def test_erro_inesperado_do_servico_e_contido(
    tmp_path: Path, event_bus: InMemoryEventBus
) -> None:
    class ServicoExplosivo:
        async def run(self) -> None:
            raise BackupError("disco cheio")

    manager = SchedulerManager(event_bus=event_bus)
    manager._backup = ServicoExplosivo()  # type: ignore[assignment]

    await manager.run_backup()

    assert event_bus.published == []


# --------------------------------------------------------------------------- #
# cleanup_logs
# --------------------------------------------------------------------------- #


async def test_cleanup_roda_e_nao_publica_evento(tmp_path: Path) -> None:
    """Faxina não é fato de domínio: não vai para o bus. Vai para o log."""
    bus = InMemoryEventBus()
    manager = SchedulerManager(
        event_bus=bus, cleanup=CleanupService(log_dir=tmp_path / "logs")
    )

    await manager.cleanup_logs()

    assert bus.published == []


# --------------------------------------------------------------------------- #
# reindex_knowledge
# --------------------------------------------------------------------------- #


async def test_reindex_com_mudanca_publica_memory_updated(tmp_path: Path) -> None:
    corpus = tmp_path / "knowledge"
    corpus.mkdir()
    (corpus / "nota.md").write_text("conteúdo novo", encoding="utf-8")

    bus = InMemoryEventBus()
    manager = SchedulerManager(
        event_bus=bus,
        reindex=ReindexService(source_dir=corpus, index=InMemoryKnowledgeIndex()),
    )

    await manager.reindex_knowledge()

    assert bus.types == [EventType.MEMORY_UPDATED]
    evento = bus.published[0]
    assert evento.payload["level"] == "knowledge"
    assert evento.payload["added"] == 1


async def test_reindex_sem_mudanca_nao_publica_nada(tmp_path: Path) -> None:
    """Bus não é lugar de anunciar que nada aconteceu."""
    corpus = tmp_path / "knowledge"
    corpus.mkdir()
    (corpus / "nota.md").write_text("estável", encoding="utf-8")

    indice = InMemoryKnowledgeIndex()
    servico = ReindexService(source_dir=corpus, index=indice)
    bus = InMemoryEventBus()
    manager = SchedulerManager(event_bus=bus, reindex=servico)

    await manager.reindex_knowledge()  # primeira: indexa
    bus.clear()
    await manager.reindex_knowledge()  # segunda: nada mudou

    assert bus.published == []


# --------------------------------------------------------------------------- #
# start() — "roda sozinho"
# --------------------------------------------------------------------------- #


async def test_start_registra_os_tres_jobs_e_para_limpo() -> None:
    """`async` de propósito: o `AsyncIOScheduler` se prende ao event loop em
    execução, e chamar `start()` sem loop é um teste que passa por acidente."""
    pytest.importorskip("apscheduler")

    cfg = SchedulerConfig(backup_hour=3, cleanup_hour=4, reindex_hour=5)
    manager = SchedulerManager(config=cfg)
    manager.start()

    try:
        assert manager.running
        agendador = manager._scheduler
        assert agendador is not None
        jobs = {job.id: job for job in agendador.get_jobs()}
        assert sorted(jobs) == [
            "jarvis.backup",
            "jarvis.cleanup_logs",
            "jarvis.reindex_knowledge",
        ]
        assert "hour='3'" in str(jobs["jarvis.backup"].trigger)
        assert "hour='4'" in str(jobs["jarvis.cleanup_logs"].trigger)
        assert "hour='5'" in str(jobs["jarvis.reindex_knowledge"].trigger)
        # Um disparo perdido não pode virar N backups simultâneos ao religar.
        assert jobs["jarvis.backup"].max_instances == 1
        assert jobs["jarvis.backup"].coalesce is True
    finally:
        manager.stop()

    assert not manager.running


def test_stop_sem_start_nao_explode() -> None:
    SchedulerManager().stop()
