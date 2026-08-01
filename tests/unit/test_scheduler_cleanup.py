"""`CleanupService` — poda de log por idade e recolhimento de chave sem TTL.

Os dois lados têm a mesma armadilha: apagar de menos não custa nada hoje e apagar
de mais custa tudo hoje. Por isso os testes de "não apagou" são tantos quanto os
de "apagou".
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from packages.scheduler.cleanup import CleanupService

AGORA = datetime(2026, 7, 30, 4, 0, 0, tzinfo=UTC)


class FakeKeyspace:
    """`ShortTermKeyspace` em dicionário. `-1` sem TTL, `-2` inexistente."""

    def __init__(self, ttls: dict[str, int]) -> None:
        self.ttls = dict(ttls)
        self.deleted: list[str] = []

    async def scan(self, pattern: str) -> list[str]:
        prefixo = pattern.rstrip("*")
        return sorted(k for k in self.ttls if k.startswith(prefixo))

    async def ttl_seconds(self, key: str) -> int:
        return self.ttls.get(key, -2)

    async def delete(self, keys: Sequence[str]) -> int:
        apagadas = 0
        for chave in keys:
            if self.ttls.pop(chave, None) is not None:
                self.deleted.append(chave)
                apagadas += 1
        return apagadas


def envelhecer(arquivo: Path, *, dias: int) -> None:
    """Empurra o mtime para trás — o job decide por mtime, não por nome."""
    quando = (AGORA - timedelta(days=dias)).timestamp()
    os.utime(arquivo, (quando, quando))


# --------------------------------------------------------------------------- #
# Logs
# --------------------------------------------------------------------------- #


async def test_apaga_log_mais_velho_que_o_limite(tmp_path: Path) -> None:
    antigo = tmp_path / "api.log"
    antigo.write_text("linha antiga\n", encoding="utf-8")
    envelhecer(antigo, dias=30)

    resultado = await CleanupService(
        log_dir=tmp_path, max_age_days=14, clock=lambda: AGORA
    ).run()

    assert resultado.log_files_removed == 1
    assert resultado.log_bytes_freed == len(b"linha antiga\n")
    assert not antigo.exists()


async def test_preserva_log_dentro_do_limite(tmp_path: Path) -> None:
    recente = tmp_path / "api.log"
    recente.write_text("de ontem\n", encoding="utf-8")
    envelhecer(recente, dias=1)

    resultado = await CleanupService(
        log_dir=tmp_path, max_age_days=14, clock=lambda: AGORA
    ).run()

    assert resultado.log_files_removed == 0
    assert recente.exists()


async def test_so_apaga_o_que_parece_log(tmp_path: Path) -> None:
    """O job varre um diretório configurável. Se o filtro fosse `*`, apontar a
    variável para a pasta errada apagaria o repositório."""
    for nome in ("api.log", "eventos.jsonl", "backup.dump", "config.yaml", "notas.md"):
        arquivo = tmp_path / nome
        arquivo.write_text("x", encoding="utf-8")
        envelhecer(arquivo, dias=99)

    resultado = await CleanupService(
        log_dir=tmp_path, max_age_days=7, clock=lambda: AGORA
    ).run()

    assert resultado.log_files_removed == 2
    assert sorted(resultado.log_files) == ["api.log", "eventos.jsonl"]
    assert (tmp_path / "backup.dump").exists()
    assert (tmp_path / "config.yaml").exists()
    assert (tmp_path / "notas.md").exists()


async def test_apaga_log_rotacionado_em_subdiretorio(tmp_path: Path) -> None:
    sub = tmp_path / "orchestrator"
    sub.mkdir()
    rotacionado = sub / "run.log.3"
    rotacionado.write_text("velho", encoding="utf-8")
    envelhecer(rotacionado, dias=60)

    resultado = await CleanupService(
        log_dir=tmp_path, max_age_days=14, clock=lambda: AGORA
    ).run()

    assert resultado.log_files == ("orchestrator/run.log.3",)


async def test_diretorio_de_log_inexistente_nao_e_erro(tmp_path: Path) -> None:
    resultado = await CleanupService(
        log_dir=tmp_path / "nao-existe", clock=lambda: AGORA
    ).run()

    assert resultado.log_files_removed == 0
    assert resultado.nada_a_fazer


async def test_idade_zero_e_recusada_na_construcao() -> None:
    """`max_age_days=0` apagaria o log de hoje, inclusive o da própria execução."""
    with pytest.raises(ValueError, match="max_age_days"):
        CleanupService(max_age_days=0)


# --------------------------------------------------------------------------- #
# Short-term memory
# --------------------------------------------------------------------------- #


async def test_recolhe_apenas_chave_sem_expiracao(tmp_path: Path) -> None:
    """O Redis já apaga sozinho o que tem TTL. O que vaza é a chave imortal num
    keyspace que deveria ser todo efêmero — é essa que o job recolhe."""
    keyspace = FakeKeyspace(
        {
            "jarvis:short:goal:1": 3600,  # expira sozinha
            "jarvis:short:goal:2": -1,  # imortal: vazou
            "jarvis:short:task:9": -1,  # imortal: vazou
            "jarvis:long:fato:1": -1,  # fora do padrão: não é problema deste job
        }
    )

    resultado = await CleanupService(
        keyspace=keyspace, short_term_pattern="jarvis:short:*", clock=lambda: AGORA
    ).run()

    assert resultado.short_term_keys_scanned == 3
    assert resultado.short_term_keys_removed == 2
    assert sorted(keyspace.deleted) == ["jarvis:short:goal:2", "jarvis:short:task:9"]
    assert "jarvis:short:goal:1" in keyspace.ttls
    assert "jarvis:long:fato:1" in keyspace.ttls


async def test_keyspace_limpo_nao_apaga_nada() -> None:
    keyspace = FakeKeyspace({"jarvis:short:a": 60, "jarvis:short:b": 120})

    resultado = await CleanupService(keyspace=keyspace, clock=lambda: AGORA).run()

    assert resultado.short_term_keys_scanned == 2
    assert resultado.short_term_keys_removed == 0
    assert keyspace.deleted == []


async def test_sem_keyspace_o_job_ainda_poda_os_logs(tmp_path: Path) -> None:
    """Redis fora do ar não pode impedir a faxina de disco."""
    arquivo = tmp_path / "api.log"
    arquivo.write_text("velho", encoding="utf-8")
    envelhecer(arquivo, dias=90)

    resultado = await CleanupService(
        log_dir=tmp_path, keyspace=None, clock=lambda: AGORA
    ).run()

    assert resultado.log_files_removed == 1
    assert resultado.short_term_keys_scanned == 0
