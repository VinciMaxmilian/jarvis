"""Goal Manager — orquestra goals → tasks com checkpoint.

Responsabilidades:
- Decompor goal em tasks (via ChiefAI)
- Executar tasks em ordem de dependência
- Checkpoint: cada task DONE = commit no Postgres
- Resume: buscar goals ACTIVE com tasks pendentes → retomar
- Retry: task falha → tenta de novo se attempts < max_attempts
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog

from packages.llm.base import LLMProvider, Message
from packages.memory.system import MemorySystem
from packages.shared.contracts import (
    Goal,
    GoalStatus,
    Task,
    TaskStatus,
    utcnow,
)
from packages.shared.ports import GoalStore, ToolExecutor
from packages.kernel.kernel import Kernel
from packages.registry.registry import CapabilityRegistry
from packages.kernel.runtime.base import ExecutionRequest

logger = structlog.get_logger(__name__)


DECOMPOSE_PROMPT = """\
Você é o planejador do Jarvis. Dado um objetivo, decomponha em tarefas \
executáveis. Cada tarefa deve ter um título claro e curto.

Se capacidades (capabilities) estiverem disponíveis no contexto, prefira associar \
a tarefa à capability (capability) e tool apropriadas.

Responda APENAS com JSON no formato:
[
  {"title": "...", "capability": "nome_da_cap" | null, "tool": "tool_da_cap" | null, "depends_on_index": [] }
]

depends_on_index é lista de índices (0-based) das tarefas que precisam \
terminar antes. Máximo 5 tarefas.
"""


class GoalManager:
    """Gerencia ciclo de vida de Goals e Tasks."""

    def __init__(
        self,
        goal_store: GoalStore,
        tool_executor: ToolExecutor | Kernel | None = None,
        llm: LLMProvider | None = None,
        memory: MemorySystem | None = None,
        registry: CapabilityRegistry | None = None,
        research_pipeline: Any | None = None,
    ) -> None:
        self._store = goal_store
        self._tools = tool_executor
        self._llm = llm
        # v1.3: opcional de propósito. Com `None`, este arquivo se comporta
        # exatamente como antes da fatia de memória.
        self._memory = memory
        self._registry = registry
        # Pesquisa web tem plano fixo de sete estágios; mandá-la para o
        # `decompose_goal` faria o LLM inventar um plano pior a cada execução.
        # Com `None`, um goal de pesquisa falha explicitamente em vez de virar
        # decomposição genérica silenciosa.
        self._research = research_pipeline

    async def decompose_goal(self, goal: Goal) -> list[Task]:
        """Usa LLM para decompor goal em tasks."""
        # v1.3: é aqui que uma falha repetida de capability deixa de ser histórico
        # e entra no plano seguinte (`plan.md` §10, nível `experience`).
        contexto = await self._memory.planning_context(goal) if self._memory else ""
        
        # v1.1: injetar as capabilities ativas no contexto
        caps_info = ""
        if self._registry:
            active_caps = self._registry.get_active()
            if active_caps:
                caps_info = "Capabilities ativas disponíveis:\n"
                for cap in active_caps:
                    caps_info += f"- capability: {cap.manifest.name}\n"
                    caps_info += f"  description: {cap.manifest.description}\n"
                    caps_info += f"  tools: {[t.name for t in cap.manifest.tools]}\n"
        
        full_context = f"{caps_info}\n{contexto}".strip()
        system = f"{DECOMPOSE_PROMPT}\n{full_context}" if full_context else DECOMPOSE_PROMPT

        messages = [
            Message(role="system", content=system),
            Message(
                role="user",
                content=f"Objetivo: {goal.title}\nDescrição: {goal.description}",
            ),
        ]

        completion = await self._llm.complete(messages=messages, temperature=0.3)

        try:
            raw = completion.text.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1]
                raw = raw.rsplit("```", 1)[0]
            task_defs: list[dict[str, Any]] = json.loads(raw)
        except (json.JSONDecodeError, IndexError):
            logger.error(
                "goal.decompose_failed", goal_id=str(goal.id), raw=completion.text
            )
            # Fallback: single task with goal title
            task_defs = [{"title": goal.title, "tool": None, "depends_on_index": []}]

        tasks: list[Task] = []
        for i, td in enumerate(task_defs[:5]):
            deps = [tasks[j].id for j in td.get("depends_on_index", []) if j < i]
            task = Task(
                goal_id=goal.id,
                title=td.get("title", f"Task {i+1}"),
                capability=td.get("capability"),
                tool=td.get("tool"),
                depends_on=deps,
            )
            tasks.append(task)

        created = await self._store.create_tasks(tasks)
        logger.info("goal.decomposed", goal_id=str(goal.id), task_count=len(created))
        return created

    async def execute_next_task(self, goal_id: UUID) -> Task | None:
        """Executa próxima task pendente. Retorna task executada ou None."""
        task = await self._store.next_pending_task(goal_id)
        if task is None:
            return None

        # Marca como RUNNING
        task.status = TaskStatus.RUNNING
        task.started_at = utcnow()
        task.attempts += 1
        await self._store.update_task(task)

        logger.info(
            "task.executing",
            task_id=str(task.id),
            title=task.title,
            attempt=task.attempts,
        )

        # v1.3: abre a tentativa no working memory e recupera o que a execução
        # anterior desta task já tentou — vazio quando a task é nova.
        retomado = await self._memory.on_task_started(task) if self._memory else ""
        erro: str | None = None

        try:
            if task.capability and task.tool and self._registry and isinstance(self._tools, Kernel):
                # Execução via Kernel (v1.2)
                cap = self._registry.resolve(task.capability, goal_id=task.goal_id, task_id=task.id)
                if cap is None:
                    raise Exception(f"Capability gap: capability {task.capability} não resolvida")
                
                request = ExecutionRequest(
                    capability=cap.manifest.name,
                    tool=task.tool,
                    manifest=cap.manifest,
                    arguments=task.input,
                    dry_run=task.dry_run,
                    goal_id=task.goal_id,
                    task_id=task.id
                )
                result = await self._tools.run(request)
                task.output = {"status": result.status.value, "result": result.result, "error": result.error}
                
                if result.status.value != "ok":
                    raise Exception(result.error or f"Falha na execução: {result.status.value}")
                    
            elif task.tool and not isinstance(self._tools, Kernel) and hasattr(self._tools, 'has') and self._tools.has(task.tool):
                # Fallback legado para ToolExecutor
                result = await self._tools.execute(
                    task.tool,
                    task.input,
                    dry_run=task.dry_run,
                )
                task.output = dict(result)
            else:
                # Task sem tool → usa LLM diretamente
                instrucao = "Execute a tarefa descrita. Responda com o resultado."
                if retomado:
                    instrucao = f"{instrucao}\n\n{retomado}"
                messages = [
                    Message(role="system", content=instrucao),
                    Message(role="user", content=task.title),
                ]
                completion = await self._llm.complete(messages=messages)
                task.output = {"response": completion.text}

            task.status = TaskStatus.DONE
            task.finished_at = utcnow()
            logger.info("task.completed", task_id=str(task.id))

        except Exception as exc:
            erro = str(exc)
            task.status = TaskStatus.FAILED
            task.error = erro
            task.finished_at = utcnow()
            logger.error("task.failed", task_id=str(task.id), error=erro)

            if task.can_retry:
                task.status = TaskStatus.PENDING
                task.finished_at = None
                logger.info(
                    "task.retry_scheduled", task_id=str(task.id), attempt=task.attempts
                )

        # v1.3: o working memory é gravado no MESMO checkpoint da task, logo
        # abaixo — matar o processo entre os dois deixaria os dois no estado
        # anterior, e não um adiantado em relação ao outro.
        if self._memory is not None:
            if erro is None:
                await self._memory.on_task_succeeded(task)
            else:
                await self._memory.on_task_failed(task, erro)

        # CHECKPOINT: commit via update
        await self._store.update_task(task)
        return task

    async def process_goal(self, goal_id: UUID) -> Goal | None:
        """Processa goal completo: executa tasks até acabar ou falhar."""
        goal = await self._store.get_goal(goal_id)
        if goal is None:
            return None

        if goal.status == GoalStatus.DRAFT:
            await self._store.update_goal_status(goal_id, GoalStatus.ACTIVE)

        if goal.context.get("tipo") == "research":
            return await self._processar_pesquisa(goal)

        # Decompor se não tem tasks
        tasks = await self._store.list_tasks(goal_id)
        if not tasks:
            await self.decompose_goal(goal)

        # Executar tasks em sequência de dependência
        while True:
            task = await self.execute_next_task(goal_id)
            if task is None:
                break

        # Check final state
        tasks = await self._store.list_tasks(goal_id)
        all_done = all(t.status == TaskStatus.DONE for t in tasks)
        any_failed = any(
            t.status == TaskStatus.FAILED and t.attempts >= t.max_attempts
            for t in tasks
        )

        if all_done:
            await self._store.update_goal_status(goal_id, GoalStatus.DONE)
            logger.info("goal.completed", goal_id=str(goal_id))
        elif any_failed:
            await self._store.update_goal_status(goal_id, GoalStatus.FAILED)
            logger.error("goal.failed", goal_id=str(goal_id))

        return await self._store.get_goal(goal_id)

    async def _processar_pesquisa(self, goal: Goal) -> Goal | None:
        """Goal de pesquisa web: plano fixo, sem decomposição por LLM.

        Roda aqui e não numa `Task` por capability porque o pipeline já é a
        unidade de retomada: ele é idempotente por URL (o cache de fontes) e por
        conteúdo (o hash do `ingest_document`), então reprocessar um goal
        interrompido refaz só o que faltou, sem custo de embedding repetido.
        """
        if self._research is None:
            await self._store.update_goal_status(goal.id, GoalStatus.FAILED)
            logger.error("goal.research.sem_pipeline", goal_id=str(goal.id))
            return await self._store.get_goal(goal.id)

        contexto = goal.context
        topico = str(contexto.get("topico") or goal.title)

        try:
            relatorio = await self._research.run(
                topico,
                profundidade=str(contexto.get("profundidade") or "media"),
                max_fontes=contexto.get("max_fontes"),
            )
        except Exception as exc:
            await self._store.update_goal_status(goal.id, GoalStatus.FAILED)
            logger.error("goal.research.falhou", goal_id=str(goal.id), erro=str(exc))
            return await self._store.get_goal(goal.id)

        atualizado = await self._store.get_goal(goal.id)
        if atualizado is not None:
            atualizado.context = {
                **contexto,
                "relatorio": relatorio.model_dump(mode="json"),
            }
            # Nem todo GoalStore expõe update de contexto; o relatório completo é
            # bônus, o status é o que não pode faltar.
            atualizar = getattr(self._store, "update_goal", None)
            if atualizar is not None:
                try:
                    await atualizar(atualizado)
                except Exception as exc:
                    logger.warning(
                        "goal.research.contexto_nao_salvo",
                        goal_id=str(goal.id),
                        erro=str(exc),
                    )

        await self._store.update_goal_status(goal.id, GoalStatus.DONE)
        logger.info(
            "goal.research.concluida",
            goal_id=str(goal.id),
            documentos=len(relatorio.documentos),
            chunks=relatorio.chunks_totais,
        )
        return await self._store.get_goal(goal.id)

    async def resume_active_goals(self) -> list[UUID]:
        """Resume após restart: busca goals ACTIVE e retoma processamento."""
        active = await self._store.list_goals(status=GoalStatus.ACTIVE)
        resumed: list[UUID] = []

        for goal in active:
            # Pesquisa não gera Task nenhuma, então a checagem por tasks pendentes
            # abaixo a deixaria ACTIVE para sempre depois de um restart no meio.
            if goal.context.get("tipo") == "research":
                resumed.append(goal.id)
                logger.info("goal.resumed", goal_id=str(goal.id), tipo="research")
                continue

            tasks = await self._store.list_tasks(goal.id)
            pending = [
                t
                for t in tasks
                if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
            ]

            if pending:
                # Reset tasks RUNNING → PENDING (foram interrompidas)
                for t in pending:
                    if t.status == TaskStatus.RUNNING:
                        t.status = TaskStatus.PENDING
                        t.started_at = None
                        await self._store.update_task(t)

                resumed.append(goal.id)
                logger.info(
                    "goal.resumed",
                    goal_id=str(goal.id),
                    pending_tasks=len(pending),
                )

        return resumed


__all__ = ["GoalManager"]
