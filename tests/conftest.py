"""Dublês das portas de `packages/shared/ports.py` e da camada de LLM.

A suíte da v1.0 não sobe Postgres nem chama provider externo: cada adaptador
real tem aqui um par em memória que implementa a **mesma porta**. Como as portas
são `runtime_checkable`, `isinstance(x, Porta)` é verificado em
`tests/unit/test_fixtures.py` — dublê que sai do contrato falha na suíte, não em
produção.

Determinismo é requisito, não conveniência: resposta de LLM é roteirizada e
embedding sai de hash estável, para que asserção sobre ordem de ranking valha
entre processos e máquinas.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import AsyncIterator, Iterable, Sequence
from typing import Any
from uuid import UUID, uuid4

import pytest

from packages.llm.base import Completion, Message, StreamChunk, ToolCall
from packages.shared.contracts import (
    ChatMessage,
    Event,
    Goal,
    GoalStatus,
    Task,
    TaskStatus,
    ToolSpec,
    utcnow,
)

# --------------------------------------------------------------------------- #
# LLM
# --------------------------------------------------------------------------- #


class FakeLLMProvider:
    """`LLMProvider` roteirizado. Sem rede, sem aleatoriedade.

    `complete()` consome a fila de `queue_text`/`queue_tool_call` na ordem; fila
    vazia devolve `default_text`, para que teste que não se importa com o texto
    não precise roteirizar nada.
    """

    def __init__(
        self,
        *,
        name: str = "fake",
        model: str = "fake-model-1",
        default_text: str = "resposta padrão do dublê",
        embedding_dim: int = 8,
    ) -> None:
        self.name = name
        self.model = model
        self.default_text = default_text
        self.embedding_dim = embedding_dim

        self._scripted: list[Completion] = []
        #: Contadores por operação — asserção de "não repetiu a task concluída"
        #: se apoia neles.
        self.complete_calls = 0
        self.stream_calls = 0
        self.embed_calls = 0
        #: Cada lista de mensagens recebida, na ordem, para inspeção de prompt.
        self.received: list[list[Message]] = []

    # -- roteiro ---------------------------------------------------------- #

    def queue_text(self, text: str) -> FakeLLMProvider:
        """Enfileira uma resposta de texto puro. Retorna `self` para encadear."""
        self._scripted.append(
            Completion(text=text, model=self.model, finish_reason="stop")
        )
        return self

    def queue_tool_call(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        call_id: str | None = None,
        text: str = "",
    ) -> FakeLLMProvider:
        """Enfileira uma resposta que pede execução de tool."""
        self._scripted.append(
            Completion(
                text=text,
                tool_calls=[
                    ToolCall(
                        id=call_id or f"call_{len(self._scripted)}",
                        name=name,
                        arguments=arguments or {},
                    )
                ],
                model=self.model,
                finish_reason="tool_use",
            )
        )
        return self

    def queue(self, completion: Completion) -> FakeLLMProvider:
        """Enfileira uma `Completion` montada à mão (tokens, finish_reason)."""
        self._scripted.append(completion)
        return self

    @property
    def pending(self) -> int:
        """Quantas respostas roteirizadas ainda não foram consumidas."""
        return len(self._scripted)

    # -- porta ------------------------------------------------------------ #

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system: str | None = None,
    ) -> Completion:
        self.complete_calls += 1
        self.received.append(list(messages))
        return self._next_completion()

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        self.stream_calls += 1
        self.received.append(list(messages))
        completion = self._next_completion()

        if completion.text:
            yield StreamChunk(type="text", text=completion.text)
        for call in completion.tool_calls:
            yield StreamChunk(type="tool_call", tool_call=call)
        yield StreamChunk(type="done", completion=completion)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls += 1
        return [stable_embedding(t, dim=self.embedding_dim) for t in texts]

    # -- interno ---------------------------------------------------------- #

    def _next_completion(self) -> Completion:
        if self._scripted:
            return self._scripted.pop(0)
        return Completion(text=self.default_text, model=self.model, finish_reason="stop")


def stable_embedding(text: str, *, dim: int = 8) -> list[float]:
    """Vetor unitário derivado de SHA-256 do texto.

    `hash()` embutido é semeado por processo e devolveria ranking diferente a
    cada execução; SHA-256 dá o mesmo vetor em qualquer máquina, então teste de
    retrieval pode afirmar a ordem exata dos vizinhos.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    raw = [digest[i % len(digest)] / 255.0 for i in range(dim)]
    norm = math.sqrt(sum(v * v for v in raw))
    if norm == 0.0:  # pragma: no cover — SHA-256 nunca dá 32 bytes zerados
        return [0.0] * dim
    return [v / norm for v in raw]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Similaridade de cosseno. Usada para afirmar ranking de `embed()`."""
    return sum(x * y for x, y in zip(a, b, strict=True))


# --------------------------------------------------------------------------- #
# Embeddings (v1.3 — memória `knowledge` e `long`)
# --------------------------------------------------------------------------- #

_TOKEN = re.compile(r"\w+", re.UNICODE)

#: 256 baldes: colisão de hash entre duas palavras diferentes vira ruído no
#: ranking, e com uma dúzia de documentos por teste 64 baldes já colidiam o
#: suficiente para o vizinho certo empatar com o errado.
EMBEDDING_DIM = 256


def hashed_embedding(text: str, *, dim: int = EMBEDDING_DIM) -> list[float]:
    """Saco de palavras com hashing, normalizado. Determinístico e **sem rede**.

    `stable_embedding` (acima) resolve outro problema: ele dá um vetor estável
    por texto, mas descorrelacionado do conteúdo — dois textos sobre o mesmo
    assunto ficam tão distantes quanto dois textos sobre assuntos opostos. Serve
    para afirmar "o mesmo texto dá o mesmo vetor"; não serve para afirmar que uma
    **busca semântica** encontrou o documento certo, que é o aceite da v1.3.

    Aqui, sobreposição de vocabulário vira proximidade de cosseno: a consulta que
    compartilha palavras com o documento fica mais perto dele do que dos outros.
    É a propriedade mínima de um embedding real, e é a única de que o teste de
    recuperação precisa. SHA-256 por token mantém o resultado igual entre
    processos e máquinas (o `hash()` embutido é semeado por processo).
    """
    vetor = [0.0] * dim
    for token in _TOKEN.findall(text.lower()):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        vetor[int.from_bytes(digest[:8], "big") % dim] += 1.0
    norma = math.sqrt(sum(v * v for v in vetor))
    if norma == 0.0:
        return vetor
    return [v / norma for v in vetor]


class FakeEmbeddingProvider:
    """`LLMProvider` cuja única razão de existir é `embed()`.

    Esta máquina não tem **nenhum** modelo de inferência rodando — sem LM Studio,
    sem Ollama, sem chave em uso. Todo teste de memória depende deste dublê, e a
    porta é a mesma que a produção usa (`LLMProvider.embed`), então o caminho
    exercitado é o real: nenhum módulo de memória importa SDK de embedding.

    `complete()`/`stream()` respondem texto fixo — quem precisa de roteiro usa o
    `FakeLLMProvider`.
    """

    def __init__(
        self,
        *,
        name: str = "fake-embeddings",
        model: str = "fake-embed-1",
        dim: int = EMBEDDING_DIM,
        default_text: str = "resposta padrão do dublê de embeddings",
    ) -> None:
        self.name = name
        self.model = model
        self.dim = dim
        self.default_text = default_text
        #: Quantas vezes `embed()` foi chamado e com quantos textos — é como o
        #: teste prova que a reindexação incremental NÃO recalculou nada.
        self.embed_calls = 0
        self.embedded: list[list[str]] = []

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system: str | None = None,
    ) -> Completion:
        return Completion(text=self.default_text, model=self.model, finish_reason="stop")

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        completion = await self.complete(messages, tools, temperature, max_tokens, system)
        yield StreamChunk(type="text", text=completion.text)
        yield StreamChunk(type="done", completion=completion)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls += 1
        self.embedded.append(list(texts))
        return [hashed_embedding(t, dim=self.dim) for t in texts]

    @property
    def embedded_count(self) -> int:
        """Total de textos vetorizados desde o início. Zero é uma asserção válida."""
        return sum(len(lote) for lote in self.embedded)


# --------------------------------------------------------------------------- #
# GoalStore
# --------------------------------------------------------------------------- #


class InMemoryGoalStore:
    """`GoalStore` em dicionário, com a mesma semântica do `PgGoalStore`.

    Guarda e devolve **cópias profundas**: o adaptador Postgres só vê mudança
    depois de `update_task`, e um dublê que compartilhasse a instância deixaria
    passar bug de "esqueci de persistir". A ordem de `list_tasks` vem da ordem de
    inserção, não de `created_at`, que empata quando duas tasks nascem no mesmo
    microssegundo.
    """

    def __init__(self) -> None:
        self._goals: dict[UUID, Goal] = {}
        self._tasks: dict[UUID, Task] = {}
        self._task_seq: dict[UUID, int] = {}
        self._seq = 0

    async def create_goal(self, goal: Goal) -> Goal:
        self._goals[goal.id] = goal.model_copy(deep=True)
        return goal

    async def get_goal(self, goal_id: UUID) -> Goal | None:
        stored = self._goals.get(goal_id)
        return stored.model_copy(deep=True) if stored else None

    async def list_goals(
        self, status: GoalStatus | None = None, limit: int = 50
    ) -> list[Goal]:
        goals = [g.model_copy(deep=True) for g in self._goals.values()]
        if status is not None:
            goals = [g for g in goals if g.status == status]
        goals.sort(key=lambda g: g.created_at, reverse=True)
        return goals[:limit]

    async def update_goal_status(self, goal_id: UUID, status: GoalStatus) -> Goal | None:
        stored = self._goals.get(goal_id)
        if stored is None:
            return None
        stored.status = status
        stored.updated_at = utcnow()
        if status == GoalStatus.DONE:
            stored.completed_at = utcnow()
        return stored.model_copy(deep=True)

    async def create_tasks(self, tasks: Sequence[Task]) -> list[Task]:
        for task in tasks:
            self._tasks[task.id] = task.model_copy(deep=True)
            self._task_seq[task.id] = self._seq
            self._seq += 1
        return list(tasks)

    async def get_task(self, task_id: UUID) -> Task | None:
        stored = self._tasks.get(task_id)
        return stored.model_copy(deep=True) if stored else None

    async def list_tasks(self, goal_id: UUID) -> list[Task]:
        rows = [t for t in self._tasks.values() if t.goal_id == goal_id]
        rows.sort(key=lambda t: self._task_seq[t.id])
        return [t.model_copy(deep=True) for t in rows]

    async def update_task(self, task: Task) -> Task:
        if task.id not in self._tasks:
            raise ValueError(f"Task {task.id} not found")
        self._tasks[task.id] = task.model_copy(deep=True)
        return task

    async def next_pending_task(self, goal_id: UUID) -> Task | None:
        """Primeira tarefa `pending` cujas dependências já estão `done`."""
        tasks = await self.list_tasks(goal_id)
        done_ids = {t.id for t in tasks if t.status == TaskStatus.DONE}
        for task in tasks:
            if task.status != TaskStatus.PENDING:
                continue
            if all(dep in done_ids for dep in task.depends_on):
                return task
        return None


# --------------------------------------------------------------------------- #
# EventBus
# --------------------------------------------------------------------------- #


class InMemoryEventBus:
    """`EventBus` que grava tudo em `published`.

    Evento é o único canal entre módulos (`plan-execution.md` §7); sem registro
    do que foi publicado, "emitiu o evento" não é afirmação verificável.
    """

    def __init__(self) -> None:
        self.published: list[Event] = []

    async def publish(self, event: Event) -> None:
        self.published.append(event)

    # -- consulta --------------------------------------------------------- #

    @property
    def types(self) -> list[str]:
        return [e.type for e in self.published]

    def of_type(self, event_type: str) -> list[Event]:
        return [e for e in self.published if e.type == event_type]

    def clear(self) -> None:
        self.published.clear()


# --------------------------------------------------------------------------- #
# ConversationStore
# --------------------------------------------------------------------------- #


class InMemoryConversationStore:
    """`ConversationStore` em lista, na ordem de escrita."""

    def __init__(self) -> None:
        self._messages: list[ChatMessage] = []
        self.conversations: set[UUID] = set()

    async def append(self, message: ChatMessage) -> ChatMessage:
        self._messages.append(message.model_copy(deep=True))
        return message

    async def history(self, conversation_id: UUID, limit: int = 50) -> list[ChatMessage]:
        rows = [m for m in self._messages if m.conversation_id == conversation_id]
        return [m.model_copy(deep=True) for m in rows[:limit]]

    async def ensure_conversation(self, conversation_id: UUID) -> UUID:
        self.conversations.add(conversation_id)
        return conversation_id


# --------------------------------------------------------------------------- #
# ToolExecutor
# --------------------------------------------------------------------------- #


class RecordingToolExecutor:
    """`ToolExecutor` que registra chamadas em vez de executar.

    O Chief AI e o GoalManager exigem a porta no construtor; aqui ela existe só
    para provar *que* foi chamada, com quais argumentos e com qual `dry_run`.
    """

    def __init__(
        self,
        specs: Iterable[ToolSpec] | None = None,
        *,
        results: dict[str, dict[str, object]] | None = None,
    ) -> None:
        self._specs = list(specs or [])
        self._results = results or {}
        self.calls: list[tuple[str, dict[str, object], bool]] = []

    def specs(self) -> list[ToolSpec]:
        return list(self._specs)

    def has(self, name: str) -> bool:
        return any(s.name == name for s in self._specs)

    async def execute(
        self, name: str, arguments: dict[str, object], dry_run: bool = False
    ) -> dict[str, object]:
        self.calls.append((name, dict(arguments), dry_run))
        return self._results.get(name, {"ok": True, "tool": name})


def make_tool_spec(name: str, description: str = "tool de teste") -> ToolSpec:
    """`ToolSpec` mínima e válida (o `input_schema` é JSON Schema de verdade)."""
    return ToolSpec(
        name=name,
        description=description,
        input_schema={"type": "object", "properties": {}},
    )


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def fake_llm() -> FakeLLMProvider:
    return FakeLLMProvider()


@pytest.fixture
def goal_store() -> InMemoryGoalStore:
    return InMemoryGoalStore()


@pytest.fixture
def event_bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture
def conversation_store() -> InMemoryConversationStore:
    return InMemoryConversationStore()


@pytest.fixture
def tool_executor() -> RecordingToolExecutor:
    return RecordingToolExecutor([make_tool_spec("web_search")])


@pytest.fixture
def goal_id() -> UUID:
    return uuid4()


# -- memória (v1.3) ---------------------------------------------------------- #


@pytest.fixture
def fake_embeddings() -> FakeEmbeddingProvider:
    """Provider de embeddings determinístico. Nenhum teste de memória toca a rede."""
    return FakeEmbeddingProvider()
