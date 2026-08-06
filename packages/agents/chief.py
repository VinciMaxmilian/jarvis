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

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any
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

#: Rodadas de tool por turno no caminho normal.
_RODADAS_PADRAO = 5

#: Teto quando o turno usa `desktop_*`. Pilotar interface é uma sequência de
#: passos curtos (abrir → inspecionar → clicar → conferir → corrigir) e cinco
#: rodadas acabam antes da tarefa. Não é `_RODADAS_PADRAO` maior para todo mundo
#: porque cada rodada é uma chamada de LLM paga.
_RODADAS_DESKTOP = 15

#: Imagens enviadas ao modelo por rodada. Duas: a última captura e a anterior,
#: que é o que permite ao modelo comparar "antes" e "depois" da própria ação.
#: Sem teto, um turno de 15 rodadas mandaria 15 PNGs de tela cheia.
_TETO_IMAGENS = 2


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
        skill_registry=None,
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
        self._skills = skill_registry

    def _prompt_com_skills(self) -> str:
        """Resolve `{{SKILLS}}` a cada turno, não na carga do módulo.

        A cada turno porque uma pesquisa concluída grava uma skill nova com a API
        de pé: resolver uma vez só exigiria restart para o Jarvis saber que
        aprendeu algo, o que anularia a única parte autônoma do recurso.
        `load_prompt` memoiza o arquivo, então o custo aqui é um `replace`.
        """
        base = self._system_prompt
        if "{{SKILLS}}" not in base:
            return base
        bloco = ""
        if self._skills is not None:
            try:
                bloco = self._skills.render_prompt_block()
            except Exception as exc:  # registro quebrado não derruba o turno
                logger.warning("chief.skills.render_falhou", error=str(exc))
        return base.replace("{{SKILLS}}", bloco)

    @property
    def profile(self) -> AgentProfile:
        """O papel em vigor. Exposto para log e diagnóstico."""
        return self._profile

    async def _completar(
        self, messages: list[Message], tools: list[ToolSpec] | None, images: list[str] | None = None
    ) -> Completion:
        """Chama o LLM com a temperatura do perfil.
        
        Usa complete_with_images se houver imagens e o provider suportar.
        """
        temp = self._profile.temperature
        kwargs = {"messages": messages, "tools": tools}
        if temp is not None:
            kwargs["temperature"] = temp
            
        if images and hasattr(self._llm, "complete_with_images"):
            kwargs["images"] = images
            return await self._llm.complete_with_images(**kwargs)
            
        return await self._llm.complete(**kwargs)

    async def respond(
        self,
        user_text: str,
        conversation_id: UUID,
        current_user_email: str = "Usuário Local",
        images: list[str] | None = None,
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
        sys_prompt = self._prompt_com_skills()
        sys_prompt += f"\n\n[INFO DE CONTEXTO OBRIGATÓRIA]: O usuário atual falando com você nesta sessão é: {current_user_email}."

        _t = time.perf_counter()
        history = await self._conv.history(conversation_id, limit=30)
        _dt = time.perf_counter() - _t
        if _dt > 0.5:
            logger.warning("perf.historico_lento", segundos=round(_dt, 2))
        _t_rag = time.perf_counter()
        
        # ---------------------------------------------------------------------- #
        # RAG automático: injeta contexto da base de conhecimento e do histórico
        # no system prompt. Roda em TODA mensagem, não só na primeira, porque
        # modelos menores (ex: gemma-3n) não fazem tool calling e dependem
        # exclusivamente deste contexto para responder com fatos reais.
        # ---------------------------------------------------------------------- #
        try:
            # PARALELISMO: a busca do Agno e o embedding local são independentes e
            # cada um custa uma ida à rede (~0,7s). Em série somavam; juntos, o
            # tempo é o do mais lento.
            #
            # O embedding é especulativo de propósito: ele só é USADO se o Agno não
            # trouxer nada (o fallback abaixo) ou se o histórico estiver vazio. Mas
            # descobrir isso exige esperar o Agno, e aí não haveria mais o que
            # paralelizar. O desperdício quando o Agno acerta é uma chamada de
            # embedding barata; o ganho quando ele não acerta é a latência inteira
            # dela. A troca vale porque a base do Agno hoje devolve zero documentos
            # na maioria das perguntas — ou seja, o caminho comum é o fallback.
            vetores: list[list[float]] | None = None

            async def _buscar_agno() -> list[str]:
                if not self._agno_knowledge:
                    return []
                # Agno 2.x: search(max_results=...). Se o Agno falhar (banco fora,
                # embedder sem chave), cai no vector store local em vez de deixar
                # o agente sem NENHUM contexto — era o que acontecia antes, porque
                # a exceção do Agno matava o bloco inteiro de RAG.
                from packages.rag.agno_knowledge import documents_to_texts, search_knowledge

                try:
                    docs = await search_knowledge(
                        user_text, limit=5, knowledge=self._agno_knowledge
                    )
                    return documents_to_texts(docs)
                except Exception as exc:
                    logger.warning("memory.rag.agno_knowledge_failed", error=str(exc))
                    return []

            async def _embutir() -> list[list[float]] | None:
                if not (self._memory_store or self._chat_history_store):
                    return None
                try:
                    return await self._embed_llm.embed([user_text])
                except Exception as exc:
                    logger.warning("memory.rag.embed_failed", error=str(exc))
                    return None

            kb_textos, vetores = await asyncio.gather(_buscar_agno(), _embutir())

            _CABECALHO_KB = (
                "Fatos e preferências do usuário (base de conhecimento — "
                "USE ESTAS INFORMAÇÕES, são fatos reais e confirmados):"
            )

            if kb_textos:
                kb_context = "\n".join(f"- {t}" for t in kb_textos)
                sys_prompt += (
                    f"\n\n<knowledge_base>\n{_CABECALHO_KB}\n{kb_context}\n</knowledge_base>"
                )
                logger.info("memory.rag.agno_knowledge_injected", matches=len(kb_textos))

            # As duas buscas restantes também são independentes entre si: uma olha
            # a memória de conhecimento, a outra o histórico de conversas. Ambas
            # consomem o MESMO vetor já calculado acima — antes desta versão o
            # embedding era refeito aqui, e o `if 'vetores' not in locals()` que
            # evitava isso dependia de introspecção de escopo local, que quebra em
            # silêncio se alguém renomear a variável.
            tarefas: dict[str, Any] = {}
            if vetores and not kb_textos and self._memory_store:
                tarefas["memoria"] = self._memory_store.search(
                    vetores[0], namespace="knowledge", limit=5
                )
            # Histórico passado só na primeira mensagem da conversa.
            if vetores and not history and self._chat_history_store:
                tarefas["historico"] = self._chat_history_store.search(
                    vetores[0], namespace="chat_history", limit=5
                )

            if tarefas:
                resultados = dict(
                    zip(tarefas, await asyncio.gather(*tarefas.values()))
                )

                kb_matches = resultados.get("memoria") or []
                if kb_matches:
                    kb_context = "\n".join(f"- {m.record.text}" for m in kb_matches)
                    sys_prompt += (
                        f"\n\n<knowledge_base>\n{_CABECALHO_KB}\n{kb_context}\n</knowledge_base>"
                    )
                    logger.info("memory.rag.knowledge_injected", matches=len(kb_matches))

                hist_matches = resultados.get("historico") or []
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

        # Só loga quando dói. Estado estável medido: ~0,8s. Acima de 2s há algo
        # errado (banco lento, embedder fora), e é isso que vale aparecer.
        _dt_rag = time.perf_counter() - _t_rag
        if _dt_rag > 2.0:
            logger.warning("perf.rag_lento", segundos=round(_dt_rag, 2))

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
        #
        # MEDIDO: este passo interroga cada servidor MCP por `list_tools()`, em
        # série, ANTES de toda chamada ao modelo. O tempo aparece como silêncio
        # numa conversa por voz, então ele é logado quando passa de meio segundo.
        _t_specs = time.perf_counter()
        tool_specs = await self._tools.get_all_specs()
        _dt_specs = time.perf_counter() - _t_specs
        if _dt_specs > 0.5:
            logger.warning(
                "agent.catalogo_lento", segundos=round(_dt_specs, 2), tools=len(tool_specs)
            )

        # O orçamento de rodadas é adaptativo. Cinco basta para "busca e
        # responde", e é pouco para pilotar uma interface: abrir a tela certa,
        # inspecionar, clicar, conferir a captura e corrigir já são cinco. Subir
        # o teto para todo mundo pagaria essa conta em toda conversa, então ele
        # sobe só quando o turno de fato encosta numa tool `desktop_*`.
        limite_rodadas = _RODADAS_PADRAO

        # Imagens vivas neste turno. Começa com o que o dono anexou e passa a
        # receber as capturas devolvidas pelas tools (ver o bloco de execução
        # abaixo). `_TETO_IMAGENS` é o que impede o laço de virar um upload de
        # 15 PNGs de tela cheia para o modelo.
        capturas: list[str] = []

        _round = -1
        while (_round := _round + 1) < limite_rodadas:
            images_da_rodada = [*(images or []), *capturas][-_TETO_IMAGENS:] or None
            # LLM call (non-streaming para tool loop)
            # A imagem acompanha TODAS as rodadas deste turno, não só a primeira.
            #
            # Com `_round == 0`, o agente ficava CEGO assim que chamasse qualquer
            # ferramenta: a rodada seguinte chegava ao modelo sem a imagem, e ele
            # então descrevia de memória. Observado em produção — anexo de uma
            # foto de gato, o modelo chamou `analyze_image`, perdeu a visão
            # (input_tokens caiu de 4191 para 3165) e descreveu a última imagem
            # que conhecia do histórico. A resposta saiu confiante e errada, que
            # é o pior formato possível para esse defeito.
            #
            # Custa reenviar a imagem por rodada? Custa. Mas o laço é limitado a
            # `limite_rodadas`, é o MESMO turno do dono, e a alternativa é um
            # agente multimodal que perde a visão no meio da própria resposta.
            completion = await self._completar(
                messages=messages,
                tools=tool_specs if tool_specs else None,
                images=images_da_rodada,
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
                # ANÚNCIO ANTES DA EXECUÇÃO — este yield faltava.
                #
                # `StreamChunk.type` sempre declarou `"tool_call"`
                # (packages/llm/base.py), e DOIS consumidores já o tratavam: o
                # roteador de chat, que emite `image_analysis_started` para o PWA
                # abrir o modal de imagem, e o de voz, que fala "deixa eu
                # procurar" enquanto a ferramenta roda. Nenhum dos dois jamais
                # executou, porque este ponto — o único lugar que sabe que uma
                # tool vai rodar — nunca anunciava. Os dois recursos pareciam
                # implementados e eram código morto.
                #
                # Emitido ANTES do `await` de propósito: o valor do evento é
                # justamente cobrir a espera. Depois da execução ele não teria
                # nada a esconder.
                yield StreamChunk(type="tool_call", tool_call=tc)
                if tc.name.startswith("desktop_"):
                    limite_rodadas = max(limite_rodadas, _RODADAS_DESKTOP)

                try:
                    result = await self._tools.execute(tc.name, tc.arguments)
                    # Captura devolvida pela tool sai do JSON e entra no canal
                    # multimodal da PRÓXIMA rodada. Deixá-la no texto seria pior
                    # de duas formas: o modelo receberia base64 como se fosse
                    # prosa, e um único screenshot (~200 KB em base64) empurraria
                    # o histórico inteiro para fora da janela de contexto.
                    novas = (
                        result.pop("images_b64", None)
                        if isinstance(result, dict)
                        else None
                    )
                    if isinstance(novas, list) and novas:
                        # Filtra URL por segurança: o canal multimodal do provider
                        # espera BYTES em base64, e uma URL que escape para lá vira
                        # HTTP 400 no meio do turno, não um aviso.
                        novas = [
                            str(i) for i in novas if not str(i).startswith(("http://", "https://"))
                        ]
                    if novas:
                        capturas.extend(novas)
                        del capturas[:-_TETO_IMAGENS]
                        # `capturas`, não `images`: `web_search` já usa `images`
                        # para as URLs que ele achou, e sobrescrever aquilo com
                        # esta nota apagaria o resultado da busca.
                        result["capturas"] = (
                            f"{len(novas)} captura(s) anexada(s) como imagem nesta "
                            "conversa — olhe a imagem, ela é o estado atual da tela."
                        )
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
