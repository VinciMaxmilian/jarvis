import structlog

logger = structlog.get_logger(__name__)

class KnowledgeBaseAdapter:
    def __init__(self, memory_system):
        self.kb = memory_system.knowledge

    async def list_indexed(self):
        return await self.kb._index.all()

    async def upsert(self, document) -> None:
        from packages.memory.models import KnowledgeDocument as MemDoc
        mem_doc = MemDoc(
            doc_id=document.doc_id,
            source=document.source,
            text=document.text
        )
        await self.kb.ingest(mem_doc)
        
        # Agno Knowledge — API 2.x: add_content_async(text_content=..., name=...).
        # NÃO existe insert()/ainsert(); a versão antiga deste código testava por
        # hasattr() e simplesmente não indexava nada, sem erro nenhum.
        try:
            from packages.rag.agno_knowledge import add_knowledge
            await add_knowledge(
                text=document.text,
                name=document.source,
                metadata={"doc_id": document.doc_id, "source": document.source},
            )
            logger.info("agno_knowledge.upsert.ok", source=document.source)
        except Exception as e:
            logger.warning("agno_knowledge.upsert.failed", source=document.source, error=str(e))

    async def delete(self, doc_ids):
        count = 0
        for did in doc_ids:
            if await self.kb._index.delete(did):
                count += 1
        return count
