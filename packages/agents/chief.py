"""Chief AI — núcleo mínimo da v0.

Recebe mensagem do usuário, envia para LLM com tools, executa tool calls em loop,
devolve stream de texto. O Chief AI NUNCA executa nada diretamente — delega ao
ToolExecutor (ports.py).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID

import structlog

from packages.llm.base import (
    LLMProvider,
    Message,
    StreamChunk,
)
from packages.shared.contracts import ChatMessage, MessageRole
from packages.shared.ports import ConversationStore, ToolExecutor, VectorStore

logger = structlog.get_logger(__name__)

SYSTEM_PROMPT = """\
Você é o Jarvis, um sistema operacional cognitivo pessoal. Você ajuda o dono a \
alcançar objetivos delegando tarefas e usando ferramentas.

Regras:
- Sempre responda em português brasileiro, a menos que o dono peça outro idioma.
- Quando precisar de informações atuais, use a ferramenta web_search.
- Seja direto e objetivo.
- Se não sabe algo e não tem ferramentas para descobrir, diga.
"""


class ChiefAI:
    """Chief AI v0: LLM loop com tool calling."""

    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolExecutor,
        conversation_store: ConversationStore,
        system_prompt: str | None = None,
        chat_history_store: VectorStore | None = None,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._conv = conversation_store
        self._system_prompt = system_prompt or SYSTEM_PROMPT
        self._chat_history_store = chat_history_store

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
        
        # Recuperação automática de RAG (Busca Vetorial do Histórico) apenas para a primeira mensagem
        if not history and self._chat_history_store:
            try:
                vetores = await self._llm.embed([user_text])
                matches = await self._chat_history_store.search(
                    vetores[0], namespace="chat_history", limit=5
                )
                
                if matches:
                    past_context = "\n".join(f"- {m.record.text} (Data: {m.record.metadata.get('updated_at', 'desconhecida')})" for m in matches)
                    sys_prompt += f"\n\n<past_context>\nAqui estão informações relevantes de conversas passadas que podem ser úteis para esta sessão:\n{past_context}\n</past_context>"
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

        tool_specs = self._tools.specs()
        max_tool_rounds = 5

        for _round in range(max_tool_rounds):
            # LLM call (non-streaming para tool loop)
            completion = await self._llm.complete(
                messages=messages,
                tools=tool_specs if tool_specs else None,
            )

            logger.info(
                "llm.complete",
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
                logger.info("tool.execute", name=tc.name, args=tc.arguments)
                try:
                    result = await self._tools.execute(tc.name, tc.arguments)
                    result_str = json.dumps(result, ensure_ascii=False, default=str)
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


__all__ = ["ChiefAI"]
