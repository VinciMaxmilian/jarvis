"""Os três aceites da v1.2, exercidos contra subprocesso de verdade.

`plan-execution.md` §3 v1.2 pede exatamente isto:

1. capability `python` de exemplo executa de ponta a ponta e devolve resultado;
2. capability declarada **sem** `network` que tenta abrir socket falha com erro
   de permissão;
3. capability em laço infinito é morta pelo timeout e o Executive recebe
   `TaskFailed`, sem travar.

**Nada aqui é mock.** Um teste de isolamento com o subprocesso mockado prova que
o mock funciona. Estes testes montam o pedido, rodam `python -m`, deixam o
supervisor matar o que tem de morrer e leem o envelope que voltou — que é o
caminho que o Executive vai exercer em produção.

Custam segundos, não milissegundos, e isso é aceitável: são cinco execuções reais
e o resto da suíte continua em memória.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from packages.kernel import Kernel
from packages.kernel.errors import RuntimeNotSupported, ToolNotInCapability
from packages.kernel.runtime import (
    ExecutionLimits,
    ExecutionRequest,
    ExecutionStatus,
    PythonRuntime,
)
from packages.shared.contracts import (
    CapabilityManifest,
    CapabilityPermissions,
    CapabilityStatus,
    Event,
    EventType,
    ToolSpec,
)

#: Módulos de `tests/fixtures/capabilities/`. Importáveis do subprocesso porque o
#: `PythonRuntime` põe a raiz do repo no `PYTHONPATH` do filho.
BASE_FIXTURES = "tests.fixtures.capabilities"


class BusDeTeste:
    """`EventBus` que guarda o que passou. O `InProcEventBus` real tem consumidor
    e fila; aqui o assunto é *o que* o kernel publica, não como o bus entrega."""

    def __init__(self) -> None:
        self.eventos: list[Event] = []

    async def publish(self, event: Event) -> None:
        self.eventos.append(event)

    def tipos(self) -> list[str]:
        return [e.type for e in self.eventos]


def manifesto(
    *,
    modulo: str,
    tools: list[str],
    permissions: CapabilityPermissions | None = None,
    runtime: str = "python",
) -> CapabilityManifest:
    return CapabilityManifest(
        name=modulo.rsplit(".", 1)[-1],
        version="1.0.0",
        description="capability de teste",
        status=CapabilityStatus.ACTIVE,
        entrypoint=f"{modulo}:handler",
        runtime=runtime,
        permissions=permissions or CapabilityPermissions(),
        tools=[
            ToolSpec(name=t, description=f"tool {t}", input_schema={"type": "object"})
            for t in tools
        ],
    )


def kernel_com_bus() -> tuple[Kernel, BusDeTeste]:
    bus = BusDeTeste()
    return Kernel([PythonRuntime()], event_bus=bus), bus


# --------------------------------------------------------------------------- #
# Aceite 1 — executa de ponta a ponta
# --------------------------------------------------------------------------- #


async def test_capability_python_executa_e_devolve_resultado(tmp_path: Path) -> None:
    """O aceite central: subprocesso de verdade, resultado de volta."""
    kernel, bus = kernel_com_bus()
    request = ExecutionRequest(
        manifest=manifesto(modulo=f"{BASE_FIXTURES}.cap_ok", tools=["somar"]),
        tool="somar",
        arguments={"parcelas": [2, 3, 4]},
        directory=tmp_path,
        task_id=uuid4(),
    )

    resultado = await kernel.run(request)

    assert resultado.status is ExecutionStatus.OK, resultado.error
    assert resultado.output == {"total": 9}
    assert resultado.exit_code == 0
    # O processo existiu de verdade: sem subprocesso não há duração medida.
    assert resultado.duration_ms > 0
    assert bus.tipos() == [EventType.TOOL_CALLED, EventType.TOOL_FINISHED]


async def test_escrita_dentro_do_diretorio_da_capability_e_permitida(
    tmp_path: Path,
) -> None:
    """A contraprova do teste de negação: o que foi declarado tem de passar.

    Um guarda que nega tudo passaria no teste de permissão e seria inútil.
    """
    kernel, _ = kernel_com_bus()
    resultado = await kernel.run(
        ExecutionRequest(
            manifest=manifesto(
                modulo=f"{BASE_FIXTURES}.cap_ok",
                tools=["escrever"],
                permissions=CapabilityPermissions(filesystem=[str(tmp_path)]),
            ),
            tool="escrever",
            arguments={"nome": "saida.txt", "conteudo": "ok"},
            directory=tmp_path,
        )
    )

    assert resultado.status is ExecutionStatus.OK, resultado.error
    assert (tmp_path / "saida.txt").read_text(encoding="utf-8") == "ok"


async def test_primeira_execucao_em_dry_run_nao_tem_efeito(tmp_path: Path) -> None:
    """`plan-execution.md` §7: a primeira execução de capability nova é ensaio.

    E o ensaio precisa dizer *o que faria* — o `_child` passa `dry_run` a quem o
    declara, e é isso que separa "importou" de "faria isto" no log do Gate 2.
    """
    kernel, _ = kernel_com_bus()
    resultado = await kernel.run(
        ExecutionRequest(
            manifest=manifesto(
                modulo=f"{BASE_FIXTURES}.cap_ok",
                tools=["escrever"],
                permissions=CapabilityPermissions(filesystem=[str(tmp_path)]),
            ),
            tool="escrever",
            arguments={"nome": "nao_deve_existir.txt", "conteudo": "x"},
            directory=tmp_path,
            dry_run=True,
        )
    )

    assert resultado.status is ExecutionStatus.OK, resultado.error
    assert resultado.dry_run is True
    assert resultado.output is not None
    assert resultado.output["executado"] is False
    assert resultado.output["escreveria"] == "nao_deve_existir.txt"
    assert not (tmp_path / "nao_deve_existir.txt").exists()


# --------------------------------------------------------------------------- #
# Aceite 2 — sem `network` declarada, não alcança a rede
# --------------------------------------------------------------------------- #


async def test_sem_network_declarada_o_socket_e_negado(tmp_path: Path) -> None:
    """O aceite que separa permissão declarada de permissão aplicada."""
    kernel, bus = kernel_com_bus()
    resultado = await kernel.run(
        ExecutionRequest(
            manifest=manifesto(modulo=f"{BASE_FIXTURES}.cap_rede", tools=["buscar"]),
            tool="buscar",
            arguments={"host": "1.1.1.1", "porta": 80},
            directory=tmp_path,
            task_id=uuid4(),
        )
    )

    assert resultado.status is ExecutionStatus.DENIED
    assert resultado.error is not None
    assert "1.1.1.1" in resultado.error
    assert any("1.1.1.1" in alvo for alvo in resultado.denied)
    # Desfecho não-OK avisa o Executive pelo bus, e não por exceção.
    assert EventType.TASK_FAILED in bus.tipos()


async def test_a_negacao_acontece_ja_na_resolucao_de_nome(tmp_path: Path) -> None:
    """Negar só no `connect` deixaria a consulta DNS sair da máquina.

    O host consultado já é informação vazando — e é a informação que diz ao
    servidor de DNS que esta máquina existe e o que ela procura.
    """
    kernel, _ = kernel_com_bus()
    resultado = await kernel.run(
        ExecutionRequest(
            manifest=manifesto(modulo=f"{BASE_FIXTURES}.cap_rede", tools=["resolver"]),
            tool="resolver",
            arguments={"host": "example.com"},
            directory=tmp_path,
        )
    )

    assert resultado.status is ExecutionStatus.DENIED
    assert resultado.error is not None
    assert "example.com" in resultado.error


async def test_host_declarado_nao_e_negado_pelo_guarda(tmp_path: Path) -> None:
    """Contraprova da negação: o host declarado passa pelo guarda.

    A conexão em si pode falhar (o container de teste não tem rede, e é bom que
    não tenha) — o que este teste fixa é que a falha **não** é `DENIED`. Guarda
    que nega o que foi declarado é tão quebrado quanto guarda que permite tudo.
    """
    kernel, _ = kernel_com_bus()
    resultado = await kernel.run(
        ExecutionRequest(
            manifest=manifesto(
                modulo=f"{BASE_FIXTURES}.cap_rede",
                tools=["buscar"],
                permissions=CapabilityPermissions(network=["127.0.0.1"]),
            ),
            tool="buscar",
            arguments={"host": "127.0.0.1", "porta": 9},
            directory=tmp_path,
        )
    )

    assert resultado.status is not ExecutionStatus.DENIED
    assert not resultado.denied


# --------------------------------------------------------------------------- #
# Aceite 3 — laço infinito morre no timeout, e o Executive fica sabendo
# --------------------------------------------------------------------------- #


async def test_laco_infinito_e_morto_pelo_timeout(tmp_path: Path) -> None:
    """O supervisor mata; o kernel devolve `TIMEOUT` e publica `task.failed`.

    O `await` deste teste retornando é, ele próprio, metade do aceite: se o
    supervisor não matasse, o teste não terminaria.
    """
    kernel, bus = kernel_com_bus()
    task_id = uuid4()

    resultado = await kernel.run(
        ExecutionRequest(
            manifest=manifesto(modulo=f"{BASE_FIXTURES}.cap_loop", tools=["travar"]),
            tool="travar",
            directory=tmp_path,
            task_id=task_id,
            limits=ExecutionLimits(timeout_seconds=2.0),
        )
    )

    assert resultado.status is ExecutionStatus.TIMEOUT
    assert resultado.error is not None
    assert "2s" in resultado.error

    falhas = [e for e in bus.eventos if e.type == EventType.TASK_FAILED]
    assert len(falhas) == 1
    assert falhas[0].task_id == task_id
    assert falhas[0].payload["status"] == ExecutionStatus.TIMEOUT.value


# --------------------------------------------------------------------------- #
# O que é erro de quem chamou, e por isso levanta
# --------------------------------------------------------------------------- #


async def test_runtime_desconhecido_diz_quais_existem(tmp_path: Path) -> None:
    """A razão de `runtime` ser `str` e não `Literal`: o conjunto é da instalação."""
    kernel, _ = kernel_com_bus()
    with pytest.raises(RuntimeNotSupported) as exc:
        await kernel.run(
            ExecutionRequest(
                manifest=manifesto(
                    modulo=f"{BASE_FIXTURES}.cap_ok", tools=["somar"], runtime="wasm"
                ),
                tool="somar",
                directory=tmp_path,
            )
        )

    assert "wasm" in str(exc.value)
    assert "python" in str(exc.value)


async def test_tool_fora_do_manifest_falha_antes_de_gastar_processo(
    tmp_path: Path,
) -> None:
    """Barato antes de caro: não se paga um `fork` para descobrir isto."""
    kernel, bus = kernel_com_bus()
    with pytest.raises(ToolNotInCapability):
        await kernel.run(
            ExecutionRequest(
                manifest=manifesto(modulo=f"{BASE_FIXTURES}.cap_ok", tools=["somar"]),
                tool="inexistente",
                directory=tmp_path,
            )
        )

    # Nem `tool.called` foi publicado: a execução não chegou a começar.
    assert bus.eventos == []


async def test_capability_que_levanta_volta_como_status_e_nao_excecao(
    tmp_path: Path,
) -> None:
    """Falha da capability é campo, não exceção — senão o laço do Executive morre."""
    kernel, bus = kernel_com_bus()
    resultado = await kernel.run(
        ExecutionRequest(
            manifest=manifesto(modulo=f"{BASE_FIXTURES}.cap_ok", tools=["explodir"]),
            tool="explodir",
            directory=tmp_path,
            task_id=uuid4(),
        )
    )

    assert resultado.status is ExecutionStatus.FAILED
    assert resultado.error is not None
    assert "explodir" in resultado.error
    assert EventType.TASK_FAILED in bus.tipos()
