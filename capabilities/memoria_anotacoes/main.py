from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any
import uuid

class CapabilityHandler:
    """Handler para a capability de anotações de preferências."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.knowledge_dir = Path(directory).parent.parent / "data" / "knowledge"
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self.scripts_dir = Path(directory).parent.parent / "scripts"

    async def run(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Entrypoint de execução isolado pelo Kernel."""
        if tool != "salvar_preferencia":
            return {"error": f"Tool desconhecida: {tool}"}

        conteudo = arguments.get("conteudo")
        if not conteudo:
            return {"error": "conteudo é obrigatório"}

        # Salva o arquivo em data/knowledge
        # Como o objetivo é anotar informações, vamos usar um UUID ou agrupar num arquivo só
        file_path = self.knowledge_dir / "preferencias_usuario.md"
        
        # Faz append no arquivo de preferências para ir acumulando conhecimentos
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(f"- {conteudo}\n")
            
        # O force_reindex.py força a injeção do LanceDB em realtime
        reindex_script = self.scripts_dir / "force_reindex.py"
        
        if reindex_script.exists():
            # Dispara via subprocesso sincronamente apenas para esperar acabar e retornar sucesso
            # É permitido porque pedimos `subprocess = true` no manifesto
            try:
                # python executable can be called directly
                subprocess.run(
                    ["python", str(reindex_script)],
                    check=True,
                    capture_output=True,
                    text=True
                )
                reindexed = True
            except subprocess.CalledProcessError as exc:
                return {
                    "status": "success mas com falha ao vetorizar",
                    "file_created": str(file_path),
                    "error": exc.stderr
                }
        else:
            reindexed = False

        return {
            "status": "success",
            "file": str(file_path),
            "reindexed_realtime": reindexed
        }

__all__ = ["CapabilityHandler"]
