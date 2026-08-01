"""Capability Registry — o catálogo do que o sistema sabe fazer.

`plan.md` §6: a pergunta deixou de ser "tenho a ferramenta X?" e passou a ser
"tenho a capacidade de fazer isto? se não tenho, posso criá-la?". Este módulo
responde a primeira metade; a segunda começa no evento que o miss publica.

Quatro defeitos da v1.0 morrem aqui (`plan-execution.md` §1):

- **D-1** — `resolve()` casava nome exato de capability, o que só funcionava se
  quem chamava já soubesse o nome. Agora casa intenção contra o catálogo
  (`matching.py`), determinístico e sem LLM.
- **D-2** — o miss levantava exceção. Agora devolve `None`, publica
  `capability.gap_detected` e o goal pai vai para `blocked` pelo consumidor
  (`gap.py`). Exceção deixou de ser o canal.
- **D-3** — `discover()` não conferia o código em disco contra o
  `approved_commit`. Agora confere e **recusa** na divergência (`integrity.py`).
- **D-4** — manifest inválido caía em `except ManifestLoadError: pass` e sumia.
  Agora vira log em `error` e uma entrada `disabled` no catálogo: capability
  quebrada que ninguém enxerga é capability que ninguém conserta.

A assimetria entre D-3 e D-4 é proposital. Manifest inválido é defeito de
configuração: fica **visível** como `disabled`, para ser corrigido. Código
divergente do aprovado é suspeita de automodificação: **não entra** no catálogo
de jeito nenhum, porque registrar já seria oferecê-lo a quem lista.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import structlog

from packages.registry.exceptions import ManifestLoadError
from packages.registry.gap import FONTE, gap_event
from packages.registry.integrity import MANIFEST_FILENAME, compute_capability_digest
from packages.registry.manifest import load_manifest
from packages.registry.matching import CatalogIndex, build_index, match_intent
from packages.registry.ports import CapabilityStore
from packages.registry.records import CapabilityHealth, CapabilityRecord
from packages.shared.contracts import (
    Capability,
    CapabilityManifest,
    CapabilityStatus,
    Event,
    utcnow,
)
from packages.shared.ports import EventBus

logger = structlog.get_logger(__name__)


def capability_id(name: str) -> UUID:
    """Id estável derivado do nome — a chave da capability em disco.

    `uuid4()` a cada `discover()` faria a mesma capability virar uma linha nova
    da tabela `capabilities` a cada boot, e `last_used_at`/`health` nunca
    sobreviveriam a um restart, que é justamente o que a tabela existe para
    resolver.
    """
    return uuid5(NAMESPACE_URL, f"jarvis://capability/{name}")


class CapabilityRegistry:
    """Catálogo em memória, com estado durável atrás da porta `CapabilityStore`."""

    def __init__(
        self,
        base_dir: str | Path,
        *,
        event_bus: EventBus | None = None,
        source: str = FONTE,
    ) -> None:
        self._base_dir = Path(base_dir)
        self._bus = event_bus
        self._source = source
        self._capabilities: dict[str, Capability] = {}
        self._index: dict[str, CatalogIndex] = {}
        #: Estado operacional: sobrevive a `discover()` e vem/vai para a tabela.
        self._health: dict[str, CapabilityHealth] = {}
        self._last_used: dict[str, datetime] = {}
        #: Publicações em voo quando há loop rodando (ver `_publicar`).
        self._pendentes: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------ #
    # discover
    # ------------------------------------------------------------------ #

    def discover(self) -> None:
        """Varre `base_dir` e recarrega o catálogo do zero.

        Idempotente: o catálogo passa a ser exatamente o que está em disco agora,
        e capability removida do disco desaparece da listagem.
        """
        self._capabilities.clear()
        self._index.clear()

        if not self._base_dir.is_dir():
            return

        # Ordem alfabética: `iterdir()` devolve a ordem do sistema de arquivos, e
        # catálogo que muda de ordem entre máquinas torna desempate não-reprodutível.
        for entry in sorted(self._base_dir.iterdir(), key=lambda p: p.name):
            if not entry.is_dir():
                continue
            manifest_path = entry / MANIFEST_FILENAME
            if not manifest_path.is_file():
                continue

            try:
                manifest = load_manifest(manifest_path)
            except ManifestLoadError as exc:
                # D-4: o `pass` daqui era o defeito. Manifest quebrado é fato
                # observável — em log e no catálogo.
                logger.error(
                    "capability.manifest_invalido",
                    capability=entry.name,
                    path=str(manifest_path),
                    erro=str(exc),
                )
                self._registrar(self._placeholder(entry.name, str(exc)))
                continue

            if manifest.name != entry.name:
                # O nome do diretório é a chave em disco; divergência é
                # capability ambígua, e ambiguidade em catálogo é bug de gente.
                logger.error(
                    "capability.nome_divergente",
                    diretorio=entry.name,
                    manifest=manifest.name,
                    path=str(manifest_path),
                )
                continue

            if not self._integridade_ok(entry, manifest):
                continue

            self._registrar(manifest)

    def _integridade_ok(self, directory: Path, manifest: CapabilityManifest) -> bool:
        """D-3: o código em disco tem de ser o que passou pelo gate."""
        aprovado = manifest.approved_commit

        if aprovado is None:
            if manifest.is_loadable:
                # Estado legítimo enquanto o Gate 2 (v3.2) não existe, mas é
                # exatamente o buraco que ele fecha: sem valor gravado não há o
                # que conferir. Aviso, não recusa — recusar aqui esvaziaria o
                # catálogo inteiro de hoje.
                logger.warning(
                    "capability.sem_approved_commit",
                    capability=manifest.name,
                    path=str(directory),
                )
            return True

        digest = compute_capability_digest(directory)
        if digest == aprovado.strip().lower():
            return True

        logger.error(
            "capability.integridade_divergente",
            capability=manifest.name,
            path=str(directory),
            approved_commit=aprovado,
            digest=digest,
            acao="recusada",
        )
        return False

    @staticmethod
    def _placeholder(name: str, erro: str) -> CapabilityManifest:
        """Entrada mínima e `disabled` para uma capability que não carregou.

        O nome do diretório é a única identidade confiável quando o manifest não
        parseia — e é o suficiente para o dono achar a pasta e consertar.
        """
        return CapabilityManifest(
            name=name,
            version="0.0.0",
            description=f"manifest inválido: {erro}",
            status=CapabilityStatus.DISABLED,
            entrypoint="",
        )

    def _registrar(self, manifest: CapabilityManifest) -> None:
        self._capabilities[manifest.name] = Capability(
            id=capability_id(manifest.name),
            manifest=manifest,
            last_used_at=self._last_used.get(manifest.name),
        )
        self._index[manifest.name] = build_index(manifest)

    # ------------------------------------------------------------------ #
    # consulta
    # ------------------------------------------------------------------ #

    @property
    def base_dir(self) -> Path:
        """Raiz do catálogo em disco.

        Público desde a v1.2: o kernel precisa do diretório da capability para
        rodá-la (é o `cwd` do subprocesso e a raiz de escrita implícita das
        permissões). A alternativa era o dono passar o mesmo caminho duas vezes,
        para o registry e para o kernel, e um dia passar dois caminhos
        diferentes.
        """
        return self._base_dir

    def directory_of(self, name: str) -> Path:
        """Diretório em disco de uma capability. Não confere existência."""
        return self._base_dir / name

    def get_all(self) -> list[Capability]:
        """Todas as capabilities carregadas, inclusive as `disabled`."""
        return list(self._capabilities.values())

    def get_active(self) -> list[Capability]:
        """Só as que podem executar (`status == active`)."""
        return [c for c in self._capabilities.values() if c.manifest.is_loadable]

    def health_of(self, name: str) -> CapabilityHealth:
        return self._health.get(name, CapabilityHealth.UNKNOWN)

    def set_health(self, name: str, health: CapabilityHealth) -> None:
        self._health[name] = health

    def mark_used(self, name: str, when: datetime | None = None) -> None:
        """Registra uso. `persist()` leva o valor para a tabela."""
        momento = when or utcnow()
        self._last_used[name] = momento
        cap = self._capabilities.get(name)
        if cap is not None:
            cap.last_used_at = momento

    # ------------------------------------------------------------------ #
    # resolve
    # ------------------------------------------------------------------ #

    def resolve(
        self,
        intent: str,
        context: str = "",
        *,
        goal_id: UUID | None = None,
        task_id: UUID | None = None,
        trace_id: str | None = None,
    ) -> Capability | None:
        """Casa uma intenção contra o catálogo `active`. `None` é o miss.

        Miss **não levanta** (D-2): publica `capability.gap_detected` e devolve
        `None`. Quem chama decide o que fazer com o `None`; o goal pai vai para
        `blocked` pelo consumidor do evento, sem o Chief AI precisar tratar
        exceção de uma camada que ele nem conhece.
        """
        ativos = [
            self._index[nome]
            for nome, cap in self._capabilities.items()
            if cap.manifest.is_loadable and nome in self._index
        ]
        escolhida = match_intent(intent, ativos)

        if escolhida is None:
            self._anunciar_gap(
                intent,
                context=context,
                goal_id=goal_id,
                task_id=task_id,
                trace_id=trace_id,
                candidatos=len(ativos),
            )
            return None

        logger.info(
            "capability.resolvida",
            intent=intent,
            capability=escolhida,
            candidatos=len(ativos),
        )
        return self._capabilities[escolhida]

    def _anunciar_gap(
        self,
        intent: str,
        *,
        context: str,
        goal_id: UUID | None,
        task_id: UUID | None,
        trace_id: str | None,
        candidatos: int,
    ) -> None:
        event = gap_event(
            intent,
            context=context,
            goal_id=goal_id,
            task_id=task_id,
            trace_id=trace_id,
            candidatos=candidatos,
            source=self._source,
        )
        # Log independe de bus: miss sem barramento configurado ainda é o fato
        # mais importante que o registry produz, e ele não pode sumir.
        logger.warning(
            "capability.gap_detected",
            intent=intent,
            context=context,
            goal_id=str(goal_id) if goal_id else None,
            candidatos=candidatos,
            trace_id=event.trace_id,
            bus=self._bus is not None,
        )
        if self._bus is not None:
            self._publicar(self._bus, event)

    # ------------------------------------------------------------------ #
    # bus
    # ------------------------------------------------------------------ #

    def _publicar(self, bus: EventBus, event: Event) -> None:
        """Publica de código síncrono numa porta assíncrona.

        `resolve()` é síncrono porque é chamado no meio de uma decisão, e
        `EventBus.publish` é assíncrono porque o transporte da v2.2 é rede. Sem
        loop rodando, a corrotina roda até o fim aqui mesmo — é o caso do
        registry usado fora do orchestrator. Com loop, vira task e `flush()`
        espera: agendar sem guardar a referência é como a asyncio perde tarefa
        por coleta de lixo.
        """
        coro = bus.publish(event)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(coro)
            return
        task = loop.create_task(coro)
        self._pendentes.add(task)
        task.add_done_callback(self._pendentes.discard)

    async def flush(self) -> None:
        """Espera as publicações em voo. Determinismo para teste e desligamento."""
        while self._pendentes:
            await asyncio.gather(*tuple(self._pendentes), return_exceptions=True)

    # ------------------------------------------------------------------ #
    # persistência (tabela `capabilities`)
    # ------------------------------------------------------------------ #

    def records(self) -> list[CapabilityRecord]:
        """O catálogo de agora em forma de linha da tabela `capabilities`."""
        return [
            CapabilityRecord(
                id=cap.id,
                name=cap.manifest.name,
                version=cap.manifest.version,
                runtime=cap.manifest.runtime,
                status=cap.manifest.status,
                permissions=cap.manifest.permissions,
                dependencies=list(cap.manifest.dependencies),
                approved_commit=cap.manifest.approved_commit,
                health=self.health_of(cap.manifest.name),
                last_used_at=cap.last_used_at,
            )
            for cap in self._capabilities.values()
        ]

    async def persist(self, store: CapabilityStore) -> list[CapabilityRecord]:
        """Grava o catálogo descoberto. Devolve o que foi gravado."""
        gravados = [await store.upsert(record) for record in self.records()]
        logger.info("capability.catalogo_persistido", total=len(gravados))
        return gravados

    async def hydrate(self, store: CapabilityStore) -> int:
        """Recupera da tabela o estado que o disco não tem.

        `status`, `permissions` e `approved_commit` continuam vindo do manifest —
        disco é a verdade do que a capability *é*. Da tabela vem só o que é
        consequência de execução (`health`, `last_used_at`), que é o que morria
        a cada restart.
        """
        recuperados = 0
        for record in await store.list_all():
            self._health[record.name] = record.health
            if record.last_used_at is not None:
                self._last_used[record.name] = record.last_used_at
            cap = self._capabilities.get(record.name)
            if cap is not None:
                cap.last_used_at = record.last_used_at
                recuperados += 1
        logger.info("capability.estado_recuperado", capabilities=recuperados)
        return recuperados


__all__ = ["CapabilityRegistry", "capability_id"]
