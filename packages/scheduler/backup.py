"""Backup: `pg_dump` do Postgres + snapshot do diretório do LanceDB.

O risco R-5 de `plan-execution.md` §8 é literalmente este arquivo: *"backup
existe e restore nunca é testado"*. Três decisões existem só por causa dele:

1. **Formato `custom` (`-Fc`)**, não SQL de texto. É o que o `pg_restore` sabe
   restaurar seletivamente, com `--clean --if-exists`, sem depender de o banco
   de destino ter sido criado com o mesmo dono e as mesmas roles.
2. **Manifesto com SHA-256** de cada artefato. Restore que não confere digest
   descobre a corrupção no meio da restauração, com o banco já derrubado.
3. **Escrita em `<carimbo>.partial` e rename no fim.** Processo morto no meio
   deixa um `.partial`, que o restore ignora e a retenção varre. Sem isso, um
   backup truncado tem exatamente a mesma cara de um backup bom.

O restore é `infrastructure/scripts/restore.sh` — shell, não Python, de
propósito: o dia em que o restore é preciso é o dia em que talvez não exista
mais um Python com as dependências do projeto instaladas.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

import structlog

from packages.scheduler.models import (
    DUMP_NAME,
    LANCEDB_DIRNAME,
    MANIFEST_NAME,
    PARTIAL_SUFFIX,
    STAMP_FORMAT,
    ArtifactDigest,
    BackupManifest,
    BackupResult,
    PostgresTarget,
    sha256_of_file,
    sha256_of_tree,
)
from packages.scheduler.ports import CommandRunner
from packages.shared.contracts import utcnow

logger = structlog.get_logger(__name__)

#: Teto do `pg_dump`. Uma hora é folgado para um banco single-user e curto o
#: bastante para o job não ficar pendurado até o backup do dia seguinte.
DEFAULT_TIMEOUT_SECONDS = 3600.0


class BackupError(RuntimeError):
    """Backup não terminou. O evento `backup.completed` **não** é emitido."""


class BackupService:
    """Produz um diretório de backup autoconferível.

    Layout resultante::

        <backup_root>/20260730T031500Z/
            manifest.json      índice + digests
            postgres.dump      pg_dump --format=custom
            lancedb/           cópia do diretório de vetores (se existir)
    """

    def __init__(
        self,
        *,
        target: PostgresTarget,
        backup_root: Path,
        runner: CommandRunner,
        lancedb_path: Path | None = None,
        pg_dump_argv: Sequence[str] = ("pg_dump",),
        retention: int = 7,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        if retention < 1:
            raise ValueError(
                "retention precisa ser >= 1 — 0 apagaria o backup recém-feito"
            )
        if not pg_dump_argv:
            raise ValueError("pg_dump_argv vazio")
        self._target = target
        self._root = backup_root
        self._runner = runner
        self._lancedb_path = lancedb_path
        self._pg_dump_argv = tuple(pg_dump_argv)
        self._retention = retention
        self._timeout = timeout_seconds
        self._clock = clock

    # -- API -------------------------------------------------------------- #

    async def run(self) -> BackupResult:
        """Executa o backup completo. Levanta `BackupError` se algo falhar."""
        inicio = time.monotonic()
        self._root.mkdir(parents=True, exist_ok=True)

        backup_id = self._reservar_id()
        parcial = self._root / f"{backup_id}{PARTIAL_SUFFIX}"
        parcial.mkdir()

        try:
            postgres = await self._dump_postgres(parcial)
            lancedb = await self._snapshot_lancedb(parcial)
            manifesto = BackupManifest(
                backup_id=backup_id,
                created_at=self._clock(),
                database=self._target.database,
                postgres=postgres,
                lancedb=lancedb,
                tool_version=" ".join(self._pg_dump_argv),
            )
            self._escrever_manifesto(parcial, manifesto)
        except Exception:
            # Diretório parcial some junto com a falha: deixar lixo no caminho do
            # restore é pior do que não ter backup nenhum, porque parece backup.
            shutil.rmtree(parcial, ignore_errors=True)
            raise

        final = self._root / backup_id
        parcial.rename(final)

        podados = self._podar()
        resultado = BackupResult(
            manifest=manifesto,
            root=str(final),
            pruned=tuple(podados),
            duration_seconds=round(time.monotonic() - inicio, 3),
        )
        logger.info(
            "scheduler.backup.written",
            backup_id=backup_id,
            root=str(final),
            postgres_bytes=postgres.bytes,
            lancedb_files=lancedb.files if lancedb else 0,
            pruned=len(podados),
            duration_seconds=resultado.duration_seconds,
        )
        return resultado

    # -- Postgres ---------------------------------------------------------- #

    async def _dump_postgres(self, destino: Path) -> ArtifactDigest:
        arquivo = destino / DUMP_NAME
        argv = [
            *self._pg_dump_argv,
            *self._target.libpq_args(),
            "--format=custom",
            # Sem dono e sem ACL: o restore numa base limpa recria tudo sob o
            # usuário que estiver conectando. Com `--no-owner` ausente, restaurar
            # num container novo falha em toda linha de `ALTER ... OWNER TO`.
            "--no-owner",
            "--no-privileges",
            "--file",
            str(arquivo),
        ]
        logger.info(
            "scheduler.backup.pg_dump.started", target=self._target.redacted()
        )
        resultado = await self._runner.run(
            argv, env=self._target.env(), timeout_seconds=self._timeout
        )
        if not resultado.ok:
            raise BackupError(
                f"pg_dump falhou ({resultado.returncode}): {resultado.resumo_do_erro}"
            )
        if not arquivo.is_file():
            raise BackupError("pg_dump devolveu 0 mas não escreveu o arquivo de dump")

        tamanho = arquivo.stat().st_size
        if tamanho == 0:
            raise BackupError("dump vazio — backup de 0 byte não é backup")

        return ArtifactDigest(
            path=DUMP_NAME, bytes=tamanho, sha256=sha256_of_file(arquivo), files=1
        )

    # -- LanceDB ----------------------------------------------------------- #

    async def _snapshot_lancedb(self, destino: Path) -> ArtifactDigest | None:
        """Cópia do diretório de vetores. Ausência é caso normal, não erro.

        Nunca importa `lancedb`: o snapshot é do **diretório**, e a biblioteca
        não roda em CPU sem AVX2. Copiar arquivo funciona em qualquer CPU.
        """
        origem = self._lancedb_path
        if origem is None or not origem.is_dir():
            logger.info(
                "scheduler.backup.lancedb.absent",
                path=str(origem) if origem else None,
            )
            return None

        alvo = destino / LANCEDB_DIRNAME
        # copytree e o hash da árvore são I/O bloqueante; numa thread para não
        # travar o event loop do orchestrator enquanto o backup roda.
        await asyncio.to_thread(shutil.copytree, origem, alvo)
        digest, arquivos, tamanho = await asyncio.to_thread(sha256_of_tree, alvo)
        logger.info(
            "scheduler.backup.lancedb.copied", files=arquivos, bytes=tamanho
        )
        return ArtifactDigest(
            path=LANCEDB_DIRNAME, bytes=tamanho, sha256=digest, files=arquivos
        )

    # -- manifesto e retenção ---------------------------------------------- #

    def _escrever_manifesto(self, destino: Path, manifesto: BackupManifest) -> None:
        texto = manifesto.model_dump_json(indent=2)
        (destino / MANIFEST_NAME).write_text(texto + "\n", encoding="utf-8")

    def _reservar_id(self) -> str:
        """Carimbo UTC; sufixo `-N` se dois backups caírem no mesmo segundo."""
        base = self._clock().strftime(STAMP_FORMAT)
        candidato = base
        sufixo = 1
        while (self._root / candidato).exists() or (
            self._root / f"{candidato}{PARTIAL_SUFFIX}"
        ).exists():
            candidato = f"{base}-{sufixo}"
            sufixo += 1
        return candidato

    def existing_backups(self) -> list[Path]:
        """Backups **íntegros**, do mais antigo ao mais novo.

        Íntegro = tem `manifest.json`. Um `.partial` (processo morto no meio) e
        um diretório sem manifesto não contam: se contassem, a retenção poderia
        apagar o último backup bom para preservar um pedaço de backup.
        """
        if not self._root.is_dir():
            return []
        return sorted(
            item
            for item in self._root.iterdir()
            if item.is_dir()
            and not item.name.endswith(PARTIAL_SUFFIX)
            and (item / MANIFEST_NAME).is_file()
        )

    def _podar(self) -> list[str]:
        existentes = self.existing_backups()
        excedente = existentes[: max(0, len(existentes) - self._retention)]
        removidos: list[str] = []
        for item in excedente:
            shutil.rmtree(item, ignore_errors=True)
            removidos.append(item.name)
            logger.info("scheduler.backup.pruned", backup_id=item.name)
        # `.partial` órfão de execução anterior sai junto — não é backup e o
        # restore não sabe o que fazer com ele.
        for item in self._root.iterdir():
            if item.is_dir() and item.name.endswith(PARTIAL_SUFFIX):
                shutil.rmtree(item, ignore_errors=True)
                logger.warning("scheduler.backup.partial_removed", name=item.name)
        return removidos


def read_manifest(backup_dir: Path) -> BackupManifest:
    """Lê e valida o `manifest.json` de um backup. Usado por ferramenta e teste."""
    bruto = (backup_dir / MANIFEST_NAME).read_text(encoding="utf-8")
    return BackupManifest.model_validate(json.loads(bruto))


def verify_backup(backup_dir: Path) -> list[str]:
    """Confere os digests do manifesto contra o disco.

    Devolve a lista de problemas — vazia significa backup íntegro. É a mesma
    verificação que o `restore.sh` faz antes de encostar no banco; existe também
    em Python para que a suíte possa afirmar que um backup recém-feito passa.
    """
    problemas: list[str] = []
    manifesto = read_manifest(backup_dir)

    dump = backup_dir / manifesto.postgres.path
    if not dump.is_file():
        problemas.append(f"dump ausente: {manifesto.postgres.path}")
    else:
        if dump.stat().st_size != manifesto.postgres.bytes:
            problemas.append("tamanho do dump difere do manifesto")
        if sha256_of_file(dump) != manifesto.postgres.sha256:
            problemas.append("sha256 do dump difere do manifesto")

    if manifesto.lancedb is not None:
        arvore = backup_dir / manifesto.lancedb.path
        if not arvore.is_dir():
            problemas.append(f"snapshot do lancedb ausente: {manifesto.lancedb.path}")
        else:
            digest, arquivos, _ = sha256_of_tree(arvore)
            if digest != manifesto.lancedb.sha256:
                problemas.append("sha256 da árvore do lancedb difere do manifesto")
            if arquivos != manifesto.lancedb.files:
                problemas.append("contagem de arquivos do lancedb difere do manifesto")

    return problemas


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "BackupError",
    "BackupService",
    "read_manifest",
    "verify_backup",
]
