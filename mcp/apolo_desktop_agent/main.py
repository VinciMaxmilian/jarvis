from fastmcp import FastMCP
import subprocess
import platform

mcp = FastMCP("apolo-desktop-agent")

import webbrowser

@mcp.tool()
def abrir_navegador(url: str = "") -> str:
    """Abre o navegador padrão na máquina local."""
    try:
        target_url = url if url else "https://google.com"
        webbrowser.open(target_url)
        return f"Sucesso! Comando para abrir o navegador (URL: {target_url}) executado."
    except Exception as e:
        return f"Erro ao tentar abrir o navegador: {str(e)}"

@mcp.tool()
def executar_comando_cmd(comando: str) -> str:
    """Executa um comando genérico no terminal/CMD do sistema local."""
    try:
        resultado = subprocess.run(comando, shell=True, capture_output=True, text=True, timeout=10)
        saida = resultado.stdout if resultado.stdout else resultado.stderr
        return f"Saída do comando:\n{saida}"
    except Exception as e:
        return f"Erro ao executar comando: {str(e)}"

if __name__ == "__main__":
    mcp.run()
