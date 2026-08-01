"""Modelos de dados do scheduler.

Nenhum dicionário solto atravessa fronteira de módulo (`plan-execution.md` §7):
o que sai de um job é um modelo tipado, e é ele que vira `payload` de evento — a
conversão para `dict` acontece **na borda**, ao montar o `Event`, não antes.

Roda sob `mypy`; os modelos de resultado são `frozen` porque resultado de job é
fato consumado: mutar depois de devolvido esconderia de onde veio o número.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field

from packages.shared.contracts import utcnow

#: Formato do carimbo que nomeia o diretório de um backup. Ordenação
#: lexicográfica == ordenação cronológica, o que faz a retenção ser um `sorted()`
#: em vez de um parse de data por diretório.
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"

#: Sufixo do diretório em construção. Um backup só ganha o nome definitivo
#: depois do último byte escrito; assim um processo morto no meio nunca deixa
#: para trás algo que o restore confundiria com backup íntegro.
PARTIAL_SUFFIX = ".partial"

#: Nomes fixos dentro do diretório de um backup. O `restore.sh` depende deles.
MANIFEST_NAME = "manifest.json"
DUMP_NAME = "postgres.dump"
LANCEDB_DIRNAME = "lancedb"


def sha256_of_file(path: Path, *, chunk_size: int = 1 << 20) -> str:
    """SHA-256 de um arquivo, lido em blocos (o dump não cabe na memória)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_of_tree(root: Path) -> tuple[str, int, int]:
    """Digest estável de um diretório: `(sha256, arquivos, bytes)`.

    O digest é sobre a lista ordenada de `caminho relativo + sha256 do conteúdo`,
    e não sobre a concatenação dos bytes: assim renomear um arquivo muda o
    digest, que é exatamente o que se quer de um snapshot de índice vetorial.
    """
    linhas: list[str] = []
    arquivos = 0
    tamanho = 0
    for item in sorted(root.rglob("*")):
        if not item.is_file():
            continue
        arquivos += 1
        tamanho += item.stat().st_size
        relativo = item.relative_to(root).as_posix()
        linhas.append(f"{relativo}\0{sha256_of_file(item)}")
    combinado = "\n".join(linhas).encode("utf-8")
    return hashlib.sha256(combinado).hexdigest(), arquivos, tamanho


# --------------------------------------------------------------------------- #
# Execução de comando externo
# --------------------------------------------------------------------------- #


class CommandResult(BaseModel):
    """Saída de um processo externo (`pg_dump`), já decodificada.

    `argv` é guardado para o log — por isso a senha **nunca** entra em `argv`:
    ela viaja em `PGPASSWORD`, que não aparece nem aqui nem em `ps`.
    """

    model_config = ConfigDict(frozen=True)

    argv: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def resumo_do_erro(self) -> str:
        """Última linha não vazia do stderr — o que o `pg_dump` de fato reclamou."""
        for linha in reversed(self.stderr.splitlines()):
            if linha.strip():
                return linha.strip()
        return f"código de saída {self.returncode}"


# --------------------------------------------------------------------------- #
# Alvo Postgres
# --------------------------------------------------------------------------- #


class PostgresTarget(BaseModel):
    """Coordenadas de conexão em forma libpq, derivadas do DSN da aplicação.

    O `Settings.database_url` é um DSN SQLAlchemy (`postgresql+asyncpg://...`) e
    o `pg_dump` não entende o sufixo do driver. Traduzir aqui, uma vez, evita
    que cada chamador repita a gambiarra de string.
    """

    model_config = ConfigDict(frozen=True)

    host: str
    port: int = Field(default=5432, ge=1, le=65535)
    user: str
    password: str = ""
    database: str

    @classmethod
    def from_dsn(cls, dsn: str) -> PostgresTarget:
        """Aceita `postgresql://`, `postgresql+asyncpg://` e `postgresql+psycopg://`."""
        partes = urlsplit(dsn)
        if not partes.scheme.startswith("postgres"):
            raise ValueError(f"DSN não é de Postgres: {partes.scheme}://...")
        banco = unquote(partes.path.lstrip("/"))
        if not banco:
            raise ValueError("DSN sem nome de banco")
        if not partes.hostname:
            raise ValueError("DSN sem host")
        return cls(
            host=partes.hostname,
            port=partes.port or 5432,
            # unquote explícito: urlsplit devolve o pedaço cru do netloc, então
            # uma senha com `%40` chegaria literal e a autenticação falharia com
            # a mensagem menos útil possível ("password authentication failed").
            user=unquote(partes.username or ""),
            password=unquote(partes.password or ""),
            database=banco,
        )

    def libpq_args(self) -> list[str]:
        """Flags de conexão. **Sem senha** — ver `env()`."""
        return [
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--username",
            self.user,
            "--dbname",
            self.database,
        ]

    def env(self) -> dict[str, str]:
        """Variáveis para o processo filho. É por aqui que a senha viaja."""
        ambiente = {"PGPASSWORD": self.password} if self.password else {}
        return ambiente

    def redacted(self) -> str:
        """Como o alvo aparece em log: sem senha, nunca."""
        return f"postgresql://{self.user}@{self.host}:{self.port}/{self.database}"


# --------------------------------------------------------------------------- #
# Backup
# --------------------------------------------------------------------------- #


class ArtifactDigest(BaseModel):
    """Um artefato do backup, com o que o restore precisa para conferir."""

    model_config = ConfigDict(frozen=True)

    path: str  # relativo à raiz do backup
    bytes: int = Field(ge=0)
    sha256: str
    files: int = Field(default=1, ge=0)  # > 1 só para o snapshot de diretório


class BackupManifest(BaseModel):
    """Índice do backup, serializado como `manifest.json` no próprio diretório.

    É o contrato entre o job (Python) e o `infrastructure/scripts/restore.sh`
    (shell). Mudar campo aqui sem mudar lá quebra o restore — e restore quebrado
    só aparece no dia em que é preciso, que é o pior dia possível (R-5).
    """

    model_config = ConfigDict(frozen=True)

    manifest_version: int = 1
    backup_id: str  # nome do diretório, ex.: 20260730T031500Z
    created_at: datetime = Field(default_factory=utcnow)
    database: str
    postgres_format: Literal["custom"] = "custom"
    postgres: ArtifactDigest
    #: `None` quando o diretório do LanceDB não existe — caso **normal** numa
    #: máquina sem vetores gravados, não erro.
    lancedb: ArtifactDigest | None = None
    tool_version: str = ""


class BackupResult(BaseModel):
    """O que o job devolve. Vira `payload` do evento `backup.completed`."""

    model_config = ConfigDict(frozen=True)

    manifest: BackupManifest
    root: str  # caminho absoluto do diretório do backup
    pruned: tuple[str, ...] = ()  # backups apagados pela retenção
    duration_seconds: float = Field(default=0.0, ge=0.0)

    @property
    def total_bytes(self) -> int:
        vetores = self.manifest.lancedb.bytes if self.manifest.lancedb else 0
        return self.manifest.postgres.bytes + vetores


# --------------------------------------------------------------------------- #
# Limpeza
# --------------------------------------------------------------------------- #


class CleanupResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    log_files_removed: int = Field(default=0, ge=0)
    log_bytes_freed: int = Field(default=0, ge=0)
    log_files: tuple[str, ...] = ()
    short_term_keys_scanned: int = Field(default=0, ge=0)
    short_term_keys_removed: int = Field(default=0, ge=0)

    @property
    def nada_a_fazer(self) -> bool:
        return self.log_files_removed == 0 and self.short_term_keys_removed == 0


# --------------------------------------------------------------------------- #
# Reindexação do knowledge
# --------------------------------------------------------------------------- #


class KnowledgeDocument(BaseModel):
    """Documento lido do disco, pronto para ser indexado."""

    model_config = ConfigDict(frozen=True)

    doc_id: str  # caminho relativo em posix — estável entre Windows e Linux
    source: str  # caminho absoluto no momento da leitura
    sha256: str
    text: str
    modified_at: datetime


class IndexedDocument(BaseModel):
    """O que o índice já tem. Só o suficiente para decidir se mudou."""

    model_config = ConfigDict(frozen=True)

    doc_id: str
    sha256: str
    indexed_at: datetime = Field(default_factory=utcnow)


class ReindexResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    scanned: int = Field(default=0, ge=0)
    added: int = Field(default=0, ge=0)
    updated: int = Field(default=0, ge=0)
    removed: int = Field(default=0, ge=0)
    unchanged: int = Field(default=0, ge=0)
    skipped_reason: str = ""

    @property
    def changed(self) -> int:
        """Quanto o índice de fato mexeu. Zero é o caso bom do dia a dia."""
        return self.added + self.updated + self.removed


__all__ = [
    "DUMP_NAME",
    "LANCEDB_DIRNAME",
    "MANIFEST_NAME",
    "PARTIAL_SUFFIX",
    "STAMP_FORMAT",
    "ArtifactDigest",
    "BackupManifest",
    "BackupResult",
    "CleanupResult",
    "CommandResult",
    "IndexedDocument",
    "KnowledgeDocument",
    "PostgresTarget",
    "ReindexResult",
    "sha256_of_file",
    "sha256_of_tree",
]
