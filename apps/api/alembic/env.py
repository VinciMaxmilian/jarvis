"""Alembic env.py — usa os ORM models de apps.api.db.models.

O `target_metadata` aponta para `Base.metadata` para que `autogenerate` funcione.
DSN síncrono (psycopg) lido de Settings.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from apps.api.db.models import Base

# Alembic Config object
config = context.config

# Logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata para autogenerate
target_metadata = Base.metadata


def _redact(url: str) -> str:
    """Esconde a senha de um DSN antes de ele ir para log.

    O DSN carrega credencial. Um `docker compose logs` é a coisa mais copiada e
    colada que existe num troubleshooting, e log de container costuma sobreviver
    em lugares que ninguém trata como segredo.
    """
    scheme, sep, rest = url.partition("://")
    if not sep or "@" not in rest:
        return url
    userinfo, _, hostpart = rest.partition("@")
    user, has_pw, _ = userinfo.partition(":")
    return f"{scheme}://{user}{':***' if has_pw else ''}@{hostpart}"


def get_sync_url() -> str:
    """Lê a URL do settings (async) e converte para sync."""
    try:
        from packages.shared.settings import get_settings
        return get_settings().sync_database_url
    except Exception as e:
        print(f"Alembic ignorou o .env por causa deste erro: {e}")
        # Fallback: usa o que está no alembic.ini
        return config.get_main_option("sqlalchemy.url", "")


def run_migrations_offline() -> None:
    url = get_sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    cfg = config.get_section(config.config_ini_section, {})
    url = get_sync_url()
    # Útil para saber contra qual banco a migration rodou; redigido porque o DSN
    # traz a senha e este log é o primeiro a ser colado num pedido de ajuda.
    print(f"alembic: migrando {_redact(url)}")
    cfg["sqlalchemy.url"] = url

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
