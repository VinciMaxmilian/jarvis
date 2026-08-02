from fastmcp import FastMCP
import os
import subprocess
from pathlib import Path

mcp = FastMCP("memoria")

@mcp.tool()
def salvar_preferencia(conteudo: str) -> str:
    """Salva uma preferência ou anotação importante do usuário na memória de longo prazo."""
    # O diretório knowledge fica na raiz do projeto (../../../data/knowledge)
    knowledge_dir = Path(__file__).parent.parent.parent / "data" / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = knowledge_dir / "preferencias_usuario.md"
    
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(f"- {conteudo}\n")
        
    scripts_dir = Path(__file__).parent.parent.parent / "scripts"
    reindex_script = scripts_dir / "force_reindex.py"
    
    reindexed = False
    if reindex_script.exists():
        try:
            subprocess.run(
                ["python", str(reindex_script)],
                check=True,
                capture_output=True,
                text=True
            )
            reindexed = True
        except subprocess.CalledProcessError as exc:
            return f"Anotação salva, mas falhou ao vetorizar: {exc.stderr}"
            
    return f"Anotação salva com sucesso em {file_path}. Vetorizada: {reindexed}"

if __name__ == "__main__":
    mcp.run()
