"""Nível `experience` — padrões extraídos de execução.

`plan.md` §10: "é o nível que diferencia o sistema de um chat com RAG. Guarda
coisas como 'capability X falha quando o NAS está em standby, acordar antes'".

A regra que dá sentido ao nível: **uma falha é acidente, a repetida é padrão**.
Registrar toda falha individualmente encheria o contexto de planejamento com
ruído de rede e daria ao modelo motivo para evitar uma capability que funciona.
Por isso duas coisas acontecem juntas:

1. falhas são agrupadas por `error_signature()` — números e hashes viram
   marcador, então "timeout após 30s" e "timeout após 45s" caem no mesmo
   registro em vez de virarem dois registros de uma ocorrência cada;
2. só registro com `occurrences >= pattern_threshold` entra em `patterns()`, que
   é o que alimenta o prompt do próximo planejamento.

Sucesso também é registrado, e por um motivo prático: sem ele o contexto só teria
más notícias, e "capability X falhou 3x" sem "capability X funcionou 40x" é uma
meia-verdade que faz o planejador abandonar o que funciona.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from uuid import UUID, uuid4

import structlog

from packages.memory.models import (
    ExperienceKind,
    ExperienceRecord,
    MemoryLevel,
    MemoryUpdate,
    error_signature,
    experience_id,
)
from packages.memory.ports import ExperienceStore
from packages.shared.contracts import Event, EventType, utcnow
from packages.shared.ports import EventBus

logger = structlog.get_logger(__name__)

#: Ocorrências a partir das quais uma falha vira padrão. Dois, não três: o custo
#: de avisar cedo demais é uma linha a mais no prompt; o de avisar tarde é o
#: sistema repetir a mesma falha uma terceira vez sabendo dela.
DEFAULT_PATTERN_THRESHOLD = 2
MAX_EVIDENCE = 5
MAX_GOAL_IDS = 5
SUCCESS_SIGNATURE = "ok"


class ExperienceMemory:
    """Acumula e promove padrões de execução."""

    def __init__(
        self,
        store: ExperienceStore,
        *,
        event_bus: EventBus | None = None,
        pattern_threshold: int = DEFAULT_PATTERN_THRESHOLD,
        max_evidence: int = MAX_EVIDENCE,
    ) -> None:
        self._store = store
        self._bus = event_bus
        self._threshold = max(1, pattern_threshold)
        self._max_evidence = max_evidence

    @property
    def pattern_threshold(self) -> int:
        return self._threshold

    # -- escrita ---------------------------------------------------------- #

    async def record_capability_failure(
        self,
        subject: str,
        error: str,
        *,
        goal_id: UUID | None = None,
    ) -> ExperienceRecord:
        """Registra (ou incrementa) a falha de uma capability/tool."""
        assinatura = error_signature(error)
        return await self._acumular(
            kind=ExperienceKind.CAPABILITY_FAILURE,
            subject=subject,
            signature=assinatura,
            lesson_factory=lambda n: (
                f"a capability '{subject}' falhou {n}x com: {assinatura}"
            ),
            evidence=error.strip(),
            goal_id=goal_id,
        )

    async def record_capability_success(
        self, subject: str, *, goal_id: UUID | None = None
    ) -> ExperienceRecord:
        """Registra que a capability funcionou. Contrapeso das falhas."""
        return await self._acumular(
            kind=ExperienceKind.CAPABILITY_SUCCESS,
            subject=subject,
            signature=SUCCESS_SIGNATURE,
            lesson_factory=lambda n: f"a capability '{subject}' concluiu {n}x sem erro",
            evidence="",
            goal_id=goal_id,
        )

    async def record_owner_preference(
        self, subject: str, lesson: str
    ) -> ExperienceRecord:
        """Como o dono costuma decidir — o terceiro conteúdo do nível (`plan.md` §10)."""
        return await self._acumular(
            kind=ExperienceKind.OWNER_PREFERENCE,
            subject=subject,
            signature=error_signature(lesson),
            lesson_factory=lambda _n: lesson,
            evidence="",
            goal_id=None,
        )

    # -- leitura ---------------------------------------------------------- #

    async def patterns(
        self,
        *,
        limit: int = 5,
        kinds: Sequence[ExperienceKind] | None = None,
    ) -> list[ExperienceRecord]:
        """Registros que já passaram do limiar, do mais recorrente ao menos.

        É a **única** porta de saída para o planejamento: registro com uma
        ocorrência só não entra, porque acidente não é padrão.
        """
        aceitos = kinds or (
            ExperienceKind.CAPABILITY_FAILURE,
            ExperienceKind.OWNER_PREFERENCE,
        )
        registros = [
            r
            for r in await self._store.all()
            if r.kind in aceitos and r.occurrences >= self._threshold
        ]
        # Mais recorrente primeiro; empate desempatado pelo mais recente e, se
        # ainda empatar, pelo id — ordem instável aqui viraria prompt instável.
        registros.sort(key=lambda r: (-r.occurrences, -r.last_seen_at.timestamp(), r.id))
        return registros[: max(0, limit)]

    async def all(self) -> list[ExperienceRecord]:
        return await self._store.all()

    async def get(self, record_id: str) -> ExperienceRecord | None:
        return await self._store.get(record_id)

    # -- interno ---------------------------------------------------------- #

    async def _acumular(
        self,
        *,
        kind: ExperienceKind,
        subject: str,
        signature: str,
        lesson_factory: Callable[[int], str],
        evidence: str,
        goal_id: UUID | None,
    ) -> ExperienceRecord:
        rid = experience_id(kind, subject, signature)
        registro = await self._store.get(rid)
        agora = utcnow()

        if registro is None:
            registro = ExperienceRecord(
                id=rid,
                kind=kind,
                subject=subject,
                signature=signature,
                lesson=lesson_factory(1),
                occurrences=1,
                first_seen_at=agora,
                last_seen_at=agora,
            )
        else:
            registro.occurrences += 1
            registro.last_seen_at = agora
            registro.lesson = lesson_factory(registro.occurrences)

        if evidence:
            registro.evidence = [*registro.evidence, evidence][-self._max_evidence :]
        if goal_id is not None:
            gid = str(goal_id)
            if gid not in registro.goal_ids:
                registro.goal_ids = [*registro.goal_ids, gid][-MAX_GOAL_IDS:]

        await self._store.put(registro)
        virou_padrao = registro.occurrences == self._threshold
        logger.info(
            "memory.experience.registrado",
            record_id=registro.id,
            occurrences=registro.occurrences,
            virou_padrao=virou_padrao,
        )
        await self._publicar(registro, virou_padrao=virou_padrao)
        return registro

    async def _publicar(
        self, registro: ExperienceRecord, *, virou_padrao: bool
    ) -> None:
        if self._bus is None:
            return
        update = MemoryUpdate(
            level=MemoryLevel.EXPERIENCE,
            subject=registro.id,
            detail="padrão promovido" if virou_padrao else registro.lesson,
            count=registro.occurrences,
        )
        await self._bus.publish(
            Event(
                type=EventType.MEMORY_UPDATED,
                source="packages.memory.experience",
                payload=update.model_dump(mode="json"),
                trace_id=uuid4().hex,
            )
        )


def render_experience_context(
    records: Sequence[ExperienceRecord], *, max_chars: int = 900
) -> str:
    """Formata os padrões para o prompt de planejamento.

    O bloco diz o que fazer com a informação, não só qual é: "evite repetir" é o
    que transforma um registro em decisão. Sem a instrução, o modelo lê a lista
    como contexto decorativo.
    """
    if not records:
        return ""
    linhas = ["Memória `experience` — padrões observados em execuções anteriores:"]
    linhas.extend(f"- {r.lesson}" for r in records)
    linhas.append(
        "Leve isto em conta ao planejar: não repita o que já falhou de forma "
        "recorrente sem mudar a abordagem."
    )
    return "\n".join(linhas)[:max_chars]


__all__ = [
    "DEFAULT_PATTERN_THRESHOLD",
    "ExperienceMemory",
    "render_experience_context",
]
