import structlog
from uuid import UUID
from packages.llm.base import LLMProvider
from packages.shared.ports import ConversationStore, VectorStore, VectorRecord
from packages.shared.contracts import utcnow

logger = structlog.get_logger(__name__)

async def index_conversation_message(
    message_text: str,
    conversation_id: UUID,
    message_id: str,
    provider: LLMProvider,
    vector_store: VectorStore,
    source: str = "dono",
) -> None:
    """Vetoriza uma única mensagem (ou trecho) e salva no histórico cruzado."""
    texto = message_text.strip()
    if not texto:
        return

    try:
        # Gera embedding
        vetores = await provider.embed([texto])
        
        # Upsert no VectorStore
        await vector_store.upsert(
            [
                VectorRecord(
                    id=f"msg-{message_id}",
                    namespace="chat_history",
                    text=texto,
                    embedding=list(vetores[0]),
                    metadata={
                        "conversation_id": str(conversation_id),
                        "source": source,
                        "updated_at": utcnow().isoformat(),
                    },
                )
            ]
        )
        logger.info("memory.indexer.indexed", message_id=message_id, conv_id=str(conversation_id))
    except Exception as exc:
        logger.error("memory.indexer.failed", error=str(exc), message_id=message_id)

