"""`AsyncSubprocessRunner` — a única peça do scheduler que fala com o SO.

Todo o resto da fatia v1.4 é testado com `CommandRunner` dublê (ver
`tests/unit/test_backup.py`), o que é certo: o que se quer provar lá é o job, não
o Postgres. Só que isso deixava **sem teste nenhum** justamente o adaptador que
executa o `pg_dump` de verdade em produção — e é nele que moram as três falhas
que o backup encontra no mundo real: binário ausente, processo travado e código
de saída diferente de zero.

Aqui os subprocessos são reais, mas o binário é o **próprio interpretador**
(`sys.executable`), não `sh`/`pg_dump`: é determinístico, existe em qualquer
plataforma onde a suíte rode e não depende de rede, de PATH nem de o
postgresql-client estar instalado.
"""

from __future__ import annotations

import sys

import pytest

from packages.scheduler.ports import CommandRunner
from packages.scheduler.runner import (
    EXIT_NOT_FOUND,
    EXIT_TIMEOUT,
    AsyncSubprocessRunner,
)

# --------------------------------------------------------------------------- #
# Auxiliares
# --------------------------------------------------------------------------- #


def python_c(codigo: str) -> list[str]:
    """`argv` que roda um trecho de Python no mesmo interpretador da suíte."""
    return [sys.executable, "-c", codigo]


# --------------------------------------------------------------------------- #
# Contrato
# --------------------------------------------------------------------------- #


def test_satisfaz_a_porta_command_runner() -> None:
    """O `BackupService` recebe isto como `CommandRunner`; se a forma divergir, o
    erro tem de aparecer aqui e não às 3h da manhã."""
    assert isinstance(AsyncSubprocessRunner(), CommandRunner)


async def test_argv_vazio_e_recusado() -> None:
    with pytest.raises(ValueError, match="argv vazio"):
        await AsyncSubprocessRunner().run([])


# --------------------------------------------------------------------------- #
# Caminho feliz
# --------------------------------------------------------------------------- #


async def test_comando_bem_sucedido_devolve_stdout_e_ok() -> None:
    resultado = await AsyncSubprocessRunner().run(
        python_c("print('dump pronto')")
    )

    assert resultado.ok
    assert resultado.returncode == 0
    assert "dump pronto" in resultado.stdout
    assert resultado.stderr == ""


async def test_argv_volta_no_resultado_para_o_log() -> None:
    """`CommandResult.argv` é o que vai para o log — precisa ser o comando real."""
    argv = python_c("pass")
    resultado = await AsyncSubprocessRunner().run(argv)

    assert resultado.argv == tuple(argv)


# --------------------------------------------------------------------------- #
# Falhas que o backup precisa distinguir
# --------------------------------------------------------------------------- #


async def test_codigo_de_saida_diferente_de_zero_nao_e_ok() -> None:
    resultado = await AsyncSubprocessRunner().run(
        python_c(
            "import sys; sys.stderr.write('pg_dump: erro de conexao\\n'); sys.exit(3)"
        )
    )

    assert not resultado.ok
    assert resultado.returncode == 3
    # É esta linha que o `BackupError` carrega para o log do job.
    assert resultado.resumo_do_erro == "pg_dump: erro de conexao"


async def test_binario_ausente_vira_resultado_e_nao_excecao() -> None:
    """Binário que não existe **não** pode explodir: o job trata `ok=False`.

    Se isto virasse `FileNotFoundError`, a mensagem que o dono veria seria um
    traceback de `asyncio`, e não a única frase que resolve o problema — que a
    imagem precisa do postgresql-client.
    """
    resultado = await AsyncSubprocessRunner().run(
        ["jarvis-binario-que-nao-existe-em-lugar-nenhum"]
    )

    assert not resultado.ok
    assert resultado.returncode == EXIT_NOT_FOUND
    assert "postgresql-client" in resultado.stderr


async def test_processo_travado_e_morto_no_timeout() -> None:
    """Sem isto, um `pg_dump` pendurado segura o job até o backup do dia seguinte."""
    resultado = await AsyncSubprocessRunner().run(
        python_c("import time; time.sleep(30)"), timeout_seconds=0.2
    )

    assert not resultado.ok
    assert resultado.returncode == EXIT_TIMEOUT
    assert "tempo esgotado" in resultado.stderr


async def test_stdout_com_bytes_invalidos_nao_derruba_a_decodificacao() -> None:
    """`errors="replace"`: saída suja de um binário não pode virar exceção."""
    resultado = await AsyncSubprocessRunner().run(
        python_c("import sys; sys.stdout.buffer.write(b'\\xff\\xfe ok')")
    )

    assert resultado.ok
    assert "ok" in resultado.stdout


# --------------------------------------------------------------------------- #
# Ambiente — é por aqui que a senha viaja
# --------------------------------------------------------------------------- #


async def test_env_extra_chega_ao_processo_filho() -> None:
    """`PGPASSWORD` é passado por `env`, nunca por `argv` (ver `PostgresTarget`)."""
    resultado = await AsyncSubprocessRunner().run(
        python_c("import os; print(os.environ.get('PGPASSWORD', 'AUSENTE'))"),
        env={"PGPASSWORD": "senha-secreta"},
    )

    assert resultado.ok
    assert "senha-secreta" in resultado.stdout


async def test_ambiente_do_processo_pai_e_herdado_por_padrao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`pg_dump` lê `PGSSLMODE`/`PGCONNECT_TIMEOUT` do ambiente herdado."""
    monkeypatch.setenv("JARVIS_MARCADOR_HERANCA", "presente")

    resultado = await AsyncSubprocessRunner().run(
        python_c("import os; print(os.environ.get('JARVIS_MARCADOR_HERANCA', 'AUSENTE'))")
    )

    assert "presente" in resultado.stdout


async def test_sem_heranca_o_ambiente_do_pai_nao_vaza(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JARVIS_MARCADOR_HERANCA", "presente")
    runner = AsyncSubprocessRunner(inherit_env=False)

    resultado = await runner.run(
        python_c("import os; print(os.environ.get('JARVIS_MARCADOR_HERANCA', 'AUSENTE'))")
    )

    assert "AUSENTE" in resultado.stdout


async def test_env_explicito_sobrescreve_o_herdado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ordem importa: o que o chamador passa ganha do que estava no ambiente."""
    monkeypatch.setenv("PGPASSWORD", "senha-do-ambiente")

    resultado = await AsyncSubprocessRunner().run(
        python_c("import os; print(os.environ['PGPASSWORD'])"),
        env={"PGPASSWORD": "senha-do-alvo"},
    )

    assert "senha-do-alvo" in resultado.stdout
