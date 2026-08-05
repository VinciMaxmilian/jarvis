"""Computer use — o Jarvis vê a tela, clica e digita no Windows do dono.

É o ÚLTIMO RECURSO da hierarquia de ação. Quando existe uma capability, um MCP
dedicado ou um comando, eles vencem: são mais rápidos, determinísticos e não
dependem de o modelo acertar um pixel. Este módulo cobre o resto — o que só
existe atrás de uma interface gráfica.

**Por que aqui e não em `capabilities/`.** A API e o orchestrator rodam em
Docker. Container não tem tela, mouse nem teclado da sessão gráfica do Windows, e
capability do SDK roda sandboxada dentro dele. Este arquivo é carregado pelo
`mcp/main.py`, que sobe no host via SSE em 127.0.0.1:8765 — a mesma porta que
`packages/mcp/client_manager.py` já procurava com o nome `Jarvis-Windows-Host`.
O marcador `HOST_ONLY` ao lado deste arquivo impede o container de tentar subir
uma cópia stdio dele.

**A estratégia é UIA primeiro, pixel depois.** O Windows expõe a árvore de UI
Automation (a mesma dos leitores de tela): nome, tipo e retângulo de cada
controle. Escolher elemento por `id` dessa árvore é determinístico; escolher por
coordenada que o modelo leu de um PNG erra com escala de DPI, com tema e com
qualquer mudança de layout. `desktop_inspecionar` → `desktop_clicar_elemento` é
o caminho principal; `desktop_capturar_tela` → `desktop_clicar` é o fallback
para o que a UIA não enxerga (canvas, Electron mal instrumentado, jogo).

**Nomes de função sem `_` viram tools.** `mcp/main.py` registra toda função
pública deste módulo no MCP central. Helper aqui é obrigatoriamente `_privado`.
"""

from __future__ import annotations

import contextlib
import ctypes
import io
import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


# --------------------------------------------------------------------------- #
# DPI awareness ANTES de qualquer lib de tela.
#
# Sem isto o Windows mente a resolução para processos "não cientes": numa tela
# 2560x1440 a 150%, a API responde 1707x960, o screenshot sai esticado e TODO
# clique cai deslocado — um erro que parece falha de raciocínio do modelo e é
# aritmética do sistema operacional. Tem de rodar antes de `mss` e `pyautogui`
# porque as duas leem a métrica no import.
# --------------------------------------------------------------------------- #
def _ativar_dpi_awareness() -> str:
    try:
        # PER_MONITOR_AWARE_V2 (-4): o único modo correto com monitores de
        # escalas diferentes, que é o caso de notebook + monitor externo.
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
        return "per_monitor_v2"
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return "per_monitor"
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        return "system"
    except Exception:
        return "nenhum"


_MODO_DPI = _ativar_dpi_awareness() if os.name == "nt" else "nao_windows"


# --------------------------------------------------------------------------- #
# Imports moles.
#
# Falha de import aqui NÃO pode derrubar o módulo: `mcp/main.py` carrega cada
# pasta dentro de um try e um ImportError levaria embora as tools de percepção
# junto com as de ação. Cada lib ausente vira uma mensagem de erro que o modelo
# lê e repassa ao dono ("falta instalar X"), em vez de um servidor que some.
# --------------------------------------------------------------------------- #
def _tentar_importar(nome: str) -> tuple[Any, str]:
    try:
        return __import__(nome), ""
    except Exception as exc:  # noqa: BLE001 — qualquer falha vira diagnóstico
        return None, f"{nome}: {exc}"


_mss, _ERRO_MSS = _tentar_importar("mss")
_uia, _ERRO_UIA = _tentar_importar("uiautomation")
_pyautogui, _ERRO_PYAUTOGUI = _tentar_importar("pyautogui")
_win32gui, _ERRO_WIN32 = _tentar_importar("win32gui")

try:
    from PIL import Image as _PILImage
    from PIL import ImageDraw as _PILDraw

    _ERRO_PIL = ""
except Exception as exc:  # noqa: BLE001
    _PILImage = _PILDraw = None  # type: ignore[assignment]
    _ERRO_PIL = f"Pillow: {exc}"

try:
    from fastmcp.utilities.types import Image as _MCPImage

    _ERRO_FASTMCP = ""
except Exception as exc:  # noqa: BLE001
    _MCPImage = None  # type: ignore[assignment]
    _ERRO_FASTMCP = f"fastmcp: {exc}"

if _pyautogui is not None:
    # Failsafe: jogar o mouse no canto superior esquerdo aborta a ação em curso.
    # É a única trava que o dono aciona com o corpo, sem depender de o software
    # estar são. Não desligar.
    _pyautogui.FAILSAFE = True
    # A pausa entre ações é nossa (`_INTERVALO_MIN_MS`), não da lib.
    _pyautogui.PAUSE = 0


# --------------------------------------------------------------------------- #
# Configuração
# --------------------------------------------------------------------------- #

_RAIZ = Path(__file__).resolve().parents[2]


def _env(nome: str, padrao: str) -> str:
    return os.environ.get(nome, padrao).strip()


def _env_bool(nome: str, padrao: bool = False) -> bool:
    return _env(nome, "true" if padrao else "false").lower() in {
        "1",
        "true",
        "yes",
        "sim",
    }


def _env_int(nome: str, padrao: int) -> int:
    try:
        return int(_env(nome, str(padrao)))
    except ValueError:
        return padrao


#: Interruptor mestre. Desligado, só as tools de percepção respondem.
#: Só o dono liga, editando o `.env` e reiniciando o host — é de propósito que o
#: modelo não tenha caminho nenhum para virar esta chave.
def _controle_habilitado() -> bool:
    return _env_bool("DESKTOP_CONTROL_ENABLED", False)


_DIR_AUDIT = Path(_env("DESKTOP_AUDIT_DIR", str(_RAIZ / "data" / "desktop_audit")))
_ARQ_DENYLIST = Path(
    _env("DESKTOP_DENYLIST", str(_RAIZ / "data" / "desktop_denylist.json"))
)
_LARGURA_MAX = _env_int("DESKTOP_LARGURA_MAX", 1280)
_INTERVALO_MIN_MS = _env_int("DESKTOP_INTERVALO_MIN_MS", 250)
_MAX_ACOES_SESSAO = _env_int("DESKTOP_MAX_ACOES_SESSAO", 200)
_SESSAO_MAX_MIN = _env_int("DESKTOP_SESSAO_MAX_MIN", 30)

#: Janelas que o agente nunca toca, nem para olhar de perto. Semente mínima; o
#: dono amplia conversando (`desktop_bloquear_janela`), e a lista mora em disco
#: para sobreviver ao restart do host.
_DENYLIST_PADRAO: list[dict[str, str]] = [
    {
        "padrao": r"(?i)\b(bitwarden|1password|lastpass|keepass|dashlane)\b",
        "motivo": "gerenciador de senhas",
    },
    {
        "padrao": r"(?i)\b(internet banking|banco do brasil|itau|itaú"
        r"|bradesco|santander|nubank|caixa)\b",
        "motivo": "banco",
    },
    {
        "padrao": r"(?i)(controle de conta de usu|user account control)",
        "motivo": "UAC — elevação não é para o agente",
    },
    {
        "padrao": r"(?i)\b(mstsc|conexão de área de trabalho remota|remote desktop)\b",
        "motivo": "sessão remota de terceiro",
    },
]

#: Nome de controle que sugere ação sem volta. Não bloqueia: exige que o modelo
#: passe `confirmado=True`, e o texto da recusa manda ele perguntar ao dono
#: antes. É atrito deliberado no lugar exato onde o erro é caro.
_RE_DESTRUTIVO = re.compile(
    r"(?i)\b(excluir|apagar|deletar|delete|remover|remove|formatar|format|"
    r"desinstalar|uninstall|comprar|compra|pagar|pagamento|finalizar pedido|"
    r"transferir|enviar dinheiro|encerrar conta|redefinir|reset|restaurar padr)"
)

#: Texto que não deve sair pelo teclado do agente em hipótese alguma.
_RE_SEGREDO = re.compile(
    r"(?i)(senha\s*[:=]|password\s*[:=]|api[_-]?key\s*[:=]|secret\s*[:=]|"
    r"token\s*[:=]|-----BEGIN [A-Z ]*PRIVATE KEY)"
)

#: Alvo de `desktop_abrir` que nunca abre, com ou sem confirmação.
_RE_ALVO_PROIBIDO = re.compile(
    r"(?i)\b(diskpart|format\s|cipher\s*/w|vssadmin\s+delete|bcdedit|"
    r"powershell.*-enc|reg\s+delete|rd\s+/s|rmdir\s+/s|del\s+/[qsf])"
)

_TIPOS_INTERATIVOS = frozenset(
    {
        "ButtonControl",
        "EditControl",
        "ComboBoxControl",
        "CheckBoxControl",
        "RadioButtonControl",
        "MenuItemControl",
        "ListItemControl",
        "TabItemControl",
        "HyperlinkControl",
        "SliderControl",
        "TreeItemControl",
        "SplitButtonControl",
        "ThumbControl",
        "DocumentControl",
    }
)

_TECLAS_PERMITIDAS = frozenset(
    {
        "enter",
        "return",
        "tab",
        "esc",
        "escape",
        "space",
        "backspace",
        "delete",
        "up",
        "down",
        "left",
        "right",
        "home",
        "end",
        "pageup",
        "pagedown",
        "ctrl",
        "ctrlleft",
        "ctrlright",
        "alt",
        "altleft",
        "altright",
        "shift",
        "shiftleft",
        "shiftright",
        "win",
        "winleft",
        "winright",
        "f1",
        "f2",
        "f3",
        "f4",
        "f5",
        "f6",
        "f7",
        "f8",
        "f9",
        "f10",
        "f11",
        "f12",
        "insert",
        "printscreen",
        "capslock",
        *(chr(c) for c in range(ord("a"), ord("z") + 1)),
        *(str(d) for d in range(10)),
    }
)


# --------------------------------------------------------------------------- #
# Estado da sessão (processo único, host único — memória basta)
# --------------------------------------------------------------------------- #

_SESSAO_ATE: float = 0.0
_SESSAO_MOTIVO: str = ""
_ACOES_NA_SESSAO: int = 0
_ULTIMA_ACAO: float = 0.0

#: Índice da última inspeção: `id` → dados do elemento. É o que dá sentido ao
#: `desktop_clicar_elemento("e12")`. Reconstruído a cada `desktop_inspecionar`.
_ELEMENTOS: dict[str, dict[str, Any]] = {}
_ELEMENTOS_EM: float = 0.0

#: Escala da última captura, para converter coordenada do espaço da imagem de
#: volta para pixel real. O modelo NUNCA faz essa conta — ela mora aqui.
_ULTIMA_ESCALA: float = 1.0
_ULTIMO_OFFSET: tuple[int, int] = (0, 0)


# --------------------------------------------------------------------------- #
# Helpers — nada aqui vira tool
# --------------------------------------------------------------------------- #


def _agora_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _erro(mensagem: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "erro": mensagem, **extra}


def _carregar_denylist() -> list[dict[str, str]]:
    if not _ARQ_DENYLIST.exists():
        return list(_DENYLIST_PADRAO)
    try:
        dados = json.loads(_ARQ_DENYLIST.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — arquivo corrompido não desarma a trava
        return list(_DENYLIST_PADRAO)
    if not isinstance(dados, list):
        return list(_DENYLIST_PADRAO)
    # A semente SEMPRE volta junto. Um arquivo editado à mão (ou um agente
    # criativo) não pode remover a proteção de banco e gerenciador de senha.
    return [
        *_DENYLIST_PADRAO,
        *(d for d in dados if isinstance(d, dict) and d.get("padrao")),
    ]


def _salvar_denylist(itens: list[dict[str, str]]) -> None:
    _ARQ_DENYLIST.parent.mkdir(parents=True, exist_ok=True)
    proprios = [i for i in itens if i not in _DENYLIST_PADRAO]
    _ARQ_DENYLIST.write_text(
        json.dumps(proprios, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _titulo_bloqueado(titulo: str) -> str:
    for item in _carregar_denylist():
        try:
            if re.search(item["padrao"], titulo or ""):
                return item.get("motivo", "na lista de bloqueio")
        except re.error:
            continue
    return ""


def _janela_ativa() -> tuple[int, str]:
    if _win32gui is None:
        return 0, ""
    try:
        hwnd = _win32gui.GetForegroundWindow()
        return int(hwnd), str(_win32gui.GetWindowText(hwnd))
    except Exception:  # noqa: BLE001
        return 0, ""


def _registrar_auditoria(
    acao: str, detalhes: dict[str, Any], png: bytes | None = None
) -> None:
    """Trilha em disco. Sem ela, "por que meu arquivo sumiu?" não tem resposta."""
    try:
        dia = datetime.now().strftime("%Y-%m-%d")
        pasta = _DIR_AUDIT / dia
        pasta.mkdir(parents=True, exist_ok=True)
        carimbo = datetime.now().strftime("%H%M%S_%f")[:-3]
        # `acao` por ÚLTIMO, e não por primeiro: com `{"acao": acao, **detalhes}`
        # um detalhe chamado "acao" sobrescrevia o nome do evento. Era o caso de
        # `_exigir_sessao`, que registra `{"acao": "clicar"}` ao RECUSAR — e a
        # trilha gravava o clique bloqueado como se ele tivesse acontecido.
        # Auditoria que mente sobre o que foi barrado é pior que auditoria
        # nenhuma: ela acusa o agente de algo que ele não fez.
        linha = {"em": _agora_iso(), **detalhes, "acao": acao}
        if png:
            arquivo = pasta / f"{carimbo}_{acao}.png"
            arquivo.write_bytes(png)
            linha["captura"] = str(arquivo)
        with (pasta / "auditoria.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(linha, ensure_ascii=False, default=str) + "\n")
    except Exception:  # noqa: BLE001 — auditoria nunca derruba a ação
        pass


def _exigir_sessao(acao: str) -> dict[str, Any] | None:
    """Porta única de toda tool de ação. `None` = pode seguir."""
    global _ULTIMA_ACAO, _ACOES_NA_SESSAO

    if os.name != "nt":
        return _erro("este servidor só controla Windows.")
    if _pyautogui is None:
        return _erro(
            f"teclado/mouse indisponível ({_ERRO_PYAUTOGUI}). "
            "Instale: uv sync --extra desktop"
        )
    if not _controle_habilitado():
        return _erro(
            "controle de mouse e teclado DESLIGADO. O dono precisa colocar "
            "DESKTOP_CONTROL_ENABLED=true no .env e reiniciar o host. "
            "Diga isso a ele — você não tem como ligar."
        )
    if time.time() > _SESSAO_ATE:
        return _erro(
            "nenhuma sessão de controle ativa. PERGUNTE AO DONO se ele autoriza, "
            "e só então chame desktop_liberar_controle(minutos, motivo).",
            sessao_ativa=False,
        )
    if _ACOES_NA_SESSAO >= _MAX_ACOES_SESSAO:
        return _erro(
            f"teto de {_MAX_ACOES_SESSAO} ações desta sessão atingido. "
            "Pare, explique ao dono o que conseguiu fazer e peça nova liberação."
        )

    _, titulo = _janela_ativa()
    if motivo := _titulo_bloqueado(titulo):
        _registrar_auditoria(
            "bloqueado", {"tentativa": acao, "janela": titulo, "motivo": motivo}
        )
        return _erro(
            f"a janela em foco ({titulo!r}) está na lista de bloqueio: {motivo}. "
            "Nenhuma ação passa enquanto ela estiver na frente.",
            janela=titulo,
        )

    # Rate limit: o intervalo mínimo existe para que um laço maluco não faça 400
    # cliques antes de alguém perceber. Dormir é mais simples que recusar — a
    # ação sai, só que devagar o bastante para ser interrompível.
    espera = (_ULTIMA_ACAO + _INTERVALO_MIN_MS / 1000) - time.time()
    if espera > 0:
        time.sleep(min(espera, 2.0))

    _ULTIMA_ACAO = time.time()
    _ACOES_NA_SESSAO += 1
    return None


def _janela_minimizada(handle: int) -> bool:
    """`True` se a janela está minimizada. `handle=0` (foreground) nunca está."""
    if not handle or _win32gui is None:
        return False
    try:
        return bool(_win32gui.IsIconic(handle))
    except Exception:  # noqa: BLE001
        return False


def _para_tela(x: int, y: int, espaco: str) -> tuple[int, int]:
    """Coordenada do modelo → pixel real do monitor.

    Existe uma vez só porque três tools (`clicar`, `arrastar`, `rolar`) recebem
    ponto do modelo, e uma delas esquecer a conversão é um bug que só aparece
    numa tela de resolução diferente da de quem testou.
    """
    if espaco == "tela" or not _ULTIMA_ESCALA:
        return int(x), int(y)
    return (
        int(x / _ULTIMA_ESCALA) + _ULTIMO_OFFSET[0],
        int(y / _ULTIMA_ESCALA) + _ULTIMO_OFFSET[1],
    )


@contextlib.contextmanager
def _com_na_thread() -> Any:
    """Garante `CoInitialize` na thread que está atendendo esta chamada.

    A UI Automation é COM, e COM é inicializado POR THREAD. O módulo é importado
    uma vez, na thread principal, mas o FastMCP atende cada requisição numa
    thread do pool — que nasce sem COM. O sintoma observado em produção foi
    `[WinError -2147221008] CoInitialize não foi chamado` vindo de
    `desktop_inspecionar`, enquanto os mesmos comandos rodavam sem erro num
    script de teste (thread única, COM inicializado no import).

    `UIAutomationInitializerInThread` é da própria lib e faz init/uninit em par.
    O fallback direto no `comtypes` existe porque a alternativa — falhar aqui —
    devolveria de novo o erro que este bloco veio consertar.
    """
    if _uia is not None and hasattr(_uia, "UIAutomationInitializerInThread"):
        with _uia.UIAutomationInitializerInThread(debug=False):
            yield
        return
    try:
        import comtypes

        comtypes.CoInitialize()
    except Exception:  # noqa: BLE001 — thread que já tem COM levanta aqui
        pass
    yield


def _escolher_area(sct: Any, monitor: int) -> dict[str, int]:
    """Qual retângulo capturar.

    O default (`0`) é a tela onde está a janela em foco, e não a união de todas
    — medido nesta máquina: dois monitores viram 4480x1081, que reduzidos ao
    limite de largura viram uma tira de 1280x308 onde nenhum texto de interface
    é legível. Capturar a tela certa é o que faz a diferença entre o modelo ler
    um botão e o modelo chutar.
    """
    # `monitors[0]` é o espaço virtual (todas as telas), mesmo sistema de
    # coordenadas do mouse. `monitors[1..N]` são as físicas.
    if monitor > 0:
        return sct.monitors[monitor if monitor < len(sct.monitors) else 1]
    if monitor < 0:
        return sct.monitors[0]

    if _win32gui is not None:
        try:
            esq, topo, dir_, baixo = _win32gui.GetWindowRect(
                _win32gui.GetForegroundWindow()
            )
            cx, cy = (esq + dir_) // 2, (topo + baixo) // 2
            for fisico in sct.monitors[1:]:
                if (
                    fisico["left"] <= cx < fisico["left"] + fisico["width"]
                    and fisico["top"] <= cy < fisico["top"] + fisico["height"]
                ):
                    return fisico
        except Exception:  # noqa: BLE001
            pass
    return sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]


def _capturar_png(
    monitor: int = 0, regiao: list[int] | None = None
) -> tuple[bytes, dict[str, Any]]:
    """PNG reduzido + metadados de escala. Levanta se `mss`/PIL faltarem."""
    global _ULTIMA_ESCALA, _ULTIMO_OFFSET

    if _mss is None:
        raise RuntimeError(f"captura indisponível ({_ERRO_MSS})")
    if _PILImage is None:
        raise RuntimeError(f"captura indisponível ({_ERRO_PIL})")

    with _mss.mss() as sct:
        area = _escolher_area(sct, monitor)
        if regiao and len(regiao) == 4:
            x, y, w, h = regiao
            area = {"left": int(x), "top": int(y), "width": int(w), "height": int(h)}
        bruto = sct.grab(area)

    img = _PILImage.frombytes("RGB", bruto.size, bruto.bgra, "raw", "BGRX")
    largura_real, altura_real = img.size

    escala = 1.0
    if largura_real > _LARGURA_MAX:
        escala = _LARGURA_MAX / largura_real
        img = img.resize((_LARGURA_MAX, max(1, int(altura_real * escala))))

    _ULTIMA_ESCALA = escala
    _ULTIMO_OFFSET = (int(area["left"]), int(area["top"]))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    meta = {
        "resolucao_real": [largura_real, altura_real],
        "resolucao_imagem": list(img.size),
        "escala": round(escala, 4),
        "offset": list(_ULTIMO_OFFSET),
        "modo_dpi": _MODO_DPI,
    }
    return buf.getvalue(), meta


def _coletar_elementos(
    hwnd: int | None, profundidade: int, so_interativos: bool
) -> list[dict[str, Any]]:
    """Árvore UIA achatada em lista, com COM inicializado na thread da chamada."""
    with _com_na_thread():
        return _coletar_elementos_raw(hwnd, profundidade, so_interativos)


def _coletar_elementos_raw(
    hwnd: int | None, profundidade: int, so_interativos: bool
) -> list[dict[str, Any]]:
    """A varredura em si. É a percepção barata — texto, não pixel."""
    global _ELEMENTOS, _ELEMENTOS_EM

    if _uia is None:
        raise RuntimeError(f"UI Automation indisponível ({_ERRO_UIA})")

    raiz = _uia.ControlFromHandle(hwnd) if hwnd else _uia.GetForegroundControl()
    if raiz is None:
        raiz = _uia.GetRootControl()

    achados: list[dict[str, Any]] = []
    indice = 0
    for controle, _prof in _uia.WalkControl(raiz, includeTop=True, maxDepth=profundidade):
        try:
            tipo = controle.ControlTypeName
            if so_interativos and tipo not in _TIPOS_INTERATIVOS:
                continue
            if controle.IsOffscreen:
                continue
            r = controle.BoundingRectangle
            larg, alt = r.right - r.left, r.bottom - r.top
            if larg <= 0 or alt <= 0:
                continue
            nome = (controle.Name or "").strip()
            auto_id = (controle.AutomationId or "").strip()
            if so_interativos and not nome and not auto_id:
                # Controle interativo sem rótulo nenhum não é escolhível pelo
                # modelo e só polui a lista.
                continue
            indice += 1
            item = {
                "id": f"e{indice}",
                "nome": nome[:120],
                "tipo": tipo.replace("Control", ""),
                "automation_id": auto_id[:60],
                "rect": [r.left, r.top, r.right, r.bottom],
                "centro_tela": [r.left + larg // 2, r.top + alt // 2],
                "habilitado": bool(controle.IsEnabled),
            }
            achados.append(item)
            if indice >= 200:
                break
        except Exception:  # noqa: BLE001 — controle que some no meio da varredura
            continue

    _ELEMENTOS = {i["id"]: i for i in achados}
    _ELEMENTOS_EM = time.time()
    return achados


def _marcar(
    png: bytes, elementos: list[dict[str, Any]], escala: float, offset: tuple[int, int]
) -> bytes:
    """Set-of-Mark: caixas numeradas sobre os elementos UIA.

    Muda a pergunta feita ao modelo de "em que pixel eu clico?" (que ele erra)
    para "qual número eu escolho?" (que ele acerta). O número desenhado é o
    mesmo `id` devolvido em `desktop_inspecionar`.
    """
    if _PILImage is None or _PILDraw is None or not elementos:
        return png
    try:
        img = _PILImage.open(io.BytesIO(png)).convert("RGB")
        desenho = _PILDraw.Draw(img)
        for elemento in elementos[:60]:
            x1, y1, x2, y2 = elemento["rect"]
            x1 = int((x1 - offset[0]) * escala)
            y1 = int((y1 - offset[1]) * escala)
            x2 = int((x2 - offset[0]) * escala)
            y2 = int((y2 - offset[1]) * escala)
            if x2 <= x1 or y2 <= y1:
                continue
            desenho.rectangle([x1, y1, x2, y2], outline=(255, 0, 0), width=2)
            etiqueta = elemento["id"]
            lx, ly = x1, max(0, y1 - 14)
            desenho.rectangle(
                [lx, ly, lx + 8 * len(etiqueta) + 4, ly + 14], fill=(255, 0, 0)
            )
            desenho.text((lx + 2, ly + 1), etiqueta, fill=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception:  # noqa: BLE001 — marcação é enfeite, captura é o produto
        return png


def _imagem_mcp(png: bytes) -> Any:
    """PNG → bloco de imagem do MCP, que `client_manager.call_tool` extrai."""
    if _MCPImage is None:
        return None
    return _MCPImage(data=png, format="png")


def _conferencia(acao: str, detalhes: dict[str, Any], conferir: bool) -> Any:
    """Resposta padrão de toda tool de ação: o que fiz + como ficou a tela."""
    corpo: dict[str, Any] = {"ok": True, "acao": acao, **detalhes}
    png = None
    if conferir:
        try:
            time.sleep(0.35)  # deixa a UI repintar antes de fotografar
            png, meta = _capturar_png()
            corpo["tela"] = meta
        except Exception as exc:  # noqa: BLE001
            corpo["aviso_captura"] = str(exc)
    _registrar_auditoria(acao, detalhes, png)
    if png and (bloco := _imagem_mcp(png)):
        return [corpo, bloco]
    return corpo


def _definir_clipboard(texto: str) -> bool:
    try:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(texto, win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
        return True
    except Exception:  # noqa: BLE001
        return False


def _campo_de_senha() -> bool | None:
    """`True`/`False`/`None` quando não deu para saber.

    `None` é uma resposta honesta e importante: mentir `False` daria confiança
    falsa a quem chama. Quem consome trata o desconhecido como suspeito.
    """
    if _uia is None:
        return None
    try:
        with _com_na_thread():
            foco = _uia.GetFocusedControl()
            if foco is None:
                return None
            for atributo in ("IsPassword", "IsPasswordProperty"):
                valor = getattr(foco, atributo, None)
                if isinstance(valor, bool):
                    return valor
            prop = getattr(_uia, "PropertyId", None)
            pid = getattr(prop, "IsPasswordProperty", None) if prop else None
            if pid is not None:
                return bool(foco.GetPropertyValue(pid))
    except Exception:  # noqa: BLE001
        return None
    return None


# --------------------------------------------------------------------------- #
# TOOLS — percepção
# --------------------------------------------------------------------------- #


def desktop_status() -> dict[str, Any]:
    """Diz se o Jarvis pode ver e controlar esta máquina, e o que falta.

    Chame ANTES de tentar clicar em qualquer coisa pela primeira vez: a resposta
    diz se o controle está ligado, se há sessão ativa e quantas ações restam.
    """
    faltando = [
        e for e in (_ERRO_MSS, _ERRO_UIA, _ERRO_PYAUTOGUI, _ERRO_PIL, _ERRO_WIN32) if e
    ]
    restante = max(0.0, _SESSAO_ATE - time.time())
    return {
        "ok": True,
        "sistema": os.name,
        "modo_dpi": _MODO_DPI,
        "percepcao_disponivel": _mss is not None and _PILImage is not None,
        "uia_disponivel": _uia is not None,
        "controle_habilitado": _controle_habilitado(),
        "sessao_ativa": restante > 0,
        "sessao_segundos_restantes": int(restante),
        "sessao_motivo": _SESSAO_MOTIVO,
        "acoes_usadas": _ACOES_NA_SESSAO,
        "acoes_maximo": _MAX_ACOES_SESSAO,
        "dependencias_faltando": faltando,
        "bloqueios_ativos": len(_carregar_denylist()),
    }


def desktop_listar_janelas(so_visiveis: bool = True) -> dict[str, Any]:
    """Lista as janelas abertas no Windows, com título e handle.

    Primeiro passo barato: descobrir se o programa já está aberto antes de
    abrir outro. Devolve `handle` para usar em desktop_focar_janela e
    desktop_inspecionar.
    """
    if _win32gui is None:
        return _erro(f"listagem indisponível ({_ERRO_WIN32})")

    janelas: list[dict[str, Any]] = []
    frente, _ = _janela_ativa()

    def _visitar(hwnd: int, _: Any) -> bool:
        try:
            if so_visiveis and not _win32gui.IsWindowVisible(hwnd):
                return True
            titulo = _win32gui.GetWindowText(hwnd)
            if not titulo.strip():
                return True
            r = _win32gui.GetWindowRect(hwnd)
            janelas.append(
                {
                    "handle": int(hwnd),
                    "titulo": titulo[:120],
                    "rect": list(r),
                    "em_foco": hwnd == frente,
                    "bloqueada": bool(_titulo_bloqueado(titulo)),
                }
            )
        except Exception:  # noqa: BLE001
            pass
        return True

    try:
        _win32gui.EnumWindows(_visitar, None)
    except Exception as exc:  # noqa: BLE001
        return _erro(f"falha ao enumerar janelas: {exc}")

    return {"ok": True, "total": len(janelas), "janelas": janelas}


def desktop_inspecionar(
    handle: int = 0,
    profundidade: int = 12,
    so_interativos: bool = True,
) -> dict[str, Any]:
    """Lê a árvore de acessibilidade (UI Automation) da janela e lista os controles.

    ESTE É O CAMINHO PREFERIDO para agir numa interface, antes de qualquer
    screenshot: devolve nome, tipo e posição de cada botão, campo e menu, cada um
    com um `id`. Use o `id` em desktop_clicar_elemento ou desktop_preencher_campo.
    É mais rápido, mais barato e MUITO mais confiável que clicar por coordenada.

    handle: janela a inspecionar (0 = a que está em foco).
    so_interativos: só o que dá para clicar/editar. False traz também textos.
    """
    if _uia is None:
        return _erro(
            f"UI Automation indisponível ({_ERRO_UIA}). Instale: uv sync --extra desktop"
        )

    _, titulo = _janela_ativa()
    if handle and _win32gui is not None:
        with contextlib.suppress(Exception):
            titulo = _win32gui.GetWindowText(handle)
    if motivo := _titulo_bloqueado(titulo):
        return _erro(
            f"janela {titulo!r} bloqueada ({motivo}); não inspeciono o conteúdo dela."
        )

    try:
        elementos = _coletar_elementos(
            handle or None, max(1, min(profundidade, 30)), so_interativos
        )
    except Exception as exc:  # noqa: BLE001
        return _erro(f"falha ao ler a árvore de UI: {exc}")

    resposta: dict[str, Any] = {
        "ok": True,
        "janela": titulo,
        "total": len(elementos),
        "elementos": elementos,
        "dica": "clique por id (desktop_clicar_elemento), não por coordenada.",
    }

    # App Electron/WebView2 (Teams, Discord, VS Code, Slack) não expõe a árvore
    # interna para a UI Automation: o conteúdo inteiro chega como UM nó
    # `Document` sem nome, e o resto é a moldura da janela. Sem este aviso a
    # resposta parece uma inspeção bem-sucedida de uma tela quase vazia, e o
    # modelo conclui que os controles não existem — foi o que aconteceu com o
    # Teams, onde ele desistiu dos ids e passou a chutar pixel.
    #
    # O limiar é 6 e não 3 porque a moldura sozinha já rende 4 nós no Teams
    # (a aba, "Fechar guia", "Nova Guia" e o menu "Sistema") — medido. E o
    # `total == 0` entra junto: o Discord devolveu ZERO elementos, que é o caso
    # mais cego de todos e não tinha nem `Document` para casar na condição
    # anterior. Uma janela de aplicativo de verdade rende dezenas de nós; menos
    # que isso quer dizer que não estamos vendo o conteúdo, não que ele é vazio.
    _moldura = {"Document", "Pane", "Window"}
    interativos = [e for e in elementos if e["tipo"] not in _moldura]
    if len(interativos) <= 6:
        # Duas causas diferentes produzem a mesma lista curta, e a ação correta
        # para cada uma é oposta. Janela minimizada precisa ser trazida à frente
        # (screenshot dela não existe); janela cega precisa de screenshot (focar
        # não revela nada). Um aviso único mandaria o modelo para o lado errado
        # em metade dos casos.
        if _janela_minimizada(handle):
            resposta["aviso"] = (
                "esta janela está MINIMIZADA — por isso a lista veio vazia. Ela "
                "não está vazia de verdade. Chame desktop_focar_janela com este "
                "handle e inspecione de novo."
            )
            resposta["dica"] = "desktop_focar_janela primeiro, depois inspecione."
        else:
            resposta["aviso"] = (
                "esta janela NÃO expõe seus controles para a acessibilidade "
                "(típico de Electron/WebView2 — Teams, Discord, Slack, VS Code, "
                "Cursor). O que veio acima é só a moldura, não o conteúdo. Não "
                "conclua que a tela está vazia."
            )
            resposta["dica"] = (
                "aqui o caminho é desktop_capturar_tela e depois desktop_clicar "
                "com as coordenadas lidas NA IMAGEM — espaco='captura', que já é "
                "o padrão. Não converta nada você mesmo."
            )
    return resposta


def desktop_capturar_tela(
    monitor: int = 0,
    marcar_elementos: bool = False,
    regiao: list[int] | None = None,
    janela: int = 0,
) -> Any:
    """Tira um screenshot e devolve a imagem para você olhar.

    Use quando desktop_inspecionar não enxergar o que você precisa (conteúdo em
    canvas, jogo, app sem acessibilidade) ou quando precisar CONFERIR o efeito
    de uma ação. Para decidir onde clicar, prefira desktop_inspecionar.

    ATENÇÃO À ESCALA. A imagem é REDUZIDA antes de chegar até você, e a resposta
    diz quanto (`escala`). Com `escala` 0.5, cada linha de uma lista tem uns 20
    pixels na sua imagem e o texto fica no limite do ilegível — é assim que se
    clica na conversa errada. Se precisar LER algo para escolher, capture de
    novo com `janela` ou `regiao`: área menor significa menos redução, e abaixo de
    1280px de largura não há redução nenhuma.

    monitor: 0 (padrão) = a tela onde está a janela em foco. 1, 2... = uma tela
        específica. -1 = todas juntas, mas aí a redução é a pior possível.
    janela: handle de desktop_listar_janelas. Captura só aquela janela, com
        menos redução que a tela inteira. Prefira isto ao capturar um app.
    regiao: [x, y, largura, altura] em pixels REAIS. É o recorte mais preciso —
        use para ler texto pequeno, como o nome de um item numa lista.
    marcar_elementos: desenha caixas numeradas (e1, e2...) sobre os controles
        detectados — depois é só chamar desktop_clicar_elemento com o número.
    """
    if janela and not regiao and _win32gui is not None:
        try:
            esq, topo, dir_, baixo = _win32gui.GetWindowRect(janela)
            regiao = [esq, topo, dir_ - esq, baixo - topo]
        except Exception as exc:  # noqa: BLE001
            return _erro(f"handle de janela inválido: {exc}")

    try:
        png, meta = _capturar_png(monitor, regiao)
    except Exception as exc:  # noqa: BLE001
        return _erro(str(exc))

    corpo: dict[str, Any] = {"ok": True, **meta}
    # O aviso é acionado pela ESCALA e não pelo tamanho da tela, porque é a
    # escala que define se o texto sobreviveu. Sem ele o modelo não tem como
    # saber que está olhando uma imagem degradada — ela parece nítida para quem
    # não viu o original — e escolhe a linha errada com total confiança.
    if meta["escala"] < 0.7:
        corpo["aviso_legibilidade"] = (
            f"esta imagem foi reduzida a {int(meta['escala'] * 100)}% do tamanho "
            "real. Texto pequeno (nome em lista, item de menu) pode estar "
            "ilegível. Se você precisa LER algo para decidir onde clicar, chame "
            "de novo com `janela=<handle>` ou `regiao=[x, y, largura, altura]` "
            "antes de clicar — não chute a linha."
        )
    if marcar_elementos and _uia is not None:
        try:
            elementos = _coletar_elementos(None, 12, True)
            png = _marcar(png, elementos, meta["escala"], tuple(meta["offset"]))
            corpo["elementos"] = elementos
            corpo["total_marcados"] = min(len(elementos), 60)
        except Exception as exc:  # noqa: BLE001
            corpo["aviso_marcacao"] = str(exc)

    _registrar_auditoria(
        "capturar_tela",
        {"monitor": monitor, "janela": janela, "escala": meta["escala"]},
        png,
    )

    if bloco := _imagem_mcp(png):
        return [corpo, bloco]
    return _erro(f"não consegui montar o bloco de imagem ({_ERRO_FASTMCP})")


def desktop_posicao_cursor() -> dict[str, Any]:
    """Onde o cursor do mouse está agora, em pixels reais da tela."""
    if _pyautogui is None:
        return _erro(f"indisponível ({_ERRO_PYAUTOGUI})")
    x, y = _pyautogui.position()
    return {"ok": True, "x": int(x), "y": int(y)}


# --------------------------------------------------------------------------- #
# TOOLS — sessão e bloqueios
# --------------------------------------------------------------------------- #


def desktop_liberar_controle(minutos: int = 10, motivo: str = "") -> dict[str, Any]:
    """Abre uma janela de tempo para o Jarvis usar mouse e teclado.

    PERGUNTE AO DONO ANTES DE CHAMAR. Só chame depois que ele autorizar em
    palavras. A liberação expira sozinha e não funciona se o controle estiver
    desligado no .env.

    minutos: duração da autorização.
    motivo: o que você vai fazer — vai para a auditoria.
    """
    global _SESSAO_ATE, _SESSAO_MOTIVO, _ACOES_NA_SESSAO

    if not _controle_habilitado():
        return _erro(
            "controle desligado no .env (DESKTOP_CONTROL_ENABLED=false). "
            "Só o dono liga isso, na mão, e reinicia o host."
        )
    minutos = max(1, min(int(minutos), _SESSAO_MAX_MIN))
    _SESSAO_ATE = time.time() + minutos * 60
    _SESSAO_MOTIVO = motivo[:200]
    _ACOES_NA_SESSAO = 0
    _registrar_auditoria(
        "sessao_liberada", {"minutos": minutos, "motivo": _SESSAO_MOTIVO}
    )
    return {
        "ok": True,
        "expira_em_minutos": minutos,
        "acoes_maximo": _MAX_ACOES_SESSAO,
        "lembrete": "o dono aborta a qualquer momento jogando o mouse "
        "no canto superior esquerdo.",
    }


def desktop_encerrar_controle() -> dict[str, Any]:
    """Fecha a sessão de controle imediatamente. Use ao terminar a tarefa."""
    global _SESSAO_ATE, _SESSAO_MOTIVO
    _SESSAO_ATE = 0.0
    _SESSAO_MOTIVO = ""
    _registrar_auditoria("sessao_encerrada", {"acoes": _ACOES_NA_SESSAO})
    return {"ok": True, "acoes_realizadas": _ACOES_NA_SESSAO}


def desktop_bloquear_janela(padrao: str, motivo: str = "") -> dict[str, Any]:
    """Marca uma janela/app como PROIBIDO para o controle de tela, para sempre.

    Use sempre que o dono disser algo como "nunca mexa no meu banco", "não
    encoste no Outlook" ou "esse programa é sensível". Guarde na hora, sem pedir
    confirmação — errar para o lado de bloquear demais é barato.

    padrao: expressão regular casada contra o TÍTULO da janela.
        Ex.: "(?i)outlook" bloqueia qualquer janela com "outlook" no título.
    motivo: por que, em uma linha. Aparece quando uma ação for recusada.
    """
    padrao = (padrao or "").strip()
    if not padrao:
        return _erro("padrão vazio.")
    try:
        re.compile(padrao)
    except re.error as exc:
        return _erro(f"padrão inválido: {exc}")

    itens = _carregar_denylist()
    if any(i["padrao"] == padrao for i in itens):
        return {"ok": True, "ja_existia": True, "padrao": padrao}
    itens.append(
        {
            "padrao": padrao,
            "motivo": motivo or "pedido do dono",
            "criado_em": _agora_iso(),
        }
    )
    _salvar_denylist(itens)
    _registrar_auditoria("bloqueio_adicionado", {"padrao": padrao, "motivo": motivo})
    return {"ok": True, "padrao": padrao, "total_bloqueios": len(itens)}


def desktop_listar_bloqueios() -> dict[str, Any]:
    """Mostra tudo que está proibido para o controle de tela, e por quê."""
    itens = _carregar_denylist()
    return {
        "ok": True,
        "total": len(itens),
        "bloqueios": itens,
        "nota": "os bloqueios de fábrica (senha, banco, UAC, acesso remoto) "
        "não podem ser removidos.",
    }


def desktop_desbloquear_janela(padrao: str, confirmado: bool = False) -> dict[str, Any]:
    """Remove um bloqueio que o dono tinha pedido. Exige confirmação explícita.

    Só chame depois que o dono pedir para desbloquear com todas as letras.
    Bloqueios de fábrica (senha, banco, UAC, acesso remoto) não saem nunca.
    """
    if not confirmado:
        return _erro(
            "remover proteção exige confirmação. Pergunte ao dono e chame de novo "
            "com confirmado=True.",
            precisa_confirmar=True,
        )
    if any(i["padrao"] == padrao for i in _DENYLIST_PADRAO):
        return _erro("este é um bloqueio de fábrica e não pode ser removido.")
    itens = [i for i in _carregar_denylist() if i["padrao"] != padrao]
    _salvar_denylist(itens)
    _registrar_auditoria("bloqueio_removido", {"padrao": padrao})
    return {"ok": True, "removido": padrao, "total_bloqueios": len(itens)}


# --------------------------------------------------------------------------- #
# TOOLS — ação
# --------------------------------------------------------------------------- #


def desktop_abrir(alvo: str, confirmado: bool = False) -> Any:
    """Abre um programa, arquivo, site ou tela de configuração do Windows.

    TENTE ISTO ANTES DE CLICAR. Muita coisa que parece exigir vários cliques é
    um atalho só. Exemplos que funcionam direto:
      - "ms-settings:personalization-colors" → cores e modo claro/escuro
      - "ms-settings:network"   "ms-settings:bluetooth"   "ms-settings:apps"
      - "https://exemplo.com"   → abre no navegador padrão
      - "notepad"  "calc"  "explorer"
      - "C:/caminho/arquivo.pdf"

    confirmado: obrigatório para executáveis (.exe/.bat/.cmd/.ps1/.msi).
    """
    alvo = (alvo or "").strip()
    if not alvo:
        return _erro("alvo vazio.")
    if bloqueio := _exigir_sessao("abrir"):
        return bloqueio
    if _RE_ALVO_PROIBIDO.search(alvo):
        _registrar_auditoria("abrir_recusado", {"alvo": alvo})
        return _erro("este alvo é destrutivo demais para o controle de tela. Recusado.")
    if re.search(r"(?i)\.(exe|bat|cmd|ps1|msi)(\s|$|\")", alvo) and not confirmado:
        return _erro(
            f"{alvo!r} é um executável. Confirme com o dono e chame de novo com "
            "confirmado=True.",
            precisa_confirmar=True,
        )

    try:
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", alvo) or Path(alvo).exists():
            os.startfile(alvo)  # noqa: S606 — URI/caminho, é o handler do shell
        else:
            subprocess.Popen(["cmd", "/c", "start", "", alvo], shell=False)
    except Exception as exc:  # noqa: BLE001
        return _erro(f"não consegui abrir {alvo!r}: {exc}")

    time.sleep(1.2)  # dá tempo da janela aparecer antes da conferência
    return _conferencia("abrir", {"alvo": alvo}, conferir=True)


def desktop_focar_janela(handle: int) -> Any:
    """Traz uma janela para a frente. Faça isto ANTES de clicar ou digitar nela."""
    if _win32gui is None:
        return _erro(f"indisponível ({_ERRO_WIN32})")
    try:
        titulo = _win32gui.GetWindowText(handle)
    except Exception as exc:  # noqa: BLE001
        return _erro(f"handle inválido: {exc}")
    if motivo := _titulo_bloqueado(titulo):
        return _erro(f"janela {titulo!r} bloqueada ({motivo}).")
    if bloqueio := _exigir_sessao("focar_janela"):
        return bloqueio
    try:
        import win32con

        _win32gui.ShowWindow(handle, win32con.SW_RESTORE)
        _win32gui.SetForegroundWindow(handle)
    except Exception as exc:  # noqa: BLE001
        return _erro(f"o Windows recusou o foco (janela elevada?): {exc}")
    time.sleep(0.3)
    return _conferencia(
        "focar_janela", {"handle": handle, "titulo": titulo}, conferir=True
    )


def desktop_clicar_elemento(
    id: str,
    botao: str = "left",
    duplo: bool = False,
    confirmado: bool = False,
    conferir: bool = True,
) -> Any:
    """Clica num controle pelo `id` que desktop_inspecionar devolveu.

    CAMINHO PREFERIDO para clicar. Não erra por escala de tela nem por layout,
    porque usa a posição real que o Windows informa para aquele controle.
    Rode desktop_inspecionar antes para ter os ids.

    confirmado: exigido quando o nome do botão sugere ação sem volta
        (excluir, comprar, formatar...). Pergunte ao dono antes.
    """
    elemento = _ELEMENTOS.get(id)
    if elemento is None:
        return _erro(
            f"id {id!r} desconhecido. Rode desktop_inspecionar de novo — a tela "
            "pode ter mudado desde a última leitura.",
            ids_conhecidos=list(_ELEMENTOS)[:30],
        )
    if time.time() - _ELEMENTOS_EM > 120:
        return _erro(
            "a última inspeção tem mais de 2 minutos. Rode desktop_inspecionar de novo."
        )
    if not elemento["habilitado"]:
        return _erro(f"o controle {elemento['nome']!r} está desabilitado agora.")
    if _RE_DESTRUTIVO.search(elemento["nome"]) and not confirmado:
        return _erro(
            f"{elemento['nome']!r} parece uma ação irreversível. PERGUNTE AO DONO "
            "e só então chame de novo com confirmado=True.",
            precisa_confirmar=True,
            elemento=elemento["nome"],
        )
    if bloqueio := _exigir_sessao("clicar_elemento"):
        return bloqueio

    x, y = elemento["centro_tela"]
    try:
        _pyautogui.click(x=x, y=y, button=botao, clicks=2 if duplo else 1, interval=0.1)
    except Exception as exc:  # noqa: BLE001
        return _erro(f"falha no clique: {exc}")

    return _conferencia(
        "clicar_elemento",
        {"id": id, "nome": elemento["nome"], "tipo": elemento["tipo"], "x": x, "y": y},
        conferir,
    )


def desktop_clicar(
    x: int,
    y: int,
    botao: str = "left",
    duplo: bool = False,
    espaco: str = "captura",
    conferir: bool = True,
) -> Any:
    """Clica numa coordenada MEDIDA NA IMAGEM que você recebeu. FALLBACK.

    Prefira desktop_clicar_elemento. Use isto só quando o alvo não aparecer em
    desktop_inspecionar — app Electron/WebView2 (Teams, Discord, VS Code),
    canvas, jogo.

    espaco: "captura" (padrão) = as coordenadas que você leu na última imagem.
            A captura é REDUZIDA antes de chegar até você, e a conversão de
            volta para pixel real é feita aqui — você não faz conta nenhuma.
            "tela" = pixel real do monitor. Use SOMENTE com o valor de
            `centro_tela` que desktop_inspecionar devolveu.
    """
    if bloqueio := _exigir_sessao("clicar"):
        return bloqueio

    # O default é "captura", e não "tela", porque o modelo não tem como medir em
    # pixel real: a única coisa que ele enxerga é a imagem reduzida (2560x1080
    # chega como 1280x540). Com "tela" no default, TODO clique caía na metade da
    # distância, puxado para o canto superior esquerdo — observado com o Teams,
    # onde o alvo era a lista de conversas e o clique acertou a barra lateral.
    # Um default que só funciona quando quem chama sabe de um detalhe que ele não
    # pode observar é uma armadilha, não um default.
    real_x, real_y = int(x), int(y)
    convertido = False
    if espaco != "tela" and _ULTIMA_ESCALA:
        real_x = int(x / _ULTIMA_ESCALA) + _ULTIMO_OFFSET[0]
        real_y = int(y / _ULTIMA_ESCALA) + _ULTIMO_OFFSET[1]
        convertido = True

    try:
        _pyautogui.click(
            x=real_x, y=real_y, button=botao, clicks=2 if duplo else 1, interval=0.1
        )
    except Exception as exc:  # noqa: BLE001
        return _erro(f"falha no clique: {exc}")

    # A conversão vai para a auditoria: sem ela, uma linha `{"x": 115}` não diz
    # se 115 era o que o modelo pediu ou o que de fato foi clicado, e foi
    # exatamente essa ambiguidade que atrasou o diagnóstico deste bug.
    return _conferencia(
        "clicar",
        {
            "x": real_x,
            "y": real_y,
            "pedido": [int(x), int(y)],
            "espaco": espaco,
            "escala_aplicada": round(1 / _ULTIMA_ESCALA, 3) if convertido else 1,
            "botao": botao,
        },
        conferir,
    )


def desktop_preencher_campo(id: str, texto: str, conferir: bool = True) -> Any:
    """Escreve num campo de texto pelo `id` do desktop_inspecionar.

    MELHOR JEITO DE PREENCHER FORMULÁRIO: escreve o valor direto no controle,
    sem simular tecla. Instantâneo, aceita acentos e não erra se o foco mudar no
    meio. Substitui o conteúdo anterior do campo.
    """
    elemento = _ELEMENTOS.get(id)
    if elemento is None:
        return _erro(f"id {id!r} desconhecido. Rode desktop_inspecionar de novo.")
    if _RE_SEGREDO.search(texto):
        return _erro(
            "esse texto parece conter uma credencial. "
            "Não escrevo segredo em campo nenhum."
        )
    if bloqueio := _exigir_sessao("preencher_campo"):
        return bloqueio
    if _uia is None:
        return _erro(f"UI Automation indisponível ({_ERRO_UIA})")

    try:
        with _com_na_thread():
            x, y = elemento["centro_tela"]
            controle = _uia.ControlFromPoint(x, y)
            if controle is None:
                return _erro("não encontrei o controle nessa posição; a tela mudou?")
            if getattr(controle, "IsPassword", False) is True:
                return _erro(
                    "esse campo é de senha. Recuso escrever nele — "
                    "peça ao dono para digitar."
                )
            controle.GetValuePattern().SetValue(texto)
    except Exception as exc:  # noqa: BLE001
        return _erro(
            f"o controle não aceita escrita direta ({exc}). "
            "Tente desktop_clicar_elemento nele e depois desktop_digitar."
        )

    return _conferencia(
        "preencher_campo",
        {"id": id, "nome": elemento["nome"], "caracteres": len(texto)},
        conferir,
    )


def desktop_digitar(texto: str, conferir: bool = True) -> Any:
    """Digita texto no campo que está em foco agora. Fallback do desktop_preencher_campo.

    Clique no campo antes. Acentos e emoji passam pela área de transferência
    automaticamente, porque simulação de tecla não dá conta deles no Windows.
    """
    if not texto:
        return _erro("texto vazio.")
    if _RE_SEGREDO.search(texto):
        return _erro("esse texto parece conter uma credencial. Não digito segredo.")

    senha = _campo_de_senha()
    if senha is True:
        return _erro(
            "o campo em foco é de senha. Recuso digitar — peça ao dono para preencher."
        )
    if bloqueio := _exigir_sessao("digitar"):
        return bloqueio

    aviso = ""
    if senha is None:
        # Não conseguimos ler a propriedade. Não é motivo para recusar tudo, mas
        # é motivo para registrar — se um segredo vazar, a trilha mostra que a
        # checagem não respondeu, em vez de sugerir que ela aprovou.
        aviso = "não consegui confirmar se o campo é de senha."

    try:
        if texto.isascii():
            _pyautogui.write(texto, interval=0.02)
        elif _definir_clipboard(texto):
            _pyautogui.hotkey("ctrl", "v")
        else:
            return _erro("texto com acentos e área de transferência indisponível.")
    except Exception as exc:  # noqa: BLE001
        return _erro(f"falha ao digitar: {exc}")

    return _conferencia(
        "digitar",
        (
            {"caracteres": len(texto), "aviso": aviso}
            if aviso
            else {"caracteres": len(texto)}
        ),
        conferir,
    )


def desktop_teclas(teclas: list[str], conferir: bool = True) -> Any:
    """Aperta uma combinação de teclas. Ex.: ["ctrl","s"], ["alt","f4"], ["win","d"].

    Uma tecla sozinha também vale: ["enter"], ["esc"], ["tab"].
    """
    if not teclas:
        return _erro("nenhuma tecla informada.")
    limpas = [str(t).lower().strip() for t in teclas]
    if invalidas := [t for t in limpas if t not in _TECLAS_PERMITIDAS]:
        return _erro(f"tecla(s) fora da lista permitida: {invalidas}")
    if bloqueio := _exigir_sessao("teclas"):
        return bloqueio
    try:
        _pyautogui.hotkey(*limpas)
    except Exception as exc:  # noqa: BLE001
        return _erro(f"falha nas teclas: {exc}")
    return _conferencia("teclas", {"teclas": limpas}, conferir)


def desktop_rolar(
    quantidade: int = -3,
    x: int = 0,
    y: int = 0,
    espaco: str = "captura",
    conferir: bool = True,
) -> Any:
    """Rola a tela. Negativo desce, positivo sobe.

    x, y: onde posicionar o mouse antes de rolar, medido na imagem que você
        recebeu (0,0 = deixa o mouse onde está). Rolar exige o ponteiro DENTRO
        da área que se quer rolar — a lista de conversas não rola se o mouse
        estiver sobre o painel do lado.
    """
    if bloqueio := _exigir_sessao("rolar"):
        return bloqueio
    alvo = _para_tela(x, y, espaco) if (x or y) else None
    try:
        if alvo:
            _pyautogui.moveTo(*alvo)
        _pyautogui.scroll(int(quantidade) * 120)
    except Exception as exc:  # noqa: BLE001
        return _erro(f"falha ao rolar: {exc}")
    return _conferencia(
        "rolar", {"quantidade": quantidade, "ponteiro": list(alvo) if alvo else "atual"},
        conferir,
    )


def desktop_arrastar(
    de_x: int,
    de_y: int,
    para_x: int,
    para_y: int,
    espaco: str = "captura",
    conferir: bool = True,
) -> Any:
    """Arrasta de um ponto a outro com o botão esquerdo pressionado.

    Para mover arquivo, redimensionar janela ou ajustar um slider. As
    coordenadas são as que você leu na imagem recebida.
    """
    if bloqueio := _exigir_sessao("arrastar"):
        return bloqueio
    origem = _para_tela(de_x, de_y, espaco)
    destino = _para_tela(para_x, para_y, espaco)
    try:
        _pyautogui.moveTo(*origem)
        _pyautogui.dragTo(*destino, duration=0.4, button="left")
    except Exception as exc:  # noqa: BLE001
        return _erro(f"falha ao arrastar: {exc}")
    return _conferencia(
        "arrastar",
        {"de": list(origem), "para": list(destino), "espaco": espaco},
        conferir,
    )
