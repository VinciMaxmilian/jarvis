import asyncio
import os
import sys

# Ensure the root of the repo is in the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from apps.api.deps import _build_gemini
from packages.shared.settings import Settings
from packages.scheduler.reindex import ReindexService
from packages.scheduler.config import SchedulerConfig
from packages.memory.factory import build_memory_system
from packages.memory.models import KnowledgeDocument
import structlog
import logging

logging.basicConfig(level=logging.INFO)
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

    async def delete(self, doc_ids):
        count = 0
        for did in doc_ids:
            if await self.kb._index.delete(did):
                count += 1
        return count

async def main() -> None:
    try:
        cfg = SchedulerConfig()
        settings = Settings()
        
        provider = _build_gemini(settings, "")
        memory = build_memory_system(provider)
        adapter = KnowledgeBaseAdapter(memory)
        
        service = ReindexService(
            source_dir=cfg.knowledge_dir,
            index=adapter
        )
        
        resultado = await service.run()
        logger.info("reindex_forced.completed", 
                    unchanged=resultado.unchanged, 
                    scanned=resultado.scanned,
                    added=resultado.added,
                    updated=resultado.updated,
                    removed=resultado.removed)
                    
    except Exception as exc:
        logger.error("reindex_forced.failed", error=str(exc))
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
