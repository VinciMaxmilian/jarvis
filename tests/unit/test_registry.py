"""`discover()`, `get_active()`, `resolve()` e a persistência do Capability Registry.

Os manifests são escritos em YAML de verdade em diretório temporário: o bug que
importa é o do parse e o da varredura de disco, e mock de `open()` esconde
exatamente esses dois.

Este arquivo era a especificação executável da v1.1: quatro `xfail(strict=True)`
descreviam o comportamento exigido pelo `plan.md` §6 e ausente do código (D-1 a
D-4). As marcas saíram porque o comportamento entrou — e os testes que fixavam o
comportamento *antigo* (miss por exceção, manifest inválido sumindo em silêncio)
foram invertidos, não apagados: eles agora fixam o novo, que é o que impede a
regressão de voltar sem ninguém notar.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from structlog.testing import capture_logs

from packages.kernel.event_bus import InProcEventBus
from packages.registry import (
    CapabilityHealth,
    CapabilityRecord,
    CapabilityRegistry,
    CapabilityStore,
    GoalBlocker,
    capability_id,
    compute_capability_digest,
)
from packages.shared.contracts import (
    CapabilityStatus,
    Event,
    EventType,
    Goal,
    GoalStatus,
    utcnow,
)
from tests.conftest import InMemoryEventBus, InMemoryGoalStore


def escrever_capability(
    base: Path,
    name: str,
    *,
    status: str = "active",
    dir_name: str | None = None,
    description: str = "capability de teste",
    tools: list[dict[str, Any]] | None = None,
    extra: dict[str, Any] | None = None,
    conteudo_bruto: str | None = None,
) -> Path:
    """Cria `<base>/<dir>/manifest.yaml` e devolve o diretório da capability."""
    caps_dir = base / (dir_name or name)
    caps_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = caps_dir / "manifest.yaml"

    if conteudo_bruto is not None:
        manifest_path.write_text(conteudo_bruto, encoding="utf-8")
        return caps_dir

    dados: dict[str, Any] = {
        "name": name,
        "version": "0.1.0",
        "description": description,
        "status": status,
        "entrypoint": f"capabilities.{name}.server:main",
        "transport": "mcp_stdio",
        "tools": tools or [],
    }
    dados.update(extra or {})
    manifest_path.write_text(
        yaml.safe_dump(dados, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return caps_dir


class FakeCapabilityStore:
    """`CapabilityStore` em dicionário, com a semântica do `PgCapabilityStore`.

    Guarda cópias e casa por `name` — inclusive a regra de `last_used_at` só
    avançar, que é o que impede um `discover()` sem hidratação de apagar o
    último uso já gravado.
    """

    def __init__(self) -> None:
        self.rows: dict[str, CapabilityRecord] = {}
        self.upserts = 0

    async def upsert(self, record: CapabilityRecord) -> CapabilityRecord:
        self.upserts += 1
        anterior = self.rows.get(record.name)
        if anterior is not None and record.last_used_at is None:
            record = record.model_copy(update={"last_used_at": anterior.last_used_at})
        self.rows[record.name] = record.model_copy(deep=True)
        return record

    async def list_all(self) -> list[CapabilityRecord]:
        ordenados = sorted(self.rows.values(), key=lambda r: r.name)
        return [r.model_copy(deep=True) for r in ordenados]

    async def get_by_name(self, name: str) -> CapabilityRecord | None:
        row = self.rows.get(name)
        return row.model_copy(deep=True) if row else None

    async def mark_used(self, name: str, when: Any) -> None:
        row = self.rows.get(name)
        if row is not None:
            row.last_used_at = when

    async def set_health(self, name: str, health: CapabilityHealth) -> None:
        row = self.rows.get(name)
        if row is not None:
            row.health = health


# --------------------------------------------------------------------------- #
# discover()
# --------------------------------------------------------------------------- #


def test_discover_carrega_manifest_yaml_real(tmp_path: Path) -> None:
    escrever_capability(tmp_path, "nas_sync")
    registry = CapabilityRegistry(tmp_path)

    registry.discover()

    carregadas = registry.get_all()
    assert [c.manifest.name for c in carregadas] == ["nas_sync"]
    assert carregadas[0].manifest.version == "0.1.0"


def test_discover_em_diretorio_inexistente_nao_levanta(tmp_path: Path) -> None:
    registry = CapabilityRegistry(tmp_path / "nao_existe")

    registry.discover()

    assert registry.get_all() == []


def test_discover_ignora_diretorio_sem_manifest(tmp_path: Path) -> None:
    (tmp_path / "sem_manifest").mkdir()
    registry = CapabilityRegistry(tmp_path)

    registry.discover()

    assert registry.get_all() == []


def test_discover_ignora_arquivo_solto_na_raiz(tmp_path: Path) -> None:
    (tmp_path / "leia_me.txt").write_text("não é capability", encoding="utf-8")
    registry = CapabilityRegistry(tmp_path)

    registry.discover()

    assert registry.get_all() == []


def test_discover_recusa_nome_divergente_do_diretorio(tmp_path: Path) -> None:
    """Nome do diretório é a chave em disco; divergência é capability ambígua."""
    escrever_capability(tmp_path, "nas_sync", dir_name="outra_pasta")
    registry = CapabilityRegistry(tmp_path)

    with capture_logs() as logs:
        registry.discover()

    assert registry.get_all() == []
    assert [e["event"] for e in logs if e["log_level"] == "error"] == [
        "capability.nome_divergente"
    ]


def test_discover_e_idempotente(tmp_path: Path) -> None:
    escrever_capability(tmp_path, "nas_sync")
    registry = CapabilityRegistry(tmp_path)

    registry.discover()
    registry.discover()

    assert len(registry.get_all()) == 1


def test_discover_reflete_remocao_em_disco(tmp_path: Path) -> None:
    caps_dir = escrever_capability(tmp_path, "nas_sync")
    registry = CapabilityRegistry(tmp_path)
    registry.discover()
    assert len(registry.get_all()) == 1

    (caps_dir / "manifest.yaml").unlink()
    registry.discover()

    assert registry.get_all() == []


def test_id_da_capability_e_estavel_entre_descobertas(tmp_path: Path) -> None:
    """Id derivado do nome: sem isso cada boot criaria uma linha nova na tabela."""
    escrever_capability(tmp_path, "nas_sync")
    registry = CapabilityRegistry(tmp_path)

    registry.discover()
    primeiro = registry.get_all()[0].id
    registry.discover()

    assert registry.get_all()[0].id == primeiro == capability_id("nas_sync")


# --------------------------------------------------------------------------- #
# get_active()
# --------------------------------------------------------------------------- #


def test_get_active_filtra_por_status(tmp_path: Path) -> None:
    escrever_capability(tmp_path, "cap_active", status="active")
    escrever_capability(tmp_path, "cap_approved", status="approved")
    escrever_capability(tmp_path, "cap_pending", status="pending_approval")
    escrever_capability(tmp_path, "cap_disabled", status="disabled")
    registry = CapabilityRegistry(tmp_path)

    registry.discover()

    assert len(registry.get_all()) == 4
    assert [c.manifest.name for c in registry.get_active()] == ["cap_active"]


def test_get_active_vazio_quando_nada_esta_active(tmp_path: Path) -> None:
    escrever_capability(tmp_path, "cap_pending", status="pending_approval")
    registry = CapabilityRegistry(tmp_path)

    registry.discover()

    assert registry.get_active() == []
    assert registry.get_all()[0].manifest.status == CapabilityStatus.PENDING_APPROVAL


# --------------------------------------------------------------------------- #
# resolve() — acerto
# --------------------------------------------------------------------------- #


def test_resolve_acerta_capability_active(tmp_path: Path) -> None:
    escrever_capability(tmp_path, "nas_sync")
    registry = CapabilityRegistry(tmp_path)
    registry.discover()

    cap = registry.resolve("nas_sync")

    assert cap is not None
    assert cap.manifest.name == "nas_sync"
    assert cap.manifest.is_loadable is True


def test_resolve_erra_devolve_none_sem_levantar(tmp_path: Path) -> None:
    """D-2: o canal do miss é o evento, não a exceção.

    Inverso do teste que fixava o comportamento antigo (`pytest.raises`): quem
    chama recebe `None` e decide; ninguém acima precisa tratar exceção de uma
    camada que nem conhece.
    """
    registry = CapabilityRegistry(tmp_path)
    registry.discover()

    assert registry.resolve("nao_existe", context="pedido do dono") is None


def test_resolve_recusa_capability_nao_active(tmp_path: Path) -> None:
    """Aprovada mas não ativa não executa: o gate 2 não terminou."""
    escrever_capability(tmp_path, "cap_approved", status="approved")
    registry = CapabilityRegistry(tmp_path)
    registry.discover()

    assert registry.resolve("cap_approved") is None


def test_resolve_antes_de_discover_erra(tmp_path: Path) -> None:
    escrever_capability(tmp_path, "nas_sync")
    registry = CapabilityRegistry(tmp_path)

    assert registry.resolve("nas_sync") is None


# --------------------------------------------------------------------------- #
# D-2 — o miss é um fato publicado
# --------------------------------------------------------------------------- #


def test_resolve_miss_publica_gap_no_bus_sem_levantar(tmp_path: Path) -> None:
    """O miss é um fato publicado, não um erro propagado."""
    bus = InMemoryEventBus()
    registry = CapabilityRegistry(tmp_path, event_bus=bus)
    registry.discover()

    resultado = registry.resolve("sincronizar fotos com o NAS")

    assert resultado is None
    assert bus.types == [EventType.CAPABILITY_GAP_DETECTED]


def test_evento_de_gap_carrega_intencao_contexto_e_goal(tmp_path: Path) -> None:
    """A v3.0 escreve a SPEC a partir deste payload; campo faltando é SPEC cega."""
    bus = InMemoryEventBus()
    goal = Goal(title="organizar as fotos", status=GoalStatus.ACTIVE)
    registry = CapabilityRegistry(tmp_path, event_bus=bus)
    registry.discover()

    registry.resolve(
        "sincronizar fotos com o NAS",
        context="pedido do dono",
        goal_id=goal.id,
        trace_id="trace-42",
    )

    evento = bus.of_type(EventType.CAPABILITY_GAP_DETECTED)[0]
    assert evento.payload["intent"] == "sincronizar fotos com o NAS"
    assert evento.payload["context"] == "pedido do dono"
    assert evento.payload["candidatos_ativos"] == 0
    assert evento.goal_id == goal.id
    assert evento.trace_id == "trace-42"
    assert evento.source == "packages.registry"


def test_miss_sem_bus_configurado_nao_levanta(tmp_path: Path) -> None:
    """Registry sem barramento continua sendo registry: o miss vira log."""
    registry = CapabilityRegistry(tmp_path)
    registry.discover()

    with capture_logs() as logs:
        assert registry.resolve("qualquer coisa") is None

    assert "capability.gap_detected" in [e["event"] for e in logs]


async def test_miss_publica_gap_bloqueia_o_goal_e_nao_sobe_excecao(
    tmp_path: Path,
) -> None:
    """O aceite da v1.1 inteiro em um teste (`plan-execution.md` §3).

    (a) `capability.gap_detected` observável no bus, (b) goal em `blocked`,
    (c) nenhuma exceção subindo ao Chief AI — a ausência de `pytest.raises` é a
    terceira asserção, e ela é real: qualquer `raise` no caminho quebra o teste.
    """
    bus = InProcEventBus()
    store = InMemoryGoalStore()
    goal = await store.create_goal(
        Goal(title="sincronizar as fotos do celular", status=GoalStatus.ACTIVE)
    )

    recebidos: list[Event] = []

    async def gravar(event: Event) -> None:
        recebidos.append(event)

    bus.subscribe(gravar)
    bus.subscribe(GoalBlocker(store), types=[EventType.CAPABILITY_GAP_DETECTED])

    registry = CapabilityRegistry(tmp_path, event_bus=bus)
    registry.discover()

    resultado = registry.resolve(
        "sincronizar fotos com o NAS",
        context="task 3 do goal",
        goal_id=goal.id,
    )
    await registry.flush()
    await bus.drain()

    assert resultado is None
    assert [e.type for e in recebidos] == [EventType.CAPABILITY_GAP_DETECTED]
    bloqueado = await store.get_goal(goal.id)
    assert bloqueado is not None
    assert bloqueado.status == GoalStatus.BLOCKED


async def test_gap_sem_goal_nao_bloqueia_nada(tmp_path: Path) -> None:
    """Miss vindo do chat solto não tem goal pai — e não pode inventar um."""
    bus = InProcEventBus()
    store = InMemoryGoalStore()
    goal = await store.create_goal(Goal(title="outro objetivo", status=GoalStatus.ACTIVE))
    bus.subscribe(GoalBlocker(store), types=[EventType.CAPABILITY_GAP_DETECTED])
    registry = CapabilityRegistry(tmp_path, event_bus=bus)
    registry.discover()

    registry.resolve("algo que não existe")
    await registry.flush()
    await bus.drain()

    intocado = await store.get_goal(goal.id)
    assert intocado is not None
    assert intocado.status == GoalStatus.ACTIVE


# --------------------------------------------------------------------------- #
# D-1 — casamento de intenção contra o catálogo
# --------------------------------------------------------------------------- #


def test_resolve_casa_intencao_contra_o_catalogo(tmp_path: Path) -> None:
    escrever_capability(
        tmp_path,
        "nas_sync",
        description="Sincroniza arquivos locais com o NAS",
        tools=[
            {
                "name": "sync_files",
                "description": "Copia arquivos para o NAS",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
    )
    registry = CapabilityRegistry(tmp_path)
    registry.discover()

    cap = registry.resolve("sync_files")

    assert cap is not None
    assert cap.manifest.name == "nas_sync"


def test_resolve_casa_frase_livre_contra_nome_e_descricao(tmp_path: Path) -> None:
    """Quem chama não sabe o nome da capability — é esse o ponto do D-1."""
    escrever_capability(
        tmp_path,
        "nas_sync",
        description="Sincroniza arquivos locais com o NAS",
        tools=[
            {
                "name": "sync_files",
                "description": "Copia arquivos para o NAS",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
    )
    registry = CapabilityRegistry(tmp_path)
    registry.discover()

    cap = registry.resolve("sincronizar arquivos com o NAS")

    assert cap is not None
    assert cap.manifest.name == "nas_sync"


def test_resolve_casa_trigger_intent_declarado_no_manifest(tmp_path: Path) -> None:
    """`trigger_intent` é o campo que `plan.md` §6 cita e o contrato ainda não tem."""
    escrever_capability(
        tmp_path,
        "nas_sync",
        description="Sincroniza arquivos locais com o NAS",
        extra={"trigger_intent": ["fazer backup das fotos", "guardar fotos no disco"]},
    )
    registry = CapabilityRegistry(tmp_path)
    registry.discover()

    cap = registry.resolve("fazer backup das fotos")

    assert cap is not None
    assert cap.manifest.name == "nas_sync"


def test_resolve_nao_improvisa_com_capability_de_outro_assunto(tmp_path: Path) -> None:
    """Errar para o lado do miss é decisão de projeto: acerto errado escreve em disco."""
    bus = InMemoryEventBus()
    escrever_capability(
        tmp_path,
        "nas_sync",
        description="Sincroniza arquivos locais com o NAS",
        tools=[
            {
                "name": "sync_files",
                "description": "Copia arquivos para o NAS",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
    )
    registry = CapabilityRegistry(tmp_path, event_bus=bus)
    registry.discover()

    assert registry.resolve("enviar e-mail para o cliente") is None
    assert bus.types == [EventType.CAPABILITY_GAP_DETECTED]


def test_resolve_ignora_capability_nao_active_no_casamento(tmp_path: Path) -> None:
    escrever_capability(
        tmp_path,
        "nas_sync",
        status="pending_approval",
        description="Sincroniza arquivos locais com o NAS",
        tools=[
            {
                "name": "sync_files",
                "description": "Copia arquivos para o NAS",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
    )
    registry = CapabilityRegistry(tmp_path)
    registry.discover()

    assert registry.resolve("sync_files") is None


def test_resolve_e_deterministico_no_empate(tmp_path: Path) -> None:
    """Duas capabilities disputando o mesmo pedido não podem alternar por sorte."""
    for nome in ("alfa_sync", "beta_sync"):
        escrever_capability(
            tmp_path, nome, description="Sincroniza arquivos locais com o NAS"
        )
    registry = CapabilityRegistry(tmp_path)
    registry.discover()

    escolhas = {registry.resolve("sincronizar arquivos locais")for _ in range(5)}

    assert len(escolhas) == 1


# --------------------------------------------------------------------------- #
# D-3 — código em disco tem de ser o aprovado
# --------------------------------------------------------------------------- #


def test_discover_recusa_capability_alterada_apos_aprovacao(tmp_path: Path) -> None:
    caps_dir = escrever_capability(
        tmp_path, "nas_sync", extra={"approved_commit": "0" * 40}
    )
    (caps_dir / "server.py").write_text(
        "# código alterado após o gate\n", encoding="utf-8"
    )
    registry = CapabilityRegistry(tmp_path)

    registry.discover()

    assert registry.get_all() == []


def test_um_byte_alterado_faz_discover_recusar_a_capability(tmp_path: Path) -> None:
    """A porta da automodificação silenciosa (`plan.md` §6), fechada e testada."""
    caps_dir = escrever_capability(tmp_path, "nas_sync")
    codigo = caps_dir / "server.py"
    codigo.write_text("x = 1\n", encoding="utf-8")
    escrever_capability(
        tmp_path,
        "nas_sync",
        extra={"approved_commit": compute_capability_digest(caps_dir)},
    )
    registry = CapabilityRegistry(tmp_path)

    registry.discover()
    assert [c.manifest.name for c in registry.get_all()] == ["nas_sync"]

    codigo.write_text("x = 2\n", encoding="utf-8")  # um byte
    with capture_logs() as logs:
        registry.discover()

    assert registry.get_all() == []
    recusa = [e for e in logs if e["event"] == "capability.integridade_divergente"]
    assert len(recusa) == 1
    assert recusa[0]["log_level"] == "error"
    assert recusa[0]["capability"] == "nas_sync"


def test_digest_ignora_o_manifest_e_o_pycache(tmp_path: Path) -> None:
    """O manifest guarda o próprio digest; incluí-lo tornaria o valor impossível.

    `__pycache__` fica de fora porque existe ou não conforme a máquina, e o
    mesmo código daria digest diferente em casa e no trabalho.
    """
    caps_dir = escrever_capability(tmp_path, "nas_sync")
    (caps_dir / "server.py").write_text("x = 1\n", encoding="utf-8")
    original = compute_capability_digest(caps_dir)

    escrever_capability(tmp_path, "nas_sync", description="outra descrição")
    (caps_dir / "__pycache__").mkdir()
    (caps_dir / "__pycache__" / "server.pyc").write_bytes(b"\x00\x01")

    assert compute_capability_digest(caps_dir) == original


def test_capability_sem_approved_commit_carrega_com_aviso(tmp_path: Path) -> None:
    """Estado legítimo enquanto o Gate 2 (v3.2) não existe — mas nunca calado."""
    escrever_capability(tmp_path, "nas_sync")
    registry = CapabilityRegistry(tmp_path)

    with capture_logs() as logs:
        registry.discover()

    assert len(registry.get_all()) == 1
    avisos = [e for e in logs if e["event"] == "capability.sem_approved_commit"]
    assert len(avisos) == 1
    assert avisos[0]["log_level"] == "warning"


# --------------------------------------------------------------------------- #
# D-4 — manifest inválido é visível, não invisível
# --------------------------------------------------------------------------- #


def test_manifest_invalido_fica_visivel_como_disabled(tmp_path: Path) -> None:
    """Capability quebrada tem de ser visível: invisível ninguém conserta."""
    escrever_capability(
        tmp_path, "cap_quebrada", conteudo_bruto="name: cap_quebrada\nversion: [\n"
    )
    registry = CapabilityRegistry(tmp_path)

    registry.discover()

    quebradas = [c for c in registry.get_all() if c.manifest.name == "cap_quebrada"]
    assert len(quebradas) == 1
    assert quebradas[0].manifest.status == CapabilityStatus.DISABLED


def test_manifest_invalido_loga_em_error_e_nao_derruba_as_demais(
    tmp_path: Path,
) -> None:
    """Inverso do teste que fixava o `except ManifestLoadError: pass` (D-4)."""
    escrever_capability(
        tmp_path, "cap_quebrada", conteudo_bruto="name: cap_quebrada\nversion: [\n"
    )
    escrever_capability(tmp_path, "cap_ok")
    registry = CapabilityRegistry(tmp_path)

    with capture_logs() as logs:
        registry.discover()

    assert [c.manifest.name for c in registry.get_all()] == ["cap_ok", "cap_quebrada"]
    erros = [e for e in logs if e["event"] == "capability.manifest_invalido"]
    assert len(erros) == 1
    assert erros[0]["log_level"] == "error"
    assert erros[0]["capability"] == "cap_quebrada"


def test_capability_quebrada_nunca_entra_no_resolve(tmp_path: Path) -> None:
    """Visível para conserto, invisível para execução: `disabled` não é `active`."""
    escrever_capability(
        tmp_path, "cap_quebrada", conteudo_bruto="name: cap_quebrada\nversion: [\n"
    )
    registry = CapabilityRegistry(tmp_path)
    registry.discover()

    assert registry.get_active() == []
    assert registry.resolve("cap_quebrada") is None


# --------------------------------------------------------------------------- #
# Tabela `capabilities` — o estado que sobrevive a restart
# --------------------------------------------------------------------------- #


def test_fake_store_implementa_a_porta() -> None:
    assert isinstance(FakeCapabilityStore(), CapabilityStore)


def test_adaptador_postgres_implementa_a_porta() -> None:
    """O dublê acima só vale se o adaptador de verdade obedecer o mesmo contrato."""
    from apps.api.db.repository import PgCapabilityStore

    assert isinstance(PgCapabilityStore(cast(Any, None)), CapabilityStore)


async def test_persist_grava_o_catalogo_descoberto(tmp_path: Path) -> None:
    escrever_capability(
        tmp_path,
        "nas_sync",
        extra={
            "dependencies": ["httpx"],
            "permissions": {"network": ["nas.local"], "filesystem": ["/data"]},
        },
    )
    store = FakeCapabilityStore()
    registry = CapabilityRegistry(tmp_path)
    registry.discover()

    gravados = await registry.persist(store)

    assert [r.name for r in gravados] == ["nas_sync"]
    linha = store.rows["nas_sync"]
    assert linha.id == capability_id("nas_sync")
    assert linha.status == CapabilityStatus.ACTIVE
    # `mcp_stdio` é o nome legado que o `escrever_capability` ainda grava no
    # manifest; o contrato normaliza para o canônico `mcp` na carga. O banco
    # guarda o canônico de propósito: persistir o legado obrigaria todo leitor da
    # tabela a repetir a tradução, que é exatamente o que a migração apagou.
    assert linha.runtime == "mcp"
    assert linha.dependencies == ["httpx"]
    assert linha.permissions.network == ["nas.local"]
    assert linha.health == CapabilityHealth.UNKNOWN


async def test_estado_operacional_sobrevive_ao_restart(tmp_path: Path) -> None:
    """O motivo de a tabela existir: dicionário em memória morre no `restart`."""
    escrever_capability(tmp_path, "nas_sync")
    store = FakeCapabilityStore()
    usado_em = utcnow() - timedelta(hours=3)

    antes = CapabilityRegistry(tmp_path)
    antes.discover()
    antes.mark_used("nas_sync", usado_em)
    antes.set_health("nas_sync", CapabilityHealth.DEGRADED)
    await antes.persist(store)

    depois = CapabilityRegistry(tmp_path)  # processo novo, memória zerada
    depois.discover()
    assert depois.health_of("nas_sync") == CapabilityHealth.UNKNOWN

    recuperados = await depois.hydrate(store)

    assert recuperados == 1
    assert depois.health_of("nas_sync") == CapabilityHealth.DEGRADED
    assert depois.get_all()[0].last_used_at == usado_em


async def test_persist_e_idempotente_e_casa_por_nome(tmp_path: Path) -> None:
    escrever_capability(tmp_path, "nas_sync")
    store = FakeCapabilityStore()
    registry = CapabilityRegistry(tmp_path)
    registry.discover()

    await registry.persist(store)
    await registry.persist(store)

    assert store.upserts == 2
    assert list(store.rows) == ["nas_sync"]


async def test_capability_quebrada_tambem_e_persistida_como_disabled(
    tmp_path: Path,
) -> None:
    """Se some da tabela, o dashboard de saúde da v1.5 não tem o que mostrar."""
    escrever_capability(
        tmp_path, "cap_quebrada", conteudo_bruto="name: cap_quebrada\nversion: [\n"
    )
    store = FakeCapabilityStore()
    registry = CapabilityRegistry(tmp_path)
    registry.discover()

    await registry.persist(store)

    assert store.rows["cap_quebrada"].status == CapabilityStatus.DISABLED


@pytest.mark.parametrize("health", list(CapabilityHealth))
def test_health_e_estado_medido_e_nao_status(health: CapabilityHealth) -> None:
    """`status` é decisão humana, `health` é consequência medida — não se misturam."""
    assert health.value not in {s.value for s in CapabilityStatus}
