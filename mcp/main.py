import os
import sys
import importlib.util
import inspect
from pathlib import Path

# FIX: Como esta pasta se chama "mcp", o Python tenta importar dela mesma em vez
# da biblioteca oficial 'mcp'. Precisamos remover esta pasta temporariamente do sys.path
_current_dir = str(Path(__file__).parent.resolve())
if _current_dir in sys.path:
    sys.path.remove(_current_dir)
if "" in sys.path:
    sys.path.remove("")

from fastmcp import FastMCP

# Instância central que vai concentrar todas as ferramentas
app = FastMCP("Jarvis-Central-MCP")

def discover_and_register_tools():
    """
    Varre as subpastas em mcp/, carrega o main.py de cada uma e registra
    suas funções como ferramentas neste MCP Central.
    """
    base_dir = Path(__file__).parent
    
    # Adiciona o diretório base ao sys.path para imports funcionarem corretamente
    if str(base_dir.parent) not in sys.path:
        sys.path.insert(0, str(base_dir.parent))

    for folder in base_dir.iterdir():
        # Ignora pastas de cache e arquivos normais
        if folder.is_dir() and not folder.name.startswith((".", "__")):
            main_file = folder / "main.py"
            if main_file.exists():
                module_name = f"mcp.{folder.name}.main"
                
                # Carregamento dinâmico do módulo
                spec = importlib.util.spec_from_file_location(module_name, str(main_file))
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    try:
                        spec.loader.exec_module(module)
                        print(f"Módulo '{folder.name}' carregado.", file=sys.stderr)
                        
                        # Procurar funções definidas dentro deste módulo e registrar no app central
                        for name, obj in inspect.getmembers(module, inspect.isfunction):
                            # Queremos apenas as funções que foram definidas *no próprio arquivo*
                            # e não as que foram importadas (como 'subprocess.run' ou similares)
                            if obj.__module__ == module_name and not name.startswith("_"):
                                try:
                                    # Registra a função como ferramenta no FastMCP central
                                    app.tool()(obj)
                                    print(f"  -> Ferramenta registrada: {name}", file=sys.stderr)
                                except Exception as e:
                                    print(f"  -> Aviso ao registrar ferramenta {name}: {e}", file=sys.stderr)

                    except Exception as e:
                        print(f"Erro ao carregar o módulo '{folder.name}': {e}", file=sys.stderr)

discover_and_register_tools()

if __name__ == "__main__":
    # Rodar o MCP via SSE (HTTP) na porta 8765 (evita conflitos na 8000).
    # Assim o Agente (que está isolado ou na nuvem) pode se conectar na sua máquina!
    # Workaround temporário para um bug na lib fastmcp (qualquer kwarg estava sendo passado para anyio.run)
    import anyio
    async def run_server():
        await app.run_sse_async(port=8765)
    
    anyio.run(run_server)
