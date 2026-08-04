"""Executor central de tools do agente.

Implementa ToolExecutor (packages/shared/ports.py) e agrega `web_search` e `search_memory`.
"""

from __future__ import annotations

from typing import Any
import httpx
import asyncio
import structlog
from packages.shared.contracts import ToolSpec
from packages.shared.ports import ToolNotFound, VectorStore
from packages.llm.base import LLMProvider

logger = structlog.get_logger(__name__)

TAVILY_SEARCH_SPEC = ToolSpec(
    name="web_search",
    description=(
        "Busca informações na web usando Tavily. Retorna resultados relevantes "
        "com título, URL e conteúdo resumido. Use quando precisar de informações "
        "atualizadas ou que não estejam na base de conhecimento."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Termo de busca",
            },
            "max_results": {
                "type": "integer",
                "description": "Número máximo de resultados (1-10)",
            },
        },
        "required": ["query"],
    },
    idempotent=True,
    requires_approval=False,
)

SEARCH_MEMORY_SPEC = ToolSpec(
    name="search_memory",
    description=(
        "Busca informações na memória de longo prazo (base de conhecimento com preferências, fatos) "
        "e no histórico de conversas passadas usando busca vetorial semântica. "
        "Sempre use esta ferramenta antes de afirmar que não sabe algo sobre o usuário, seus gostos ou histórico."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Termo de busca semântica para buscar no histórico",
            },
            "limit": {
                "type": "integer",
                "description": "Número máximo de mensagens a recuperar",
            },
        },
        "required": ["query"],
    },
    idempotent=True,
    requires_approval=False,
)

CRIAR_SERVIDOR_MCP_SPEC = ToolSpec(
    name="criar_servidor_mcp",
    description=(
        "Cria um novo servidor MCP (Model Context Protocol) na pasta mcp/ para ensinar uma nova habilidade ao Jarvis. "
        "Use esta ferramenta quando o usuário pedir para você aprender a fazer algo novo ou integrar com uma nova API. "
        "Você DEVE escrever o código completo (em Python) para o arquivo main.py que usará a biblioteca FastMCP."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "nome": {
                "type": "string",
                "description": "Nome da pasta do novo servidor MCP (ex: mcp_clima, nas_smb)"
            },
            "codigo_main_py": {
                "type": "string",
                "description": "O código Python completo para o arquivo main.py usando FastMCP"
            }
        },
        "required": ["nome", "codigo_main_py"]
    },
    idempotent=False,
    requires_approval=True
)

KNOWLEDGE_SAVE_SPEC = ToolSpec(
    name="knowledge_save",
    description=(
        "Grava um fato, preferência ou informação permanente sobre o usuário na base "
        "de conhecimento. Use quando o usuário disser algo sobre si que deva ser lembrado "
        "em conversas futuras (gostos, rotina, decisões, contexto pessoal). "
        "NÃO use para informação efêmera ou para o que já está na base."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "fato": {
                "type": "string",
                "description": "O fato em uma frase, em 3ª pessoa. Ex: 'O usuário gosta de vermelho.'",
            },
            "categoria": {
                "type": "string",
                "description": "Arquivo temático. Ex: preferencias_usuario, comida, trabalho.",
            },
        },
        "required": ["fato"],
    },
    idempotent=False,
    requires_approval=False,
)

KNOWLEDGE_FORGET_SPEC = ToolSpec(
    name="knowledge_forget",
    description=(
        "Remove um fato ou documento inteiro da base de conhecimento usando o seu ID (caminho do arquivo). "
        "Use quando o usuário pedir explicitamente para esquecer alguma informação ou quando "
        "uma informação estiver desatualizada."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "doc_id": {
                "type": "string",
                "description": "O ID do documento a ser removido (ex: o caminho do arquivo retornado na busca ou gravação)."
            },
        },
        "required": ["doc_id"],
    },
    idempotent=True,
    requires_approval=False,
)

ANALYZE_IMAGE_SPEC = ToolSpec(
    name="analyze_image",
    description="Analisa o conteúdo visual de uma imagem a partir de uma URL ou caminho de arquivo local.",
    input_schema={
        "type": "object",
        "properties": {
            "image_url": {"type": "string", "description": "A URL ou caminho local da imagem."}
        },
        "required": ["image_url"],
    },
    idempotent=True,
    requires_approval=False,
)

SAVE_MODIFIED_IMAGE_SPEC = ToolSpec(
    name="save_modified_image",
    description="Aplica filtros (brilho, contraste, saturação) em uma imagem e a salva no backend.",
    input_schema={
        "type": "object",
        "properties": {
            "image_url": {"type": "string", "description": "A URL original da imagem."},
            "brightness": {"type": "number", "description": "Valor de brilho (porcentagem)."},
            "contrast": {"type": "number", "description": "Valor de contraste (porcentagem)."},
            "saturation": {"type": "number", "description": "Valor de saturação (porcentagem)."}
        },
        "required": ["image_url", "brightness", "contrast", "saturation"]
    },
    idempotent=False,
    requires_approval=False,
)

def _as_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, (float, str)):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default
    return default


class SystemToolExecutor:
    """ToolExecutor com as tools do sistema."""

    def __init__(
        self, 
        tavily_api_key: str, 
        llm: LLMProvider, 
        chat_history_store: VectorStore,
        mcp_manager: Any | None = None,
        memory_vector_store: VectorStore | None = None,
        embed_llm: LLMProvider | None = None,
        agno_knowledge=None,
    ) -> None:
        self._tavily_api_key = tavily_api_key
        self._llm = llm
        self._embed_llm = embed_llm or llm
        self._history_store = chat_history_store
        self._mcp_manager = mcp_manager
        self._memory_store = memory_vector_store
        self._agno_knowledge = agno_knowledge
        
        self._tools: dict[str, ToolSpec] = {
            TAVILY_SEARCH_SPEC.name: TAVILY_SEARCH_SPEC,
            SEARCH_MEMORY_SPEC.name: SEARCH_MEMORY_SPEC,
            CRIAR_SERVIDOR_MCP_SPEC.name: CRIAR_SERVIDOR_MCP_SPEC,
            KNOWLEDGE_SAVE_SPEC.name: KNOWLEDGE_SAVE_SPEC,
            KNOWLEDGE_FORGET_SPEC.name: KNOWLEDGE_FORGET_SPEC,
            ANALYZE_IMAGE_SPEC.name: ANALYZE_IMAGE_SPEC,
            SAVE_MODIFIED_IMAGE_SPEC.name: SAVE_MODIFIED_IMAGE_SPEC,
        }

    async def get_all_specs(self) -> list[ToolSpec]:
        """Devolve as specs do sistema e dos MCPs."""
        specs = list(self._tools.values())
        if self._mcp_manager:
            mcp_specs = await self._mcp_manager.get_tools_specs()
            for s in mcp_specs:
                specs.append(ToolSpec(
                    name=s["name"],
                    description=s["description"],
                    input_schema=s["input_schema"],
                    idempotent=False,
                    requires_approval=False
                ))
        return specs

    def specs(self) -> list[ToolSpec]:
        """Síncrono (legado). Apenas system tools."""
        return list(self._tools.values())

    def has(self, name: str) -> bool:
        return name in self._tools

    async def execute(
        self, name: str, arguments: dict[str, object], dry_run: bool = False
    ) -> dict[str, object]:
        if self.has(name):
            if name == "web_search":
                return await self._web_search(
                    query=str(arguments.get("query", "")),
                    max_results=_as_int(arguments.get("max_results"), default=5),
                    dry_run=dry_run,
                )
                
            if name == "search_memory":
                return await self._search_memory(
                    query=str(arguments.get("query", "")),
                    limit=_as_int(arguments.get("limit"), default=5),
                    dry_run=dry_run,
                )
                
            if name == "criar_servidor_mcp":
                return await self._criar_servidor_mcp(
                    nome=str(arguments.get("nome", "")),
                    codigo_main_py=str(arguments.get("codigo_main_py", "")),
                    dry_run=dry_run
                )
                
            if name == "knowledge_save":
                return await self._knowledge_save(
                    fato=str(arguments.get("fato", "")),
                    categoria=str(arguments.get("categoria", "preferencias_usuario")),
                    dry_run=dry_run
                )
                
            if name == "knowledge_forget":
                return await self._knowledge_forget(
                    doc_id=str(arguments.get("doc_id", "")),
                    dry_run=dry_run
                )
                
            if name == "analyze_image":
                return await self._analyze_image(
                    image_url=str(arguments.get("image_url", "")),
                    dry_run=dry_run
                )
                
            if name == "save_modified_image":
                return await self._save_modified_image(
                    image_url=str(arguments.get("image_url", "")),
                    brightness=float(arguments.get("brightness", 100)),
                    contrast=float(arguments.get("contrast", 100)),
                    saturation=float(arguments.get("saturation", 100)),
                    dry_run=dry_run
                )
                
        if self._mcp_manager and name in self._mcp_manager.tool_routes:
            if dry_run:
                return {"dry_run": True, "action": "mcp_call", "tool": name, "args": arguments}
            return await self._mcp_manager.call_tool(name, arguments)

        raise ToolNotFound(name)

    async def _web_search(
        self, query: str, max_results: int = 5, dry_run: bool = False
    ) -> dict[str, object]:
        if dry_run:
            return {
                "dry_run": True,
                "action": "web_search",
                "query": query,
                "max_results": max_results,
            }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self._tavily_api_key,
                    "query": query,
                    "max_results": min(max_results, 10),
                    "include_answer": True,
                    "include_raw_content": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results: list[dict[str, Any]] = []
        for r in data.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
                "score": r.get("score", 0),
            })

        return {
            "answer": data.get("answer", ""),
            "results": results,
            "query": query,
        }

    async def _search_memory(
        self, query: str, limit: int = 5, dry_run: bool = False
    ) -> dict[str, object]:
        if dry_run:
            return {
                "dry_run": True,
                "action": "search_memory",
                "query": query,
                "limit": limit,
            }
            
        try:
            vetores = await self._embed_llm.embed([query])
            
            # Busca no histórico de chat
            matches_history = await self._history_store.search(
                vetores[0], namespace="chat_history", limit=limit
            )
            
            # Busca na base de conhecimento (fatos, preferências)
            results = []
            
            usou_agno = False
            if self._agno_knowledge:
                # Agno 2.x: search(max_results=...), não num_documents=.
                from packages.rag.agno_knowledge import documents_to_texts, search_knowledge

                try:
                    docs = await search_knowledge(
                        query, limit=limit, knowledge=self._agno_knowledge
                    )
                    for texto in documents_to_texts(docs):
                        results.append({
                            "score": 1.0, # Agno abstracts scores by default
                            "text": texto,
                            "date": "",
                            "source": "knowledge_base"
                        })
                    usou_agno = bool(results)
                except Exception as exc:
                    logger.warning("tools.search_memory.agno_failed", error=str(exc))

            if not usou_agno:
                matches_knowledge = []
                if self._memory_store:
                    matches_knowledge = await self._memory_store.search(
                        vetores[0], namespace="knowledge", limit=limit
                    )
                for match in matches_knowledge:
                    results.append({
                        "score": match.score,
                        "text": match.record.text,
                        "date": match.record.metadata.get("updated_at", ""),
                        "source": "knowledge_base"
                    })
                
            for match in matches_history:
                results.append({
                    "score": match.score,
                    "text": match.record.text,
                    "date": match.record.metadata.get("updated_at", ""),
                    "source": "chat_history"
                })
                
            # Ordena por score e pega os top `limit` globais
            results.sort(key=lambda x: x["score"], reverse=True)
            results = results[:limit]
                
            return {
                "query": query,
                "matches": results,
            }
        except Exception as exc:
            return {"error": str(exc)}

    async def _criar_servidor_mcp(self, nome: str, codigo_main_py: str, dry_run: bool = False) -> dict[str, object]:
        if dry_run:
            return {
                "dry_run": True,
                "action": "criar_servidor_mcp",
                "nome": nome,
                "tamanho_codigo": len(codigo_main_py)
            }
            
        try:
            import os
            from pathlib import Path
            mcp_dir = Path(__file__).parent.parent.parent.parent / "mcp" / nome
            mcp_dir.mkdir(parents=True, exist_ok=True)
            
            main_path = mcp_dir / "main.py"
            with open(main_path, "w", encoding="utf-8") as f:
                f.write(codigo_main_py)
                
            # Adiciona um pyproject.toml básico se não existir
            pyproject_path = mcp_dir / "pyproject.toml"
            if not pyproject_path.exists():
                with open(pyproject_path, "w", encoding="utf-8") as f:
                    f.write(f'[project]\nname = "{nome}"\nversion = "0.1.0"\ndependencies = ["mcp"]\n')
                    
            if self._mcp_manager:
                # Dá 3 segundos pro watchfiles no Windows reiniciar o servidor
                await asyncio.sleep(3)
                # Tenta redescobrir imediatamente para conectar
                await self._mcp_manager.refresh()
                
            return {
                "status": "success",
                "message": f"Servidor MCP '{nome}' criado e salvo em {main_path}. Se as dependências estiverem instaladas, as ferramentas já estão disponíveis neste exato momento!"
            }
        except Exception as exc:
            return {"error": str(exc)}

    async def _knowledge_save(
        self, fato: str, categoria: str = "preferencias_usuario", dry_run: bool = False
    ) -> dict[str, object]:
        if dry_run:
            return {
                "dry_run": True,
                "action": "knowledge_save",
                "fato": fato,
                "categoria": categoria,
            }

        # 1. valida + sanitiza categoria
        import re
        import datetime
        from pathlib import Path
        
        categoria = re.sub(r"[^a-z0-9_]", "", categoria.lower())
        if not categoria:
            return {"sucesso": False, "motivo": "Categoria inválida."}
            
        from packages.scheduler.config import SchedulerConfig
        config = SchedulerConfig()
        knowledge_dir = config.knowledge_dir
        
        target_path = (knowledge_dir / f"{categoria}.md").resolve()
        if not str(target_path).startswith(str(knowledge_dir.resolve())):
            return {"sucesso": False, "motivo": "Caminho inválido."}
            
        # 3. dedup barato
        fato_limpo = fato.strip().lower()
        if target_path.exists():
            content = target_path.read_text(encoding="utf-8")
            if fato_limpo in content.lower():
                return {"sucesso": True, "duplicado": True}
                
        # 4. append
        target_path.parent.mkdir(parents=True, exist_ok=True)
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        linha = f"- [{now_str}] {fato.strip()}\n"
        with open(target_path, "a", encoding="utf-8") as f:
            f.write(linha)
            
        texto_inteiro = target_path.read_text(encoding="utf-8")
        doc_id = str(target_path)
        
        # 5. add_knowledge
        try:
            if self._agno_knowledge:
                from packages.rag.agno_knowledge import add_knowledge
                await add_knowledge(
                    text=texto_inteiro,
                    name=doc_id,
                    metadata={"doc_id": doc_id, "source": "knowledge_save"},
                    knowledge=self._agno_knowledge,
                    replace=True
                )
        except Exception as exc:
            logger.warning("knowledge_save.agno_failed", error=str(exc))
            
        # 6. fallback sem Agno
        if self._memory_store:
            try:
                # Import memory updates
                from packages.shared.ports import VectorRecord
                
                pedacos = [texto_inteiro]
                embeddings = await self._embed_llm.embed(pedacos)
                registros = [
                    VectorRecord(
                        id=f"{doc_id}#0",
                        namespace="knowledge",
                        text=texto_inteiro,
                        embedding=list(embeddings[0]),
                        metadata={"doc_id": doc_id, "source": "knowledge_save"}
                    )
                ]
                await self._memory_store.upsert(registros)
            except Exception as exc:
                logger.warning("knowledge_save.memory_store_failed", error=str(exc))

        return {"sucesso": True, "caminho": str(target_path), "categoria": categoria}

    async def _knowledge_forget(
        self, doc_id: str, dry_run: bool = False
    ) -> dict[str, object]:
        if dry_run:
            return {"dry_run": True, "action": "knowledge_forget", "doc_id": doc_id}
            
        try:
            from packages.scheduler.config import SchedulerConfig
            from pathlib import Path
            import os
            config = SchedulerConfig()
            knowledge_dir = config.knowledge_dir
            target_path = Path(doc_id).resolve()
            
            if str(target_path).startswith(str(knowledge_dir.resolve())) and target_path.exists():
                target_path.unlink()
                
            if self._agno_knowledge:
                from packages.rag.agno_knowledge import get_agno_knowledge_async
                import asyncio
                kb = await get_agno_knowledge_async()
                await asyncio.to_thread(kb.remove_vectors_by_name, doc_id)
                
            if self._memory_store:
                # Delete do fallback store
                try:
                    await self._memory_store.delete([f"{doc_id}#0"])
                except Exception:
                    pass
                    
            return {"sucesso": True, "mensagem": f"Documento {doc_id} removido da memória."}
        except Exception as exc:
            return {"error": str(exc)}

    async def _analyze_image(
        self, image_url: str, dry_run: bool = False
    ) -> dict[str, object]:
        if dry_run:
            return {"dry_run": True, "action": "analyze_image", "image_url": image_url}
        # Apenas dizemos que a imagem foi recebida com sucesso.
        # A interface de websocket capturará a chamada da ferramenta para abrir o modal
        return {"sucesso": True, "mensagem": f"Iniciada a análise da imagem {image_url}. A interface foi notificada."}

    async def _save_modified_image(
        self, image_url: str, brightness: float, contrast: float, saturation: float, dry_run: bool = False
    ) -> dict[str, object]:
        if dry_run:
            return {"dry_run": True, "action": "save_modified_image", "image_url": image_url}
            
        try:
            import urllib.request
            from io import BytesIO
            from PIL import Image, ImageEnhance
            import os
            import uuid
            
            # Processa URL ou Base64
            if image_url.startswith("http"):
                req = urllib.request.Request(image_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req) as response:
                    img_data = response.read()
            else:
                if image_url.startswith("data:"):
                    image_url = image_url.split(",")[1]
                import base64
                img_data = base64.b64decode(image_url)
                
            img = Image.open(BytesIO(img_data)).convert('RGBA')
            
            # Aplica filtros
            if brightness != 100:
                enhancer = ImageEnhance.Brightness(img)
                img = enhancer.enhance(brightness / 100.0)
                
            if contrast != 100:
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(contrast / 100.0)
                
            if saturation != 100:
                enhancer = ImageEnhance.Color(img)
                img = enhancer.enhance(saturation / 100.0)
                
            save_dir = os.path.join(os.getcwd(), "data", "images")
            os.makedirs(save_dir, exist_ok=True)
            filename = f"mod_{uuid.uuid4().hex[:8]}.png"
            filepath = os.path.join(save_dir, filename)
            
            img.save(filepath, format="PNG")
            
            return {"sucesso": True, "caminho": filepath, "mensagem": f"Imagem salva em {filepath}"}
        except Exception as exc:
            return {"error": str(exc)}

__all__ = ["SystemToolExecutor", "TAVILY_SEARCH_SPEC", "SEARCH_MEMORY_SPEC", "CRIAR_SERVIDOR_MCP_SPEC", "KNOWLEDGE_SAVE_SPEC", "KNOWLEDGE_FORGET_SPEC", "ANALYZE_IMAGE_SPEC", "SAVE_MODIFIED_IMAGE_SPEC"]
