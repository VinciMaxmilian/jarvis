"""Fachada dos cinco níveis: um objeto para o GoalManager depender de um só.

Por que existe. Os níveis são independentes de propósito — `knowledge` não sabe
o que é uma task, `working` não sabe o que é um documento. Mas quem os usa é
sempre o mesmo laço de execução, e injetar cinco dependências no `GoalManager`
para ligar a memória tornaria a mudança em `packages/agents/` tudo menos
cirúrgica. A fachada reduz a integração a **um parâmetro opcional e quatro
ganchos**, e `memory=None` deixa o comportamento de hoje intacto byte a byte.

Regra desta camada: **memória nunca derruba a task**. Um gancho que levanta
transformaria uma indisponibilidade de disco em falha de execução, e o sistema
passaria a errar mais por lembrar do que por esquecer. Falha aqui vira log em
`error` e o laço segue.
"""

from __future__ import annotations

import structlog

from packages.memory.experience import ExperienceMemory, render_experience_context
from packages.memory.knowledge import KnowledgeBase, render_knowledge_context
from packages.memory.long_term import LongTermMemory
from packages.memory.models import AttemptOutcome
from packages.memory.short_term import ShortTermMemory
from packages.memory.working import WorkingMemory, render_working_context
from packages.shared.contracts import Goal, Task

logger = structlog.get_logger(__name__)


class MemorySystem:
    """Os cinco níveis de `plan.md` §10 atrás de uma superfície só."""

    def __init__(
        self,
        *,
        working: WorkingMemory | None = None,
        knowledge: KnowledgeBase | None = None,
        experience: ExperienceMemory | None = None,
        long_term: LongTermMemory | None = None,
        short_term: ShortTermMemory | None = None,
        knowledge_in_planning: bool = True,
        planning_pattern_limit: int = 5,
        planning_knowledge_limit: int = 3,
    ) -> None:
        self.working = working
        self.knowledge = knowledge
        self.experience = experience
        self.long_term = long_term
        self.short_term = short_term
        self._knowledge_in_planning = knowledge_in_planning
        self._pattern_limit = planning_pattern_limit
        self._knowledge_limit = planning_knowledge_limit

    # -- ganchos do laço de execução -------------------------------------- #

    async def on_task_started(self, task: Task) -> str:
        """Abre a tentativa no working memory e devolve o que já foi tentado.

        A ordem importa: o estado é lido **antes** de a tentativa nova ser
        registrada, senão o contexto devolvido incluiria a tentativa em curso e
        diria ao modelo que ele já tentou o que está começando a fazer agora.
        """
        if self.working is None:
            return ""
        try:
            anterior = await self.working.restore(task.id)
            await self.working.begin_attempt(task)
        except Exception as exc:  # memória nunca derruba a task
            logger.error("memory.hook_falhou", hook="on_task_started", error=str(exc))
            return ""
        if anterior is None:
            return ""
        return render_working_context(anterior)

    async def on_task_succeeded(self, task: Task) -> None:
        """Fecha a tentativa, registra o sucesso e descarta o estado da task."""
        alvo = _alvo(task)
        try:
            if self.working is not None:
                await self.working.finish_attempt(
                    task, outcome=AttemptOutcome.SUCCEEDED
                )
                # Vida útil do nível `working` é a da task (`plan.md` §10).
                await self.working.clear(task.id)
            if self.experience is not None and alvo is not None:
                await self.experience.record_capability_success(
                    alvo, goal_id=task.goal_id
                )
        except Exception as exc:
            logger.error("memory.hook_falhou", hook="on_task_succeeded", error=str(exc))

    async def on_task_failed(self, task: Task, error: str) -> None:
        """Fecha a tentativa com o erro e acumula o padrão em `experience`.

        O estado do working memory **não** é descartado aqui: a task pode ter
        retry, e é justamente o que já foi tentado que a próxima tentativa
        precisa ler.
        """
        alvo = _alvo(task)
        try:
            if self.working is not None:
                await self.working.finish_attempt(
                    task, outcome=AttemptOutcome.FAILED, error=error
                )
            if self.experience is not None and alvo is not None:
                await self.experience.record_capability_failure(
                    alvo, error, goal_id=task.goal_id
                )
        except Exception as exc:
            logger.error("memory.hook_falhou", hook="on_task_failed", error=str(exc))

    async def planning_context(self, goal: Goal) -> str:
        """Bloco de contexto para o planejamento (`GoalManager.decompose_goal`).

        É aqui que uma falha repetida de capability deixa de ser histórico e vira
        entrada do próximo plano — o aceite da v1.3.
        """
        blocos: list[str] = []
        try:
            if self.experience is not None:
                padroes = await self.experience.patterns(limit=self._pattern_limit)
                bloco = render_experience_context(padroes)
                if bloco:
                    blocos.append(bloco)
        except Exception as exc:
            logger.error("memory.hook_falhou", hook="planning_experience", error=str(exc))

        try:
            if self.knowledge is not None and self._knowledge_in_planning:
                consulta = f"{goal.title}\n{goal.description}".strip()
                achados = await self.knowledge.search(
                    consulta, limit=self._knowledge_limit
                )
                bloco = render_knowledge_context(achados)
                if bloco:
                    blocos.append(bloco)
        except Exception as exc:
            logger.error("memory.hook_falhou", hook="planning_knowledge", error=str(exc))

        return "\n\n".join(blocos)


def _alvo(task: Task) -> str | None:
    """Quem executou a task: a capability, ou a tool quando não há capability.

    `None` quando a task rodou direto no LLM — nesse caso não há capability sobre
    a qual acumular padrão, e inventar um nome ("llm") criaria um registro que
    ninguém consegue agir sobre.
    """
    return task.capability or task.tool


__all__ = ["MemorySystem"]
