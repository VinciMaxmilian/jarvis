from __future__ import annotations

import os
from pathlib import Path
from typing import NoReturn

from capabilities.rag_search.schemas import (
    BuscarEntrada,
    ResultadoBusca,
    BuscarSaida,
)
from packages.capabilities import (
    Capability,
    EntradaInvalida,
    PermissaoNaoDeclarada,
    Problema,
    entrypoint,
    permissoes_declaradas,
    tool,
)

DIRETORIO = Path(__file__).resolve().parents[1]


class RagSearch(Capability):
    """Busca conhecimento no repositório de dados."""

    name = "rag_search"
    version = "0.1.0"
    description = "Faz buscas na base de conhecimento (texto) do sistema."
    trigger_intents = (
        "buscar conhecimento",
        "pesquisar nos arquivos de conhecimento",
    )
    runtime = "python"

    def _recusar(self, tool_name: str, campo: str, mensagem: str) -> NoReturn:
        raise EntradaInvalida(
            self.name, tool_name, [Problema(campo=campo, mensagem=mensagem)]
        )

    @tool(
        description="Busca um termo na base de conhecimento e retorna trechos relevantes.",
        entrada=BuscarEntrada,
        saida=BuscarSaida,
        idempotent=True,
    )
    def rag_query(self, entrada: BuscarEntrada) -> BuscarSaida:
        if not self.permissions.filesystem:
            raise PermissaoNaoDeclarada(
                "filesystem", "<raiz de conhecimento>", self.name, "rag_query"
            )
        
        # O manifest irá mapear o filesystem concedido para a pasta knowledge
        knowledge_dir = Path(self.permissions.filesystem[0])
        
        if not knowledge_dir.exists():
            return BuscarSaida(resultados=[], query=entrada.query)

        resultados: list[ResultadoBusca] = []
        termos = entrada.query.lower().split()
        
        try:
            for filepath in knowledge_dir.rglob("*.md"):
                if not filepath.is_file():
                    continue
                conteudo = filepath.read_text(encoding="utf-8", errors="ignore")
                conteudo_lower = conteudo.lower()
                
                # Busca textual básica (fallback para evitar import lancedb em CPU sem AVX)
                if all(t in conteudo_lower for t in termos):
                    linhas = conteudo.splitlines()
                    for idx, linha in enumerate(linhas):
                        if any(t in linha.lower() for t in termos):
                            inicio = max(0, idx - 2)
                            fim = min(len(linhas), idx + 3)
                            trecho = "\\n".join(linhas[inicio:fim])
                            resultados.append(
                                ResultadoBusca(
                                    documento=filepath.name,
                                    trecho=trecho,
                                    score=1.0
                                )
                            )
                            if len(resultados) >= entrada.limite:
                                break
                if len(resultados) >= entrada.limite:
                    break
        except Exception as exc:
            self._recusar("rag_query", "query", f"falha ao ler arquivos: {exc}")

        return BuscarSaida(resultados=resultados, query=entrada.query)


def construir() -> RagSearch:
    return RagSearch(permissoes_declaradas(DIRETORIO))


main = entrypoint(construir)

__all__ = ["DIRETORIO", "RagSearch", "construir", "main"]
