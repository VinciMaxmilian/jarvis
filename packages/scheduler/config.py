"""Configuração dos jobs, lida do ambiente com prefixo `JARVIS_`.

Por que **não** entrou em `packages/shared/settings.py`: aquele arquivo tem a
regra "toda variável declarada aqui entra em `.env.example` no mesmo commit", e
o `.env.example` pertence a outra fatia neste momento. Um contrato de
configuração próprio, com defaults que funcionam sem nenhuma variável definida,
entrega a mesma coisa sem tocar em arquivo de terceiro — e, quando as variáveis
forem documentadas, elas já são lidas do mesmo `.env`.

Todos os caminhos relativos são resolvidos contra a **raiz do repositório**, não
contra o diretório de trabalho: o scheduler roda dentro do orchestrator, cujo
cwd não é garantido, e um backup gravado em cwd errado é um backup perdido.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

#: `packages/scheduler/config.py` → sobe três níveis até a raiz do repo.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def resolve_path(bruto: str) -> Path:
    """Caminho absoluto; relativo é resolvido contra a raiz do repositório."""
    caminho = Path(bruto).expanduser()
    if caminho.is_absolute():
        return caminho
    return (_REPO_ROOT / caminho).resolve()


class SchedulerConfig(BaseSettings):
    """Onde cada job escreve, quanto guarda e a que horas roda."""

    model_config = SettingsConfigDict(
        env_file=os.fspath(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        env_prefix="jarvis_",
        extra="ignore",
        case_sensitive=False,
    )

    # --- backup ------------------------------------------------------------ #
    backup_path: str = "./data/backups"
    #: Sete dias de retenção: cobre a semana inteira, e o dump de um banco
    #: single-user é pequeno. `ge=1` porque `0` apagaria o backup recém-escrito.
    backup_retention: int = Field(default=7, ge=1)
    #: Binário do dump. Existe como variável porque a imagem de runtime pode
    #: trazê-lo em caminho não padrão (ou não trazê-lo — ver README de scripts).
    pg_dump_bin: str = "pg_dump"
    backup_timeout_seconds: float = Field(default=3600.0, gt=0)

    # --- limpeza ----------------------------------------------------------- #
    log_path: str = "./data/logs"
    log_max_age_days: int = Field(default=14, ge=1)
    short_term_pattern: str = "jarvis:short:*"

    # --- knowledge --------------------------------------------------------- #
    knowledge_path: str = "./data/knowledge"
    #: Skills declarativas (`<nome>/SKILL.md`). Mora aqui, e não numa constante
    #: em `packages/agents/skills.py`, porque a regra de resolução é a mesma do
    #: `knowledge_path` — relativo ancorado na raiz do repo, nunca no cwd — e o
    #: pipeline de pesquisa escreve nas duas pastas no mesmo passo.
    skills_path: str = "./data/skills"

    # --- horários (cron, hora local do container) --------------------------- #
    #
    # Escalonados de propósito: backup às 3h, limpeza às 4h, reindexação às 5h.
    # Rodar os três juntos faria a limpeza competir por I/O com o `pg_dump` e,
    # pior, poderia varrer log da própria execução do backup.
    backup_hour: int = Field(default=3, ge=0, le=23)
    cleanup_hour: int = Field(default=4, ge=0, le=23)
    reindex_hour: int = Field(default=5, ge=0, le=23)

    # -- derivados ---------------------------------------------------------- #

    @property
    def backup_root(self) -> Path:
        return resolve_path(self.backup_path)

    @property
    def log_dir(self) -> Path:
        return resolve_path(self.log_path)

    @property
    def knowledge_dir(self) -> Path:
        return resolve_path(self.knowledge_path)

    @property
    def skills_dir(self) -> Path:
        return resolve_path(self.skills_path)


__all__ = ["SchedulerConfig", "resolve_path"]
