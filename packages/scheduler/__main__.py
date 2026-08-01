"""Entrada de linha de comando dos jobs: `python -m packages.scheduler <job>`.

Existe por dois motivos concretos, nenhum deles estético:

1. **Backup sob demanda.** Antes de mexer no schema, antes de um restore, antes
   de qualquer coisa arriscada — sem esperar as 3 da manhã.
2. **Provar o aceite.** O aceite da v1.4 é "backup roda sozinho e emite
   `backup.completed`". Aqui o job roda pelo **mesmo caminho** do agendamento
   (`SchedulerManager.run_backup`), com um bus que imprime o que foi publicado.
   Chamar `BackupService` direto provaria menos: pularia justamente o trecho que
   emite o evento.

Os eventos vão para a saída padrão em JSON, uma linha por evento, prefixados por
`EVENT `. É o que o `infrastructure/scripts/backup.sh` mostra no terminal.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from packages.scheduler.config import SchedulerConfig
from packages.scheduler.jobs import SchedulerManager
from packages.shared.contracts import Event

JOBS = ("backup", "cleanup", "reindex")


class StdoutEventBus:
    """`EventBus` que imprime. Satisfaz a porta estruturalmente, sem herança.

    Não é o bus do sistema (esse é o `InProcEventBus` do kernel) — é o bus de uma
    execução avulsa, onde "publicar" significa "aparecer no terminal de quem
    mandou rodar".
    """

    def __init__(self) -> None:
        self.published: list[Event] = []

    async def publish(self, event: Event) -> None:
        self.published.append(event)
        print(f"EVENT {event.model_dump_json()}", flush=True)


async def _run(job: str) -> int:
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        print("DATABASE_URL não definida no ambiente", file=sys.stderr)
        return 2

    bus = StdoutEventBus()
    manager = SchedulerManager.from_database_url(
        dsn, event_bus=bus, config=SchedulerConfig()
    )

    if job == "backup":
        await manager.run_backup()
        # Código de saída é o contrato com o shell: sem o evento, o backup não
        # aconteceu, e o script chamador tem de parar em vez de seguir alegre.
        emitidos = [e for e in bus.published if e.type == "backup.completed"]
        if not emitidos:
            print("backup NÃO emitiu backup.completed", file=sys.stderr)
            return 1
        print(f"BACKUP_ROOT {emitidos[0].payload['root']}", flush=True)
        return 0

    if job == "cleanup":
        await manager.cleanup_logs()
        return 0

    await manager.reindex_knowledge()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m packages.scheduler",
        description="Roda um job do scheduler uma vez, fora do agendamento.",
    )
    parser.add_argument("job", choices=JOBS)
    args = parser.parse_args(argv)
    return asyncio.run(_run(args.job))


if __name__ == "__main__":
    raise SystemExit(main())
