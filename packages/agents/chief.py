"""Chief AI — núcleo mínimo da v0.

Recebe mensagem do usuário, envia para LLM com tools, executa tool calls em loop,
devolve stream de texto. O Chief AI NUNCA executa nada diretamente — delega ao
ToolExecutor (ports.py).

**O papel é parâmetro, não é esta classe.** O prompt, as tools disponíveis e a
temperatura vêm de um `AgentProfile` (`packages/agents/profiles.py`); esta classe
só roda o loop. Sem perfil explícito o agente recebe o `CHIEF_PROFILE`, que
carrega o prompt histórico, libera o catálogo inteiro e não manda temperatura —
o comportamento de antes desta separação, preservado de propósito.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID

import structlog

from packages.agents.profiles import CHIEF_PROFILE, AgentProfile, load_prompt
from packages.agents.tool_guard import ProfiledToolExecutor, ToolDenied, guard_tools
from packages.llm.base import (
    Completion,
    LLMProvider,
    Message,
    StreamChunk,
)
from packages.shared.contracts import ChatMessage, MessageRole, ToolSpec
from packages.shared.ports import ConversationStore, ToolExecutor, VectorStore

logger = structlog.get_logger(__name__)

#: Prompt do papel `chief`, agora em `prompts/chief.md`.
#:
#: Mantido como constante do módulo porque era API pública deste arquivo. O texto
#: é o mesmo byte a byte — `tests/unit/test_agent_profiles.py` trava isso, já que
#: uma mudança acidental no prompt não quebra nada e só piora as respostas.
SYSTEM_PROMPT = load_prompt(CHIEF_PROFILE)


class ChiefAI:
    """Chief AI v0: LLM loop com tool calling, sob um perfil de agente."""

    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolExecutor,
        conversation_store: ConversationStore,
        system_prompt: str | None = None,
        chat_history_store: VectorStore | None = None,
        memory_vector_store: VectorStore | None = None,
        embed_llm: LLMProvider | None = None,
        profile: AgentProfile | None = None,
        agno_knowledge=None,
    ) -> None:
        self._profile = profile or CHIEF_PROFILE
        self._llm = llm
        # Provider dedicado para embeddings. Quando o provider de chat (ex: LM Studio)
        # não suporta embeddings, usamos outro (ex: Gemini) que tem API de embedding.
        self._embed_llm = embed_llm or llm
        # As tools passam pela política do perfil antes de chegar ao loop: é o
        # envelope, e não a boa vontade deste arquivo, que impede um planner de
        # executar. Ver `tool_guard.py`.
        self._tools: ProfiledToolExecutor = guard_tools(tools, self._profile)
        self._conv = conversation_store
        # `system_prompt` explícito continua vencendo o perfil: é por onde o dono
        # sobrescreve o prompt pelo banco (`apps/api/deps.get_chief_ai`).
        self._system_prompt = system_prompt or load_prompt(self._profile)
        self._chat_history_store = chat_history_store
        self._memory_store = memory_vector_store
        self._agno_knowledge = agno_knowledge

    @property
    def profile(self) -> AgentProfile:
        """O papel em vigor. Exposto para log e diagnóstico."""
        return self._profile

    async def _completar(
        self, messages: list[Message], tools: list[ToolSpec] | None
    ) -> Completion:
        """Chama o LLM com a temperatura do perfil.

        Os dois ramos existem porque `temperature=None` no perfil significa "não
        mande o parâmetro", e não "mande `None`": o default do provider é uma
        decisão dele, e o `CHIEF_PROFILE` a preserva. Passar `0.7` escrito aqui
        pareceria igual e congelaria um valor que hoje é do provider.
        """
        if self._profile.temperature is None:
            return await self._llm.complete(messages=messages, tools=tools)
        return await self._llm.complete(
            messages=messages, tools=tools, temperature=self._profile.temperature
        )

    async def respond(
        self,
        user_text: str,
        conversation_id: UUID,
        current_user_email: str = "Usuário Local",
    ) -> AsyncIterator[StreamChunk]:
        """Processa mensagem do usuário. Yield StreamChunks para streaming."""

        await self._conv.ensure_conversation(conversation_id)

        # Persiste mensagem do user
        user_msg = ChatMessage(
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=user_text,
        )
        await self._conv.append(user_msg)

        # Carrega histórico
        # Injeta a identidade atual no system prompt
        sys_prompt = self._system_prompt
        sys_prompt += f"\n\n[INFO DE CONTEXTO OBRIGATÓRIA]: O usuário atual falando com você nesta sessão é: {current_user_email}."

        history = await self._conv.history(conversation_id, limit=30)
        
        # ---------------------------------------------------------------------- #
        # RAG automático: injeta contexto da base de conhecimento e do histórico
        # no system prompt. Roda em TODA mensagem, não só na primeira, porque
        # modelos menores (ex: gemma-3n) não fazem tool calling e dependem
        # exclusivamente deste contexto para responder com fatos reais.
        # ---------------------------------------------------------------------- #
        try:
            # 1. Knowledge base (fatos, preferências do usuário)
            kb_textos: list[str] = []
            if self._agno_knowledge:
                # Agno 2.x: search(max_results=...). Se o Agno falhar (banco fora,
                # embedder sem chave), cai no vector store local em vez de deixar
                # o agente sem NENHUM contexto — era o que acontecia antes, porque
                # a exceção do Agno matava o bloco inteiro de RAG.
                from packages.rag.agno_knowledge import documents_to_texts, search_knowledge

                try:
                    docs = await search_knowledge(
                        user_text, limit=5, knowledge=self._agno_knowledge
                    )
                    kb_textos = documents_to_texts(docs)
                except Exception as exc:
                    logger.warning("memory.rag.agno_knowledge_failed", error=str(exc))

                if kb_textos:
                    kb_context = "\n".join(f"- {t}" for t in kb_textos)
                    sys_prompt += (
                        f"\n\n<knowledge_base>\n"
                        f"Fatos e preferências do usuário (base de conhecimento — USE ESTAS INFORMAÇÕES, são fatos reais e confirmados):\n"
                        f"{kb_context}\n"
                        f"</knowledge_base>"
                    )
                    logger.info("memory.rag.agno_knowledge_injected", matches=len(kb_textos))

            if not kb_textos and self._memory_store:
                vetores = await self._embed_llm.embed([user_text])
                kb_matches = await self._memory_store.search(
                    vetores[0], namespace="knowledge", limit=5
                )
                if kb_matches:
                    kb_context = "\n".join(
                        f"- {m.record.text}" for m in kb_matches
                    )
                    sys_prompt += (
                        f"\n\n<knowledge_base>\n"
                        f"Fatos e preferências do usuário (base de conhecimento — USE ESTAS INFORMAÇÕES, são fatos reais e confirmados):\n"
                        f"{kb_context}\n"
                        f"</knowledge_base>"
                    )
                    logger.info("memory.rag.knowledge_injected", matches=len(kb_matches))
            
            # 2. Histórico de conversas passadas (apenas na primeira msg da conversa)
            if not history and self._chat_history_store:
                if 'vetores' not in locals():
                    vetores = await self._embed_llm.embed([user_text])
                hist_matches = await self._chat_history_store.search(
                    vetores[0], namespace="chat_history", limit=5
                )
                if hist_matches:
                    past_context = "\n".join(
                        f"- {m.record.text} (Data: {m.record.metadata.get('updated_at', 'desconhecida')})"
                        for m in hist_matches
                    )
                    sys_prompt += (
                        f"\n\n<past_context>\n"
                        f"Informações relevantes de conversas passadas:\n"
                        f"{past_context}\n"
                        f"</past_context>"
                    )
        except Exception as exc:
            logger.warning("memory.rag.failed", error=str(exc))

        messages = [Message(role="system", content=sys_prompt)]
        for h in history:
            messages.append(
                Message(
                    role=h.role.value,
                    content=h.content,
                    tool_call_id=h.tool_call_id,
                )
            )

        # O envelope do perfil resolve as duas formas do catálogo (síncrona e
        # async) e devolve só o que este papel pode chamar.
        tool_specs = await self._tools.get_all_specs()

        max_tool_rounds = 5

        for _round in range(max_tool_rounds):
            # LLM call (non-streaming para tool loop)
            completion = await self._completar(
                messages=messages,
                tools=tool_specs if tool_specs else None,
            )

            logger.info(
                "llm.complete",
                profile=self._profile.name,
                model=completion.model,
                input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
                tool_calls=len(completion.tool_calls),
            )

            if not completion.wants_tools:
                # Resposta final — stream o texto
                if completion.text:
                    yield StreamChunk(type="text", text=completion.text)

                # Persiste resposta
                assistant_msg = ChatMessage(
                    conversation_id=conversation_id,
                    role=MessageRole.ASSISTANT,
                    content=completion.text,
                    input_tokens=completion.input_tokens,
                    output_tokens=completion.output_tokens,
                    model=completion.model,
                )
                await self._conv.append(assistant_msg)

                yield StreamChunk(type="done", completion=completion)
                return

            # Tem tool calls — executar
            # Persiste assistant msg com tool calls
            assistant_msg = ChatMessage(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=completion.text,
                tool_calls=[
                    {
                        "id": tc.id,
                        "name": tc.name,
                        "arguments": tc.arguments,
                        "thought_signature": tc.thought_signature,
                    }
                    for tc in completion.tool_calls
                ],
                input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
                model=completion.model,
            )
            await self._conv.append(assistant_msg)

            # Adiciona assistant message com tool_calls ao contexto
            messages.append(
                Message(
                    role="assistant",
                    content=completion.text,
                    tool_calls=completion.tool_calls,
                )
            )

            # Executa cada tool call
            for tc in completion.tool_calls:
                logger.info(
                    "tool.execute",
                    profile=self._profile.name,
                    name=tc.name,
                    args=tc.arguments,
                )
                try:
                    result = await self._tools.execute(tc.name, tc.arguments)
                    result_str = json.dumps(result, ensure_ascii=False, default=str)
                except ToolDenied as exc:
                    # Recusa volta como resultado da tool, não como exceção que
                    # mata o turno: o modelo lê que não pode, e o loop segue com
                    # o que sobrou. Derrubar aqui deixaria o dono sem resposta
                    # porque o modelo pediu algo que este papel não faz.
                    logger.warning(
                        "tool.denied", profile=self._profile.name, name=tc.name
                    )
                    result_str = json.dumps({"error": str(exc)}, ensure_ascii=False)
                except Exception as exc:
                    logger.error("tool.error", name=tc.name, error=str(exc))
                    result_str = json.dumps({"error": str(exc)})

                # Persiste tool result
                tool_msg = ChatMessage(
                    conversation_id=conversation_id,
                    role=MessageRole.TOOL,
                    content=result_str,
                    tool_call_id=tc.id,
                )
                await self._conv.append(tool_msg)

                messages.append(
                    Message(role="tool", content=result_str, tool_call_id=tc.id)
                )

        # Safety: max rounds atingido
        yield StreamChunk(
            type="text",
            text="Atingi o limite de chamadas de ferramentas. Tente reformular.",
        )
        yield StreamChunk(type="done")


__all__ = ["SYSTEM_PROMPT", "ChiefAI"]
