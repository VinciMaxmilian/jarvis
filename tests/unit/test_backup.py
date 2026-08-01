"""`BackupService` — o que o job escreve no disco e quando ele se recusa.

R-5 (`plan-execution.md` §8) é "backup existe e restore nunca é testado". Estes
testes cobrem a metade que dá para cobrir sem banco: **layout, integridade e
recusa**. A outra metade — restore de verdade contra Postgres vazio — é o script
`infrastructure/scripts/restore.sh`, exercitado à mão como parte do aceite.

Nenhum teste aqui chama `pg_dump`: o `CommandRunner` é dublê. O que se está
testando é o job, não o Postgres.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from packages.scheduler.backup import BackupError, BackupService, verify_backup
from packages.scheduler.models import (
    DUMP_NAME,
    LANCEDB_DIRNAME,
    MANIFEST_NAME,
    PARTIAL_SUFFIX,
    CommandResult,
    PostgresTarget,
    sha256_of_file,
)
from packages.scheduler.ports import CommandRunner

# --------------------------------------------------------------------------- #
# Dublês
# --------------------------------------------------------------------------- #


class FakePgDump:
    """`CommandRunner` que escreve um dump falso onde o `--file` mandar.

    Grava conteúdo previsível para que o teste possa afirmar o SHA-256 do
    manifesto contra o do arquivo — que é exatamente o que o restore confere.
    """

    def __init__(
        self,
        *,
        conteudo: bytes = b"PGDMP-dump-de-teste",
        returncode: int = 0,
        stderr: str = "",
        escrever: bool = True,
    ) -> None:
        self.conteudo = conteudo
        self.returncode = returncode
        self.stderr = stderr
        self.escrever = escrever
        self.calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

    async def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        comando = tuple(argv)
        self.calls.append((comando, dict(env or {})))
        if self.escrever and self.returncode == 0:
            destino = Path(comando[comando.index("--file") + 1])
            destino.write_bytes(self.conteudo)
        return CommandResult(
            argv=comando, returncode=self.returncode, stderr=self.stderr
        )


def make_target() -> PostgresTarget:
    return PostgresTarget(
        host="postgres",
        port=5432,
        user="jarvis",
        password="senha-secreta",
        database="jarvis",
    )


def make_service(
    tmp_path: Path,
    runner: CommandRunner,
    *,
    lancedb: Path | None = None,
    retention: int = 7,
    instante: datetime | None = None,
) -> BackupService:
    relogio = instante or datetime(2026, 7, 30, 3, 15, 0, tzinfo=UTC)
    return BackupService(
        target=make_target(),
        backup_root=tmp_path / "backups",
        runner=runner,
        lancedb_path=lancedb,
        retention=retention,
        clock=lambda: relogio,
    )


# --------------------------------------------------------------------------- #
# Caminho feliz
# --------------------------------------------------------------------------- #


async def test_backup_escreve_dump_manifesto_e_carimbo_utc(tmp_path: Path) -> None:
    runner = FakePgDump()

    resultado = await make_service(tmp_path, runner).run()

    raiz = Path(resultado.root)
    assert raiz.name == "20260730T031500Z"
    assert (raiz / DUMP_NAME).is_file()
    assert (raiz / MANIFEST_NAME).is_file()
    assert resultado.manifest.database == "jarvis"
    assert resultado.manifest.postgres.bytes == len(runner.conteudo)


async def test_manifesto_guarda_o_sha256_real_do_dump(tmp_path: Path) -> None:
    """O digest é o contrato com o restore: se mentir, o restore recusa backup bom."""
    runner = FakePgDump(conteudo=b"conteudo-especifico-deste-teste")

    resultado = await make_service(tmp_path, runner).run()

    dump = Path(resultado.root) / DUMP_NAME
    assert resultado.manifest.postgres.sha256 == sha256_of_file(dump)
    assert verify_backup(Path(resultado.root)) == []


async def test_backup_recem_feito_passa_na_propria_verificacao(tmp_path: Path) -> None:
    vetores = tmp_path / "lancedb"
    (vetores / "tabela.lance").mkdir(parents=True)
    (vetores / "tabela.lance" / "dados.arrow").write_bytes(b"vetores")

    resultado = await make_service(tmp_path, FakePgDump(), lancedb=vetores).run()

    assert verify_backup(Path(resultado.root)) == []


async def test_verificacao_acusa_dump_adulterado(tmp_path: Path) -> None:
    """Um byte trocado tem de reprovar — senão o digest é decoração."""
    resultado = await make_service(tmp_path, FakePgDump()).run()

    dump = Path(resultado.root) / DUMP_NAME
    dump.write_bytes(b"conteudo-diferente-do-que-foi-registrado")

    problemas = verify_backup(Path(resultado.root))
    assert any("sha256" in p for p in problemas), problemas


# --------------------------------------------------------------------------- #
# Argumentos e senha
# --------------------------------------------------------------------------- #


async def test_pg_dump_recebe_formato_custom_e_sem_dono(tmp_path: Path) -> None:
    """`--format=custom` é o que o pg_restore precisa; `--no-owner` é o que faz
    o restore funcionar num container novo, com roles diferentes."""
    runner = FakePgDump()

    await make_service(tmp_path, runner).run()

    argv, _ = runner.calls[0]
    assert "--format=custom" in argv
    assert "--no-owner" in argv
    assert "--no-privileges" in argv
    assert argv[0] == "pg_dump"


async def test_senha_nao_entra_no_argv(tmp_path: Path) -> None:
    """Argumento de processo é público (`ps`, log, crash report). A senha vai em
    PGPASSWORD e em lugar nenhum mais."""
    runner = FakePgDump()

    await make_service(tmp_path, runner).run()

    argv, env = runner.calls[0]
    assert not any("senha-secreta" in parte for parte in argv)
    assert env["PGPASSWORD"] == "senha-secreta"


# --------------------------------------------------------------------------- #
# LanceDB
# --------------------------------------------------------------------------- #


async def test_lancedb_ausente_e_caso_normal_nao_erro(tmp_path: Path) -> None:
    """Nesta máquina o LanceDB não roda (SIGILL sem AVX2), então o diretório não
    existe. Isso não pode reprovar o backup do Postgres."""
    servico = make_service(tmp_path, FakePgDump(), lancedb=tmp_path / "nao-existe")

    resultado = await servico.run()

    assert resultado.manifest.lancedb is None
    assert resultado.manifest.postgres.bytes > 0


async def test_lancedb_presente_e_copiado_com_a_arvore_inteira(tmp_path: Path) -> None:
    vetores = tmp_path / "lancedb"
    (vetores / "knowledge.lance" / "data").mkdir(parents=True)
    (vetores / "knowledge.lance" / "data" / "0.lance").write_bytes(b"x" * 64)
    (vetores / "knowledge.lance" / "_versions").mkdir()
    (vetores / "knowledge.lance" / "_versions" / "1.manifest").write_bytes(b"y" * 16)

    resultado = await make_service(tmp_path, FakePgDump(), lancedb=vetores).run()

    copia = Path(resultado.root) / LANCEDB_DIRNAME
    assert (copia / "knowledge.lance" / "data" / "0.lance").read_bytes() == b"x" * 64
    assert resultado.manifest.lancedb is not None
    assert resultado.manifest.lancedb.files == 2
    assert resultado.manifest.lancedb.bytes == 80


async def test_snapshot_do_lancedb_nao_importa_a_biblioteca() -> None:
    """Guarda contra regressão: `import lancedb` mata o processo nesta CPU.

    Ler o texto do módulo é feio, mas importar para checar seria o próprio bug.
    """
    fonte = Path(__file__).resolve().parents[2] / "packages" / "scheduler"
    for arquivo in sorted(fonte.rglob("*.py")):
        texto = arquivo.read_text(encoding="utf-8")
        for linha in texto.splitlines():
            despido = linha.strip()
            assert not despido.startswith(("import lancedb", "from lancedb")), (
                f"{arquivo.name} importa lancedb — SIGILL em CPU sem AVX2"
            )


# --------------------------------------------------------------------------- #
# Falha
# --------------------------------------------------------------------------- #


async def test_pg_dump_com_erro_levanta_e_nao_deixa_diretorio(tmp_path: Path) -> None:
    """Falha não pode deixar para trás algo com cara de backup."""
    runner = FakePgDump(returncode=1, stderr='pg_dump: error: connection failed\n')
    servico = make_service(tmp_path, runner)

    with pytest.raises(BackupError, match="pg_dump falhou"):
        await servico.run()

    raiz = tmp_path / "backups"
    assert list(raiz.iterdir()) == []


async def test_dump_vazio_e_recusado(tmp_path: Path) -> None:
    """`pg_dump` que devolve 0 e escreve 0 byte existe (disco cheio). Não é backup."""
    runner = FakePgDump(conteudo=b"")
    with pytest.raises(BackupError, match="0 byte"):
        await make_service(tmp_path, runner).run()


async def test_dump_nao_escrito_e_recusado(tmp_path: Path) -> None:
    runner = FakePgDump(escrever=False)
    with pytest.raises(BackupError, match="não escreveu"):
        await make_service(tmp_path, runner).run()


async def test_binario_ausente_vira_falha_de_backup(tmp_path: Path) -> None:
    """`AsyncSubprocessRunner` devolve 127 quando o binário não existe. O serviço
    tem de transformar isso em BackupError, não em backup vazio."""
    runner = FakePgDump(returncode=127, stderr="binário não encontrado: 'pg_dump'")

    with pytest.raises(BackupError, match="não encontrado"):
        await make_service(tmp_path, runner).run()


# --------------------------------------------------------------------------- #
# Retenção e diretório parcial
# --------------------------------------------------------------------------- #


async def test_retencao_guarda_os_n_mais_recentes(tmp_path: Path) -> None:
    base = datetime(2026, 7, 1, 3, 0, 0, tzinfo=UTC)
    raiz = tmp_path / "backups"

    for dia in range(5):
        instante = base + timedelta(days=dia)
        servico = BackupService(
            target=make_target(),
            backup_root=raiz,
            runner=FakePgDump(),
            retention=3,
            clock=lambda instante=instante: instante,  # type: ignore[misc]
        )
        resultado = await servico.run()

    guardados = sorted(p.name for p in raiz.iterdir())
    assert guardados == [
        "20260703T030000Z",
        "20260704T030000Z",
        "20260705T030000Z",
    ]
    assert resultado.pruned == ("20260702T030000Z",)


async def test_diretorio_parcial_e_ignorado_pela_retencao(tmp_path: Path) -> None:
    """`.partial` é lixo de execução morta: não conta como backup e é varrido."""
    raiz = tmp_path / "backups"
    (raiz / f"20260101T000000Z{PARTIAL_SUFFIX}").mkdir(parents=True)

    servico = make_service(tmp_path, FakePgDump(), retention=1)
    resultado = await servico.run()

    nomes = {p.name for p in raiz.iterdir()}
    assert nomes == {"20260730T031500Z"}
    assert resultado.pruned == ()


async def test_dois_backups_no_mesmo_segundo_nao_colidem(tmp_path: Path) -> None:
    servico = make_service(tmp_path, FakePgDump())

    primeiro = await servico.run()
    segundo = await servico.run()

    assert Path(primeiro.root).name == "20260730T031500Z"
    assert Path(segundo.root).name == "20260730T031500Z-1"


async def test_retencao_zero_e_recusada_na_construcao(tmp_path: Path) -> None:
    """Retenção 0 apagaria o backup recém-escrito. Erro de construção, não runtime."""
    with pytest.raises(ValueError, match="retention"):
        BackupService(
            target=make_target(),
            backup_root=tmp_path,
            runner=FakePgDump(),
            retention=0,
        )
