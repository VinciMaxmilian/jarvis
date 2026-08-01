"""`PostgresTarget` — a tradução do DSN da aplicação para argumentos do libpq.

Parece trivial e não é: o `Settings.database_url` é um DSN SQLAlchemy
(`postgresql+asyncpg://`), o `pg_dump` não entende o sufixo do driver, e senha
com caractere especial vem percent-encoded. Cada um desses três é um backup que
falha às 3h da manhã com uma mensagem que não aponta para a causa.
"""

from __future__ import annotations

import pytest

from packages.scheduler.models import PostgresTarget

DSN_ASYNC = "postgresql+asyncpg://jarvis:senha@127.0.0.1:5433/jarvis"


def test_le_o_dsn_async_da_aplicacao() -> None:
    alvo = PostgresTarget.from_dsn(DSN_ASYNC)

    assert alvo.host == "127.0.0.1"
    assert alvo.port == 5433
    assert alvo.user == "jarvis"
    assert alvo.password == "senha"
    assert alvo.database == "jarvis"


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://jarvis:senha@postgres:5432/jarvis",
        "postgresql+asyncpg://jarvis:senha@postgres:5432/jarvis",
        "postgresql+psycopg://jarvis:senha@postgres:5432/jarvis",
    ],
)
def test_aceita_os_tres_dsn_que_circulam_no_repo(dsn: str) -> None:
    """asyncpg na app, psycopg no Alembic, cru no psql. Os três apontam para o
    mesmo banco e o backup precisa funcionar a partir de qualquer um."""
    alvo = PostgresTarget.from_dsn(dsn)
    assert (alvo.host, alvo.port, alvo.database) == ("postgres", 5432, "jarvis")


def test_porta_ausente_cai_no_default_do_postgres() -> None:
    alvo = PostgresTarget.from_dsn("postgresql://jarvis:s@postgres/jarvis")
    assert alvo.port == 5432


def test_senha_percent_encoded_e_decodificada() -> None:
    """`@` na senha vira `%40` no DSN. Passar `%40` para o pg_dump autenticaria
    com a senha errada e o erro diria apenas 'password authentication failed'."""
    alvo = PostgresTarget.from_dsn(
        "postgresql+asyncpg://us%40r:p%40ss%3Aword@postgres:5432/jarvis"
    )
    assert alvo.user == "us@r"
    assert alvo.password == "p@ss:word"


@pytest.mark.parametrize(
    ("dsn", "erro"),
    [
        ("mysql://a:b@host:3306/db", "não é de Postgres"),
        ("postgresql://a:b@host:5432/", "sem nome de banco"),
        ("postgresql:///jarvis", "sem host"),
    ],
)
def test_dsn_invalido_falha_dizendo_o_que_falta(dsn: str, erro: str) -> None:
    with pytest.raises(ValueError, match=erro):
        PostgresTarget.from_dsn(dsn)


def test_libpq_args_nao_contem_a_senha() -> None:
    alvo = PostgresTarget.from_dsn(DSN_ASYNC)
    assert "senha" not in " ".join(alvo.libpq_args())
    assert alvo.env() == {"PGPASSWORD": "senha"}


def test_sem_senha_nao_define_pgpassword() -> None:
    """PGPASSWORD vazio e PGPASSWORD ausente são coisas diferentes para o libpq:
    o primeiro autentica com senha vazia, o segundo tenta os outros métodos."""
    alvo = PostgresTarget.from_dsn("postgresql://jarvis@postgres:5432/jarvis")
    assert alvo.env() == {}


def test_representacao_de_log_esconde_a_senha() -> None:
    alvo = PostgresTarget.from_dsn(DSN_ASYNC)
    assert alvo.redacted() == "postgresql://jarvis@127.0.0.1:5433/jarvis"
    assert "senha" not in alvo.redacted()
