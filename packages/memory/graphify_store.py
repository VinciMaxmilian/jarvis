import asyncio
import os
import subprocess
from pathlib import Path
from collections.abc import Sequence

import structlog

from packages.shared.ports import VectorMatch, VectorRecord
from packages.memory.vector_store import InMemoryVectorStore

logger = structlog.get_logger(__name__)

class GraphifyVectorStore(InMemoryVectorStore):
    """
    Híbrido: InMemoryVectorStore para RAG rápido + Graphify corpus generation.
    Os textos inseridos na memória são salvos como arquivos Markdown para o Graphify
    poder ler e construir o grafo em background/sob demanda.
    """

    def __init__(
        self,
        persist_path: str | Path | None = None,
        corpus_dir: str | Path = "./data/memory_corpus"
    ) -> None:
        super().__init__(persist_path=persist_path)
        self._corpus_dir = Path(corpus_dir)
        self._corpus_dir.mkdir(parents=True, exist_ok=True)

    async def upsert(self, records: Sequence[VectorRecord]) -> int:
        # 1. In-memory upsert para RAG (rápido)
        inserted = await super().upsert(records)
        
        # 2. Salva em disco para o Graphify
        for record in records:
            safe_id = "".join(c if c.isalnum() else "_" for c in record.id)
            filepath = self._corpus_dir / f"{safe_id}.md"
            
            content = f"# Memória: {record.namespace}\n\n{record.text}\n"
            if record.metadata:
                content += "\n## Metadata\n"
                for k, v in record.metadata.items():
                    content += f"- **{k}**: {v}\n"
            
            try:
                filepath.write_text(content, encoding="utf-8")
            except Exception as e:
                logger.error("memory.graphify_store.write_failed", error=str(e), id=record.id)
                
        return inserted

    async def delete(self, ids: Sequence[str]) -> int:
        removed = await super().delete(ids)
        
        # Remove from corpus
        for r_id in ids:
            safe_id = "".join(c if c.isalnum() else "_" for c in r_id)
            filepath = self._corpus_dir / f"{safe_id}.md"
            if filepath.exists():
                filepath.unlink()
                
        return removed

    def trigger_graphify_update(self) -> None:
        """Chama o comando graphify update na pasta do corpus (Processo em Lote)."""
        try:
            logger.info("memory.graphify_store.updating_graph", corpus=str(self._corpus_dir))
            
            # Executa o graphify dentro da pasta do corpus para que ele crie 
            # a pasta graphify-out localmente lá (data/memory_corpus/graphify-out)
            cmd = ["graphify", "update", "."]
            
            subprocess.Popen(
                cmd,
                cwd=str(self._corpus_dir.absolute()),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception as e:
            logger.error("memory.graphify_store.update_failed", error=str(e))
