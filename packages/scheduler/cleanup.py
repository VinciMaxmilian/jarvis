"""Limpeza: arquivos de log velhos e chaves de short-term memory que vazaram.

Duas faxinas distintas com o mesmo dono, porque as duas têm a mesma natureza —
crescimento sem teto que ninguém percebe até o disco (ou a RAM do Redis) acabar.

**Sobre "short memory expirada".** O Redis já apaga sozinho o que tem TTL; um job
que varresse chaves expiradas não teria o que apagar. O que de fato vaza é a
chave gravada **sem** TTL: `ShortTermMemory.set_state` aceita `ttl_seconds`, e
qualquer chamador que passe `0`, ou qualquer escrita feita por fora dela, cria
uma chave imortal num keyspace que deveria ser todo efêmero. É isso que este job
recolhe — `TTL == -1` no padrão da short-term memory.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path

import structlog

from packages.scheduler.models import CleanupResult
from packages.scheduler.ports import ShortTermKeyspace
from packages.shared.contracts import utcnow

logger = structlog.get_logger(__name__)

#: `TTL` de chave existente e sem expiração definida (convenção do Redis).
TTL_SEM_EXPIRACAO = -1

#: Padrões considerados "log". Deliberadamente restrito: um job que apaga por
#: idade dentro de um diretório configurável é uma arma apontada para o pé se o
#: filtro for `*`.
DEFAULT_LOG_GLOBS: tuple[str, ...] = ("*.log", "*.log.*", "*.jsonl", "*.jsonl.*")


class CleanupService:
    """Poda arquivos de log por idade e recolhe chaves efêmeras sem TTL."""

    def __init__(
        self,
        *,
        log_dir: Path | None = None,
        max_age_days: int = 14,
        log_globs: Sequence[str] = DEFAULT_LOG_GLOBS,
        keyspace: ShortTermKeyspace | None = None,
        short_term_pattern: str = "jarvis:short:*",
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        if max_age_days < 1:
            raise ValueError("max_age_days precisa ser >= 1 — 0 apagaria o log de hoje")
        self._log_dir = log_dir
        self._max_age = timedelta(days=max_age_days)
        self._globs = tuple(log_globs)
        self._keyspace = keyspace
        self._pattern = short_term_pattern
        self._clock = clock

    async def run(self) -> CleanupResult:
        removidos, bytes_liberados, nomes = self._podar_logs()
        varridas, apagadas = await self._recolher_short_term()
        resultado = CleanupResult(
            log_files_removed=removidos,
            log_bytes_freed=bytes_liberados,
            log_files=tuple(nomes),
            short_term_keys_scanned=varridas,
            short_term_keys_removed=apagadas,
        )
        logger.info(
            "scheduler.cleanup.done",
            log_files_removed=removidos,
            log_bytes_freed=bytes_liberados,
            short_term_keys_scanned=varridas,
            short_term_keys_removed=apagadas,
        )
        return resultado

    # -- logs -------------------------------------------------------------- #

    def _podar_logs(self) -> tuple[int, int, list[str]]:
        if self._log_dir is None or not self._log_dir.is_dir():
            logger.info(
                "scheduler.cleanup.logs.skipped",
                reason="diretório inexistente",
                path=str(self._log_dir) if self._log_dir else None,
            )
            return 0, 0, []

        corte = self._clock() - self._max_age
        limite = corte.timestamp()
        removidos = 0
        liberados = 0
        nomes: list[str] = []

        for padrao in self._globs:
            for arquivo in sorted(self._log_dir.rglob(padrao)):
                if not arquivo.is_file():
                    continue
                estado = arquivo.stat()
                if estado.st_mtime >= limite:
                    continue
                try:
                    arquivo.unlink()
                except OSError as exc:  # pragma: no cover — arquivo em uso no Windows
                    logger.warning(
                        "scheduler.cleanup.logs.unlink_failed",
                        path=str(arquivo),
                        error=str(exc),
                    )
                    continue
                removidos += 1
                liberados += estado.st_size
                nomes.append(arquivo.relative_to(self._log_dir).as_posix())

        return removidos, liberados, nomes

    # -- short-term memory -------------------------------------------------- #

    async def _recolher_short_term(self) -> tuple[int, int]:
        if self._keyspace is None:
            logger.info("scheduler.cleanup.short_term.skipped", reason="sem keyspace")
            return 0, 0

        chaves = await self._keyspace.scan(self._pattern)
        orfas = [
            chave
            for chave in chaves
            if await self._keyspace.ttl_seconds(chave) == TTL_SEM_EXPIRACAO
        ]
        if not orfas:
            return len(chaves), 0

        apagadas = await self._keyspace.delete(orfas)
        logger.warning(
            "scheduler.cleanup.short_term.leaked_keys",
            pattern=self._pattern,
            removed=apagadas,
            sample=orfas[:5],
        )
        return len(chaves), apagadas


__all__ = ["DEFAULT_LOG_GLOBS", "TTL_SEM_EXPIRACAO", "CleanupService"]
