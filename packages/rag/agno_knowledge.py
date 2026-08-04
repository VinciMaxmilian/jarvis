"""Integração com o Knowledge do Agno (RAG sobre PgVector).

ATENÇÃO À VERSÃO: a API do Agno mudou entre 1.x e 2.x. Este módulo fala 2.x:
  - busca:   Knowledge.search(query, max_results=...)   # era num_documents= no 1.x
  - ingesta: Knowledge.add_content_async(text_content=..., name=...)
             (não existe insert()/ainsert() — chamar por hasattr() vira no-op
              silencioso, que foi exatamente o bug que deixou a base vazia)
O pin em pyproject.toml é `agno>=2.2,<3` justamente para travar esse contrato.

Todo acesso ao Knowledge deve passar por search_knowledge()/add_knowledge()
daqui, para a assinatura do Agno ficar num lugar só.
"""

import asyncio
import logging
from typing import Any, Iterable, Optional

from packages.shared.settings import get_settings

logger = logging.getLogger(__name__)

# Import Agno knowledge modules
try:
    from agno.knowledge.knowledge import Knowledge
    from agno.vectordb.pgvector import PgVector
    from agno.knowledge.embedder.google import GeminiEmbedder
except ImportError:  # pragma: no cover - depende do ambiente
    Knowledge = None
    PgVector = None
    GeminiEmbedder = None


_KNOWLEDGE_INSTANCE: Optional[Any] = None

KNOWLEDGE_TABLE = "agno_knowledge_vectors"


def get_agno_knowledge() -> Any:
    """Retorna a instância singleton de Knowledge do Agno.

    Faz I/O de banco na construção (o __post_init__ do Knowledge cria a tabela
    se não existir), então em contexto async prefira get_agno_knowledge_async().
    """
    global _KNOWLEDGE_INSTANCE

    if _KNOWLEDGE_INSTANCE is not None:
        return _KNOWLEDGE_INSTANCE

    settings = get_settings()

    if Knowledge is None or PgVector is None or GeminiEmbedder is None:
        raise ImportError(
            "Agno modules are not installed properly. Ensure 'agno>=2.2' and 'pgvector' are installed."
        )

    # Converte postgresql+asyncpg para postgresql+psycopg
    db_url = settings.database_url.replace("+asyncpg", "+psycopg")

    # Para o gemini, ele precisa de uma API key
    if not settings.gemini_api_key:
        raise ValueError("gemini_api_key is required to use Agno Knowledge with GeminiEmbedder")

    embedder = GeminiEmbedder(id="gemini-embedding-001", api_key=settings.gemini_api_key)

    # Configura o VectorDB e Knowledge
    vector_db = PgVector(
        table_name=KNOWLEDGE_TABLE,
        db_url=db_url,
        embedder=embedder,
    )

    _KNOWLEDGE_INSTANCE = Knowledge(
        vector_db=vector_db,
    )

    return _KNOWLEDGE_INSTANCE


async def get_agno_knowledge_async() -> Any:
    """Igual a get_agno_knowledge(), mas sem bloquear o event loop na 1ª chamada."""
    if _KNOWLEDGE_INSTANCE is not None:
        return _KNOWLEDGE_INSTANCE
    return await asyncio.to_thread(get_agno_knowledge)


async def search_knowledge(query: str, limit: int = 5, knowledge: Any = None) -> list:
    """Busca documentos relevantes. Devolve lista de agno Document.

    Usa async_search (que o PgVector executa em thread) para não bloquear o
    event loop do FastAPI.
    """
    kb = knowledge or await get_agno_knowledge_async()

    # O nome do método async mudou dentro do próprio 2.x (async_search no 2.2,
    # asearch no 2.8). Resolvemos aqui e caímos no search() síncrono em thread
    # se nenhum dos dois existir — o search() do PgVector é bloqueante.
    for nome in ("asearch", "async_search"):
        metodo = getattr(kb, nome, None)
        if metodo is not None:
            return await metodo(query, max_results=limit)

    return await asyncio.to_thread(kb.search, query, limit)


async def add_knowledge(
    text: str,
    name: str,
    metadata: Optional[dict] = None,
    knowledge: Any = None,
    replace: bool = True,
) -> None:
    """Insere/atualiza um texto na base do Agno.

    O upsert do Agno é por content_hash, não por `name`: reindexar um arquivo
    que MUDOU gera uma linha nova e deixa a antiga para trás, e a busca passa a
    devolver as duas versões. Com replace=True apagamos os vetores daquele
    `name` antes de inserir, então `name` (o caminho do doc) vira a chave real.
    """
    kb = knowledge or await get_agno_knowledge_async()

    if replace:
        try:
            await asyncio.to_thread(kb.remove_vectors_by_name, name)
        except Exception as exc:  # base ainda vazia, name inexistente, etc.
            logger.debug("agno_knowledge.remove_before_add.skipped: %s", exc)

    await kb.add_content_async(
        name=name,
        text_content=text,
        metadata=metadata,
        upsert=True,
        skip_if_exists=True,
    )


def documents_to_texts(docs: Iterable[Any]) -> list[str]:
    """Extrai o texto de uma lista de Documents do Agno, ignorando os vazios."""
    return [d.content for d in docs if getattr(d, "content", None)]
