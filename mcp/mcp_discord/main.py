from fastmcp import FastMCP
import subprocess
import os

mcp = FastMCP("Discord Controller")

@mcp.tool()
def abrir_discord() -> str:
    """Abre o aplicativo do Discord no computador do Senhor."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return "Erro: Não foi possível determinar a pasta LOCALAPPDATA do sistema."
        
    # O Update.exe fica na raiz da pasta do Discord e não muda quando o app atualiza!
    updater_path = os.path.join(local_app_data, "Discord", "Update.exe")
    
    if os.path.exists(updater_path):
        # A flag --processStart fala pro atualizador abrir o Discord
        subprocess.Popen([updater_path, "--processStart", "Discord.exe"])
        return "Discord aberto com sucesso, Senhor."
    else:
        return f"Não encontrei o Discord instalado em: {updater_path}"

if __name__ == "__main__":
    mcp.run()
