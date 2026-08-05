<#
.SYNOPSIS
  Sobe o MCP central no Windows (porta 8765) - e ele que da olhos e maos ao Jarvis.

.DESCRIPTION
  Roda `mcp/main.py`, que carrega todas as pastas de habilidade de `mcp/`,
  incluindo `jarvis_windows_host` (ver tela, clicar, digitar).

  Este processo PRECISA rodar na sessao grafica do Windows, num terminal comum.
  Nao rode como administrador: por UIPI, um processo elevado so controlaria
  janelas elevadas, e o objetivo aqui e justamente o contrario - o agente nao
  encosta em nada que peca UAC.

  O container alcanca este processo por host.docker.internal:8765, que e o que
  packages/mcp/client_manager.py ja procura.

.NOTES
  ENCODING: este arquivo e gravado em UTF-8 COM BOM e quebras CRLF, e nao por
  estetica. O Windows PowerShell 5.1 le .ps1 sem BOM como ANSI (Windows-1252):
  cada caractere acentuado vira dois ou tres bytes interpretados errado, e um
  travessao UTF-8 chega ao parser como uma aspa. O resultado nao e um texto
  feio - e o script inteiro sendo mal interpretado, com strings quebradas e
  variaveis que somem. Ao editar, preserve o BOM.

.EXAMPLE
  .\scripts\run_desktop_host.ps1
#>

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot

Write-Host "== Jarvis - MCP do host Windows ==" -ForegroundColor Cyan

$identidade = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identidade)
if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Warning "Terminal ELEVADO. Rode como usuario comum, senao o agente nao controla suas janelas normais."
}

$python = Join-Path $raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

# Confere as libs de desktop antes de subir: falha aqui e uma linha de texto,
# falha la dentro e uma tool que some do catalogo sem explicacao.
#
# Sem `2>&1`: no PowerShell 5.1, redirecionar stderr de um executavel nativo
# embrulha cada linha num ErrorRecord e derruba $? mesmo com exit code 0.
# O codigo de saida sozinho ja responde a pergunta.
& $python -c "import mss, uiautomation, pyautogui, win32gui" | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Dependencias de desktop faltando ou quebradas."
    Write-Host "Instale com:  uv sync --extra desktop" -ForegroundColor Yellow
    Write-Host "(o servidor sobe mesmo assim, mas sem ver a tela)" -ForegroundColor DarkGray
}

$env:PYTHONPATH = $raiz
if (-not $env:DESKTOP_CONTROL_ENABLED) {
    Write-Host "DESKTOP_CONTROL_ENABLED nao definido -> so PERCEPCAO (ver a tela, sem clicar)." -ForegroundColor Yellow
    Write-Host "Para liberar mouse/teclado: `$env:DESKTOP_CONTROL_ENABLED='true'  antes de rodar." -ForegroundColor DarkGray
}

Write-Host "SSE em http://127.0.0.1:8765/sse  - Ctrl+C para parar." -ForegroundColor Green
Write-Host "ABORTO DE EMERGENCIA: jogue o mouse no canto superior esquerdo da tela." -ForegroundColor Magenta

& $python (Join-Path $raiz "mcp\main.py")
