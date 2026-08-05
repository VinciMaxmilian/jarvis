"""Computer use: o caminho que leva um screenshot da tool até os olhos do modelo.

O valor desta suíte está quase todo em dois defeitos que existiam e eram
invisíveis, porque nenhum dos dois quebrava nada — cada um apenas fazia o agente
responder sobre uma imagem que ele nunca recebeu:

1. `MCPClientManager.call_tool` lia só blocos `text` e descartava `image` em
   silêncio. Uma tool de captura perfeita chegava vazia.
2. O laço do `ChiefAI` mandava ao provider apenas as imagens do turno do dono. O
   que uma tool fotografasse virava JSON de texto e morria ali.

Os dois falham de forma confiante — o modelo descreve a tela de memória e
inventa. Por isso os testes olham para o que o PROVIDER recebeu, não para o que
a tool devolveu: é a única asserção que prova que a imagem atravessou.

Nada aqui importa `mss`, `pyautogui` ou `uiautomation`: a suíte roda no CI (e em
container) onde não há tela. O servidor do host é exercitado por inspeção
estática — ver a última seção.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final
from uuid import uuid4

import pytest

from packages.agents.chief import _RODADAS_PADRAO, _TETO_IMAGENS, ChiefAI
from packages.agents.profiles import (
    CHIEF_PROFILE,
    EXECUTOR_PROFILE,
    PLANNER_PROFILE,
    REVIEWER_PROFILE,
)
from packages.agents.tool_guard import ToolDenied, guard_tools
from packages.llm.base import Completion, Message, ToolSpec
from packages.mcp.client_manager import MCPClientManager
from tests.conftest import (
    FakeLLMProvider,
    InMemoryConversationStore,
    RecordingToolExecutor,
    make_tool_spec,
)

_PNG_FALSO: Final = "iVBORw0KGgoAAAANSUhEUg=="
_RAIZ: Final = Path(__file__).resolve().parents[2]
_HOST_MAIN: Final = _RAIZ / "mcp" / "jarvis_windows_host" / "main.py"


# --------------------------------------------------------------------------- #
# 1. O bloco de imagem do MCP não pode mais ser jogado fora
# --------------------------------------------------------------------------- #


class _SessaoFalsa:
    """`ClientSession` do MCP reduzida ao que `call_tool` consome."""

    def __init__(self, blocos: list[Any], is_error: bool = False) -> None:
        self._resultado = SimpleNamespace(content=blocos, isError=is_error)
        self.chamadas: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.chamadas.append((name, arguments))
        return self._resultado


def _gerente_com(blocos: list[Any], is_error: bool = False) -> MCPClientManager:
    gerente = MCPClientManager(Path("nao_existe"))
    sessao = _SessaoFalsa(blocos, is_error)
    gerente.servers["host"] = SimpleNamespace(session=sessao)  # type: ignore[assignment]
    gerente.tool_routes["desktop_capturar_tela"] = "host"
    return gerente


async def test_call_tool_devolve_a_imagem_em_vez_de_descarta_la() -> None:
    """O defeito original: `if item.type == "text"` e mais nada."""
    gerente = _gerente_com(
        [
            SimpleNamespace(type="text", text='{"ok": true}'),
            SimpleNamespace(type="image", data=_PNG_FALSO, mimeType="image/png"),
        ]
    )

    resultado = await gerente.call_tool("desktop_capturar_tela", {})

    assert resultado["images_b64"] == [_PNG_FALSO]
    assert resultado["result"] == '{"ok": true}'


async def test_imagem_sai_separada_do_texto() -> None:
    """Separado não é detalhe de formato: base64 embutido no texto viraria prosa
    para o modelo e empurraria o histórico para fora do contexto."""
    gerente = _gerente_com(
        [
            SimpleNamespace(type="text", text="cliquei no botão"),
            SimpleNamespace(type="image", data=_PNG_FALSO, mimeType="image/png"),
        ]
    )

    resultado = await gerente.call_tool("desktop_capturar_tela", {})

    assert _PNG_FALSO not in resultado["result"]


async def test_tool_sem_imagem_nao_ganha_a_chave() -> None:
    """Chave `images` vazia faria todo consumidor testar duas coisas."""
    gerente = _gerente_com([SimpleNamespace(type="text", text="ok")])
    assert "images_b64" not in await gerente.call_tool("desktop_capturar_tela", {})


async def test_erro_continua_erro_mesmo_com_imagem_anexada() -> None:
    gerente = _gerente_com(
        [
            SimpleNamespace(type="text", text="falhou"),
            SimpleNamespace(type="image", data=_PNG_FALSO, mimeType="image/png"),
        ],
        is_error=True,
    )
    resultado = await gerente.call_tool("desktop_capturar_tela", {})
    assert resultado == {"error": "falhou"}


# --------------------------------------------------------------------------- #
# 2. A captura da tool tem de chegar na rodada seguinte do modelo
# --------------------------------------------------------------------------- #


class _LLMQueRegistraImagens(FakeLLMProvider):
    """Dublê com `complete_with_images` — é o `hasattr` que o `ChiefAI` testa.

    Guarda o que recebeu POR RODADA. Sem essa granularidade não dá para
    distinguir "a imagem chegou" de "a imagem chegou na hora certa", e a segunda
    é a que importa: chegar uma rodada atrasada é o mesmo que não chegar.
    """

    def __init__(self) -> None:
        super().__init__()
        self.imagens_por_rodada: list[list[str]] = []

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system: str | None = None,
    ) -> Completion:
        self.imagens_por_rodada.append([])
        return await super().complete(messages, tools, temperature, max_tokens, system)

    async def complete_with_images(
        self,
        messages: list[Message],
        images: list[str],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system: str | None = None,
    ) -> Completion:
        self.imagens_por_rodada.append(list(images))
        return await super().complete(messages, tools, temperature, max_tokens, system)


def _executor_que_fotografa(*capturas: str) -> RecordingToolExecutor:
    """Executor cuja `desktop_capturar_tela` devolve imagem, como o MCP real."""
    return RecordingToolExecutor(
        [make_tool_spec("desktop_capturar_tela"), make_tool_spec("web_search")],
        results={
            "desktop_capturar_tela": {"result": "capturei", "images_b64": list(capturas)}
        },
    )


async def _rodar(chief: ChiefAI, texto: str = "põe no modo escuro") -> None:
    async for _ in chief.respond(texto, uuid4()):
        pass


async def test_captura_da_tool_chega_na_rodada_seguinte() -> None:
    """O aceite da Fase 0. Sem isto o agente é cego logo depois de fotografar."""
    llm = _LLMQueRegistraImagens()
    llm.queue_tool_call("desktop_capturar_tela", {})
    llm.queue_text("está no modo claro, vou trocar")

    chief = ChiefAI(
        llm=llm,
        tools=_executor_que_fotografa("PNG_DA_TELA"),
        conversation_store=InMemoryConversationStore(),
        profile=CHIEF_PROFILE,
    )
    await _rodar(chief)

    assert llm.imagens_por_rodada[0] == []  # antes de fotografar, nada
    assert llm.imagens_por_rodada[1] == ["PNG_DA_TELA"]  # depois, a tela


async def test_base64_nao_vaza_para_o_texto_do_tool_result() -> None:
    """O base64 sai do JSON e vira bloco de imagem. O que sobra no texto é uma
    nota curta — o modelo precisa saber que a imagem existe, não recebê-la duas
    vezes."""
    llm = _LLMQueRegistraImagens()
    llm.queue_tool_call("desktop_capturar_tela", {})
    llm.queue_text("pronto")

    chief = ChiefAI(
        llm=llm,
        tools=_executor_que_fotografa("PNG_ENORME"),
        conversation_store=InMemoryConversationStore(),
        profile=CHIEF_PROFILE,
    )
    await _rodar(chief)

    conteudo_tool = [m.content for m in llm.received[-1] if m.role == "tool"]
    assert conteudo_tool, "o resultado da tool tem de estar no contexto"
    assert "PNG_ENORME" not in conteudo_tool[0]
    assert "captura" in conteudo_tool[0].lower()


async def test_so_as_ultimas_capturas_seguem_para_o_modelo() -> None:
    """Sem teto, um turno de 15 rodadas mandaria 15 PNGs de tela cheia."""
    llm = _LLMQueRegistraImagens()
    for _ in range(4):
        llm.queue_tool_call("desktop_capturar_tela", {})
    llm.queue_text("terminei")

    executor = RecordingToolExecutor(
        [make_tool_spec("desktop_capturar_tela")],
        results={"desktop_capturar_tela": {"result": "ok", "images_b64": ["A", "B"]}},
    )
    chief = ChiefAI(
        llm=llm,
        tools=executor,
        conversation_store=InMemoryConversationStore(),
        profile=CHIEF_PROFILE,
    )
    await _rodar(chief)

    assert all(len(i) <= _TETO_IMAGENS for i in llm.imagens_por_rodada)
    # E o que sobrou é o mais RECENTE, não o mais antigo: o modelo precisa do
    # estado atual da tela, não do de cinco cliques atrás.
    assert llm.imagens_por_rodada[-1] == ["A", "B"]


async def test_imagem_do_dono_sobrevive_a_uma_tool_sem_captura() -> None:
    """Regressão do defeito antigo (foto de gato + `analyze_image`): chamar
    qualquer tool não pode cegar o agente sobre o anexo do dono."""
    llm = _LLMQueRegistraImagens()
    llm.queue_tool_call("web_search", {"query": "gato"})
    llm.queue_text("é um gato")

    chief = ChiefAI(
        llm=llm,
        tools=_executor_que_fotografa(),
        conversation_store=InMemoryConversationStore(),
        profile=CHIEF_PROFILE,
    )
    async for _ in chief.respond("que bicho é esse?", uuid4(), images=["FOTO_DO_DONO"]):
        pass

    assert llm.imagens_por_rodada == [["FOTO_DO_DONO"], ["FOTO_DO_DONO"]]


# --------------------------------------------------------------------------- #
# 3. Orçamento de rodadas
# --------------------------------------------------------------------------- #


async def test_turno_sem_desktop_mantem_o_orcamento_curto() -> None:
    """Pilotar interface é caro; conversa normal não pode pagar essa conta."""
    llm = _LLMQueRegistraImagens()
    for _ in range(_RODADAS_PADRAO + 3):
        llm.queue_tool_call("web_search", {"query": "x"})

    chief = ChiefAI(
        llm=llm,
        tools=_executor_que_fotografa(),
        conversation_store=InMemoryConversationStore(),
        profile=CHIEF_PROFILE,
    )
    await _rodar(chief)

    assert len(llm.imagens_por_rodada) == _RODADAS_PADRAO


async def test_tool_de_desktop_estica_o_orcamento() -> None:
    """Abrir → inspecionar → clicar → conferir → corrigir já são cinco rodadas.
    Com o teto padrão, a tarefa morre exatamente quando ia terminar."""
    llm = _LLMQueRegistraImagens()
    for _ in range(_RODADAS_PADRAO + 3):
        llm.queue_tool_call("desktop_capturar_tela", {})

    chief = ChiefAI(
        llm=llm,
        tools=_executor_que_fotografa("PNG"),
        conversation_store=InMemoryConversationStore(),
        profile=CHIEF_PROFILE,
    )
    await _rodar(chief)

    assert len(llm.imagens_por_rodada) > _RODADAS_PADRAO


# --------------------------------------------------------------------------- #
# 4. Quem pode olhar e quem pode clicar
# --------------------------------------------------------------------------- #


def _catalogo_desktop() -> RecordingToolExecutor:
    return RecordingToolExecutor(
        [
            make_tool_spec("desktop_capturar_tela"),
            make_tool_spec("desktop_inspecionar"),
            make_tool_spec("desktop_clicar_elemento"),
            make_tool_spec("desktop_digitar"),
            make_tool_spec("desktop_liberar_controle"),
            make_tool_spec("desktop_bloquear_janela"),
        ]
    )


@pytest.mark.parametrize("perfil", [REVIEWER_PROFILE, PLANNER_PROFILE])
def test_papel_de_leitura_enxerga_a_tela(perfil: Any) -> None:
    """Um reviewer que não pode tirar screenshot não consegue julgar "ficou mesmo
    no modo escuro?" — e `allow_unlisted=False` o deixaria exatamente assim."""
    guardado = guard_tools(_catalogo_desktop(), perfil)
    nomes = {s.name for s in guardado.specs()}
    assert {"desktop_capturar_tela", "desktop_inspecionar"} <= nomes


@pytest.mark.parametrize("perfil", [REVIEWER_PROFILE, PLANNER_PROFILE])
async def test_papel_de_leitura_nao_clica_nem_se_o_modelo_pedir(perfil: Any) -> None:
    interno = _catalogo_desktop()
    guardado = guard_tools(interno, perfil)

    for proibida in (
        "desktop_clicar_elemento",
        "desktop_digitar",
        "desktop_liberar_controle",
    ):
        with pytest.raises(ToolDenied):
            await guardado.execute(proibida, {})

    assert interno.calls == [], "a recusa tem de vir ANTES do efeito"


async def test_executor_clica_de_fato() -> None:
    """Contraprova: a recusa acima é do papel, não uma trava geral."""
    interno = _catalogo_desktop()
    guardado = guard_tools(interno, EXECUTOR_PROFILE)

    await guardado.execute("desktop_clicar_elemento", {"id": "e7"})

    assert [c[0] for c in interno.calls] == ["desktop_clicar_elemento"]


async def test_qualquer_papel_pode_apertar_a_seguranca() -> None:
    """`desktop_bloquear_janela` só ADICIONA proibição. O papel que ouvir "nunca
    mexa no meu banco" tem de poder gravar isso na hora, mesmo sendo de leitura;
    exigir troca de papel para registrar uma proteção perderia o pedido."""
    guardado = guard_tools(_catalogo_desktop(), REVIEWER_PROFILE)
    await guardado.execute("desktop_bloquear_janela", {"padrao": "(?i)banco"})


# --------------------------------------------------------------------------- #
# 5. O servidor do host, por inspeção estática
#
# `mcp/jarvis_windows_host/main.py` não é importável aqui: ele depende de tela,
# e o CI não tem uma. Mas as duas propriedades abaixo são estruturais e quebram
# em silêncio — a primeira transforma um helper em tool exposta ao modelo, a
# segunda faz o container subir uma cópia do servidor que fotografa o nada.
# --------------------------------------------------------------------------- #


def _funcoes_publicas_do_host() -> list[str]:
    arvore = ast.parse(_HOST_MAIN.read_text(encoding="utf-8"))
    return [
        n.name
        for n in arvore.body
        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
    ]


def test_toda_funcao_publica_do_host_e_uma_tool_desktop() -> None:
    """`mcp/main.py` registra TODA função pública do módulo como tool. Um helper
    sem `_` viraria uma tool sem descrição no catálogo do modelo."""
    publicas = _funcoes_publicas_do_host()
    assert publicas, "o servidor do host não expôs nenhuma tool"
    assert all(n.startswith("desktop_") for n in publicas), publicas


def test_toda_tool_do_host_tem_docstring() -> None:
    """A docstring É a descrição que o modelo lê para escolher a tool. Sem ela, a
    tool existe e nunca é chamada — ou é chamada errado."""
    arvore = ast.parse(_HOST_MAIN.read_text(encoding="utf-8"))
    sem_doc = [
        n.name
        for n in arvore.body
        if isinstance(n, ast.FunctionDef)
        and not n.name.startswith("_")
        and not ast.get_docstring(n)
    ]
    assert sem_doc == []


def test_servidor_do_host_esta_marcado_como_host_only() -> None:
    """Sem o marcador, `discover_and_connect` subiria este servidor como stdio
    DENTRO do container e ele roubaria a rota das tools do host real."""
    assert (_HOST_MAIN.parent / "HOST_ONLY").exists()


async def test_discover_pula_pasta_marcada_host_only(tmp_path: Path) -> None:
    pasta = tmp_path / "jarvis_windows_host"
    pasta.mkdir()
    (pasta / "main.py").write_text("", encoding="utf-8")
    (pasta / "HOST_ONLY").write_text("", encoding="utf-8")

    gerente = MCPClientManager(tmp_path)
    await gerente.discover_and_connect()

    assert "jarvis_windows_host" not in gerente.servers


async def test_urls_do_web_search_nunca_viram_imagem_para_o_provider() -> None:
    """Regressão de produção: Gemini HTTP 400, "Base64 decoding failed for
    https://...".

    `SystemToolExecutor._web_search` devolve `images` com uma lista de URLs de
    resultado de busca. Quando o laço passou a aceitar imagem vinda de tool, ele
    lia essa chave e mandava as URLs para o canal multimodal como se fossem
    bytes. Duas coisas diferentes com o mesmo nome — por isso o canal de captura
    virou `images_b64`, e por isso este teste existe.
    """
    llm = _LLMQueRegistraImagens()
    llm.queue_tool_call("web_search", {"query": "gatinhos"})
    llm.queue_text("achei estas fotos")

    executor = RecordingToolExecutor(
        [make_tool_spec("web_search")],
        results={
            "web_search": {
                "answer": "fotos de gatinhos",
                "images": ["https://exemplo.com/gato.png", "https://x.com/b.jpg"],
                "results": [],
            }
        },
    )
    chief = ChiefAI(
        llm=llm,
        tools=executor,
        conversation_store=InMemoryConversationStore(),
        profile=CHIEF_PROFILE,
    )
    await _rodar(chief, "pesquise imagens de gatinhos")

    assert all(i == [] for i in llm.imagens_por_rodada), llm.imagens_por_rodada
    # E as URLs continuam no TEXTO, que é onde servem: é assim que o modelo as
    # devolve ao dono em markdown de imagem.
    conteudo = [m.content for m in llm.received[-1] if m.role == "tool"]
    assert "exemplo.com/gato.png" in conteudo[0]


async def test_captura_base64_sobrevive_ao_filtro_de_url() -> None:
    """A contraprova: o filtro tira URL, não tira captura."""
    llm = _LLMQueRegistraImagens()
    llm.queue_tool_call("desktop_capturar_tela", {})
    llm.queue_text("vi a tela")

    chief = ChiefAI(
        llm=llm,
        tools=_executor_que_fotografa("iVBORw0KGgoAAAA"),
        conversation_store=InMemoryConversationStore(),
        profile=CHIEF_PROFILE,
    )
    await _rodar(chief)

    assert llm.imagens_por_rodada[1] == ["iVBORw0KGgoAAAA"]
