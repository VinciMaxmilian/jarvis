# Plano — Computer Use (Jarvis vê a tela, clica e digita)

*Escrito em 2026-08-05. Base: `ESTADO_DO_PROJETO.md` + leitura do código atual.*

---

## STATUS — implementado em 2026-08-05

Fases 0 a 3 **aplicadas e verificadas na máquina do dono**. Fase 4 (painel no PWA,
modal de aprovação, push no mobile) segue pendente.

| O que | Onde | Verificado |
|---|---|---|
| `call_tool` preserva bloco de imagem | [client_manager.py:165](packages/mcp/client_manager.py#L165) | 4 testes |
| Captura de tool entra na rodada seguinte | [chief.py:296](packages/agents/chief.py#L296) | 5 testes |
| Orçamento de rodadas 5 → 15 com `desktop_*` | [chief.py:48](packages/agents/chief.py#L48) | 2 testes |
| Servidor do host, 19 tools | [mcp/jarvis_windows_host/main.py](mcp/jarvis_windows_host/main.py) | smoke real + 4 testes |
| Marcador `HOST_ONLY` (container não sobe cópia) | [client_manager.py:76](packages/mcp/client_manager.py#L76) | 2 testes |
| Política por perfil | [profiles.py:141](packages/agents/profiles.py#L141) | 5 testes |
| Hierarquia de precedência | `prompts/{chief,executor,voice}.md` | — |
| Script de boot no Windows | [scripts/run_desktop_host.ps1](scripts/run_desktop_host.ps1) | executado |

**Suíte:** 20 testes novos, todos passando. As 16 falhas e 24 erros do
`pytest tests/` são idênticos ao baseline antes desta mudança (`cf_access`,
`kernel_execucao`, `scheduler`, prompt do chief) — nenhum foi introduzido aqui.
`ruff check` limpo nos arquivos novos.

### Decisões do dono (2026-08-05)

1. **Todas as tools de ação de uma vez** — feito, 19 tools.
2. **Modelo de visão local (LM Studio)** — nada força o Gemini; o perfil resolve.
   Privacidade deixa de ser questão porque o alvo do projeto é 100% local.
3. **Denylist aprendida por conversa** — `desktop_bloquear_janela` grava em
   `data/desktop_denylist.json` quando o dono disser "nunca mexa em X", sem pedir
   confirmação. Prompt instrui a gravar na hora.
4. **`apolo_desktop_agent` fica** — os dois convivem; `desktop_*` é o fallback
   para quando `abrir_navegador`/`executar_comando_cmd` não bastarem.

### Achados da verificação real (não previstos no plano)

- **Multi-monitor quebrava a captura.** `monitor=0` uniu as duas telas em
  4480×1081, que reduzido ao teto de largura virou uma tira de 1280×308 —
  ilegível. O default virou "a tela onde está a janela em foco" (2560×1080 →
  1280×540, escala 0,5). `-1` é a união, com aviso na docstring.
- **A trilha de auditoria mentia.** `{"acao": acao, **detalhes}` deixava um
  detalhe chamado `acao` sobrescrever o nome do evento: uma ação BLOQUEADA era
  gravada como se o clique tivesse acontecido. `acao` passou para o fim do dict.
- **Pillow não estava instalado no `.venv`**, apesar de constar no `pyproject`.
  Sem ele a percepção inteira caía — `desktop_status` acusa isso por nome agora.

### O que ainda não foi exercitado com a máquina de verdade

Mouse e teclado **nunca chegaram a se mover** nesta verificação: as travas foram
testadas até o ponto da recusa, e clicar de verdade na sua tela é decisão sua,
não minha. O que rodou de fato: captura, inspeção UIA, marcação numerada,
listagem de janelas, denylist, auditoria e as 10 recusas de segurança.

## 1. O objetivo

Quando o Jarvis recebe um pedido que **nenhuma capability e nenhum MCP resolve** —
"abre as configurações de personalização e põe no modo escuro", "entra nesse site e
preenche o formulário", "abre o WhatsApp e manda essa mensagem" — ele deve poder:

1. **Olhar** a tela (screenshot),
2. **Decidir** onde clicar / o que digitar,
3. **Agir** (mouse + teclado),
4. **Olhar de novo** para conferir se deu certo, e repetir.

É o último recurso do sistema: mais lento e menos confiável que uma tool dedicada,
mas cobre 100% do que o usuário consegue fazer com mouse e teclado.

---

## 2. O que já existe no código (e ajuda muito)

Levantamento real, não suposição:

| Peça | Onde | Estado |
|---|---|---|
| Ponte MCP para o **host Windows** via SSE | [client_manager.py:99-115](packages/mcp/client_manager.py#L99-L115) | O cliente **já tenta** conectar em `WINDOWS_MCP_URL` (default `http://host.docker.internal:8765/sse`) com o nome `Jarvis-Windows-Host`. **O servidor não existe no repositório.** É o encaixe perfeito. |
| Visão multimodal no LLM | [gemini_provider.py:561](packages/llm/gemini_provider.py#L561), `ollama_provider.py`, `openai_provider.py` | `complete_with_images(messages, images: list[str] base64)` já implementado em 3 providers. |
| Loop de tools com imagem persistente | [chief.py:270-290](packages/agents/chief.py#L270-L290) | A imagem já acompanha **todas** as rodadas de tool do mesmo turno (correção documentada no próprio código). |
| Descoberta/roteamento de MCP | [client_manager.py:153](packages/mcp/client_manager.py#L153) | `call_tool` roteia por nome de tool. |
| Política de tools por perfil | [tool_guard.py:93](packages/agents/tool_guard.py#L93), [profiles.py:183](packages/agents/profiles.py#L183) | `ProfiledToolExecutor.execute` recusa **antes** de executar. Já dá para travar computer-use só no `executor`/`chief`. |
| Aprovação por tool | `ToolSpec.requires_approval` em [contracts.py:204](packages/shared/contracts.py#L204) | Campo existe no contrato. |
| MCP desktop rudimentar | [mcp/apolo_desktop_agent/main.py](mcp/apolo_desktop_agent/main.py) | Só `abrir_navegador` e `executar_comando_cmd`. Roda como stdio **dentro do container** — não enxerga a tela do Windows. |
| Miss determinístico | `CapabilityGapDetected` em `packages/registry/exceptions.py` | Evento de "não sei fazer isso" já existe — é o gatilho natural do fallback. |

**Conclusão do levantamento:** a arquitetura já foi desenhada para isto. Falta o
servidor do host e três correções de encanamento.

---

## 3. Decisão arquitetural central: roda no HOST, não no container

A API e o orchestrator rodam em Docker. Um container **não tem tela, mouse nem
teclado do Windows** — nem com X11 forwarding isso resolveria, porque a tela que o
usuário quer que o Jarvis veja é a sessão gráfica do Windows.

Também **não** deve ser uma `capability/` do SDK: capabilities rodam em subprocesso
sandboxado pelo kernel (`packages/kernel/runtime/sandbox.py`), dentro do container.

Portanto: **um servidor MCP nativo no Windows**, processo separado, falando SSE na
porta `8765` — exatamente o que `client_manager.py` já procura.

```
┌─────────────── Docker ───────────────┐        ┌──── Windows host ────┐
│  API / orchestrator                  │        │                      │
│    ChiefAI ──> ToolExecutor ──> MCP  │◄──SSE──┤ jarvis_windows_host  │
│                 client_manager       │  :8765 │  (FastMCP)           │
└──────────────────────────────────────┘        │   mss → screenshot   │
                                                │   uiautomation → UIA │
                                                │   pyautogui → input  │
                                                └──────────────────────┘
```

Vantagem colateral: o mesmo servidor vira a casa de qualquer outra tool que precise
do host de verdade (abrir apps, ler janelas, notificações do Windows).

---

## 4. Estratégia de percepção: UIA primeiro, visão depois

Clicar por coordenada que o modelo "chutou olhando o pixel" é o modo frágil de fazer
isso — erra em DPI escalado, muda de posição a cada versão do Windows, e não sabe se
o clique funcionou.

O Windows expõe a **UI Automation tree** (a mesma API dos leitores de tela): nomes,
tipos e retângulos de todos os controles. Isso é semântico e determinístico.

**Regra do plano:**

1. `desktop_inspect` devolve a árvore UIA filtrada (elementos clicáveis/editáveis,
   com `id`, `nome`, `tipo`, `rect`). O modelo escolhe **por id**, não por pixel.
2. `desktop_click_element(id)` clica no centro do rect daquele elemento.
3. **Só quando a UIA não enxerga** (Electron mal instrumentado, canvas, jogo,
   conteúdo web sem acessibilidade) o modelo cai para `desktop_screenshot` +
   `desktop_click(x, y)`.
4. O screenshot enviado ao modelo leva **Set-of-Mark**: caixas numeradas desenhadas
   sobre os elementos UIA detectados. O modelo diz "clica no 7" em vez de "clica em
   (1284, 673)". Reduz drasticamente o erro de coordenada.

Para o exemplo do usuário (modo claro/escuro), a UIA resolve inteiro: as
Configurações do Windows são um app WinUI totalmente instrumentado.

---

## 5. Superfície de tools do servidor

Nomes em `desktop_*` para o roteamento e a política ficarem legíveis.

### Percepção (idempotente, sem aprovação)
| Tool | Entrada | Saída |
|---|---|---|
| `desktop_screenshot` | `monitor?`, `region?`, `mark_elements=true` | PNG base64 (já redimensionado), `escala`, `resolucao_real` |
| `desktop_inspect` | `janela?`, `profundidade=4`, `so_interativos=true` | lista de elementos `{id, nome, tipo, rect, habilitado}` |
| `desktop_list_windows` | — | janelas abertas `{handle, titulo, processo, foreground}` |
| `desktop_cursor_pos` | — | `{x, y}` |

### Ação (nunca idempotente, sempre auditada)
| Tool | Entrada | Observação |
|---|---|---|
| `desktop_click_element` | `id`, `botao=left`, `duplo=false` | **caminho preferido** |
| `desktop_click` | `x`, `y`, `botao`, `duplo` | fallback visual |
| `desktop_type` | `texto`, `intervalo=0.02` | recusa se campo focado for `IsPassword` |
| `desktop_key` | `teclas: ["ctrl","c"]` | combinação; whitelist de teclas |
| `desktop_scroll` | `dx`, `dy`, `x?`, `y?` | |
| `desktop_drag` | `de_x`, `de_y`, `para_x`, `para_y` | |
| `desktop_focus_window` | `handle` | traz janela à frente antes de agir |
| `desktop_launch` | `alvo` (app/URI/`ms-settings:personalization`) | atalho barato: muita coisa nem precisa de clique |

> `desktop_launch` merece destaque: `start ms-settings:personalization` resolve o
> pedido do modo escuro em um passo. O modelo deve tentar **URI/atalho antes de
> clicar**. Isso vai no prompt do papel.

### Contrato de retorno de toda ação
Toda tool de ação devolve `{ok, o_que_fiz, screenshot_depois}` — screenshot pós-ação
por padrão. É o que fecha o loop ver → agir → **conferir**.

---

## 6. As três correções de encanamento (bloqueadores reais)

### 6.1 `call_tool` joga imagem fora — **bloqueador**

[client_manager.py:165-173](packages/mcp/client_manager.py#L165-L173):

```python
for item in result.content:
    if item.type == "text":
        output += item.text + "\n"
```

Bloco `image` do MCP é **descartado em silêncio**. Um `desktop_screenshot` que
funcionasse perfeitamente chegaria vazio ao modelo. Corrigir para coletar
`item.type == "image"` (`item.data` base64 + `item.mimeType`) e devolver
`{"result": ..., "images": [...]}`.

### 6.2 Tool result não injeta imagem na próxima rodada — **bloqueador**

[chief.py:286-290](packages/agents/chief.py#L286-L290): `images` vem só do turno do
usuário (`chief.respond(images=...)`) e é constante dentro do laço. O resultado de
tool vira `result_str = json.dumps(result)` — texto. Ou seja: hoje o modelo **não
consegue ver o que a tool fotografou**.

Correção mínima, sem tocar no contrato `Message`:
- `images` vira acumulador **com janela** dentro do laço de rodadas;
- quando o resultado da tool traz `images`, elas entram na lista para a rodada
  seguinte e o base64 sai do `result_str` (senão o JSON do texto explode o contexto);
- **teto rígido: as 2 últimas capturas.** Sem isso, 8 rodadas × ~1 MB de PNG viram
  um contexto impagável e lento.

Alternativa mais limpa (`Message.content` virar lista de blocos em
[llm/base.py:21](packages/llm/base.py#L21)) — **não recomendo agora**: mexe em 4
providers, no persistidor de conversa e em todo call site. Fica como refactor
posterior se a visão passar a ser central.

### 6.3 Redimensionar e mapear coordenadas

Um monitor 2560×1440 vira ~1,3 MB de PNG e estoura o limite de imagem de vários
providers. O servidor deve:
- reduzir para largura máxima ~1280 e devolver `escala` junto;
- **converter a coordenada de volta para a tela real no lado do host**, nunca pedir
  para o modelo fazer conta;
- chamar `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)` no boot — sem isso o
  Windows mente a resolução em telas com escala 125%/150% e todo clique sai deslocado.

---

## 7. Segurança — a parte que não pode ser cortada

Esta feature dá ao modelo **controle total da máquina do usuário**. Um clique errado
apaga arquivo, manda mensagem para a pessoa errada, ou aprova uma compra. As
proteções abaixo fazem parte do escopo mínimo, não são "fase 2".

1. **Interruptor mestre.** `DESKTOP_CONTROL_ENABLED=false` no `.env` por padrão. Sem
   isso, o servidor sobe só com as tools de percepção.
2. **Sessão com prazo.** Ações só funcionam dentro de uma janela ativada
   explicitamente pelo dono ("libera o controle por 10 min"). Expirou, volta a negar.
3. **Failsafe físico.** `pyautogui.FAILSAFE = True` — jogar o mouse no canto superior
   esquerdo aborta na hora. Documentar isso para o usuário é parte da entrega.
4. **Confirmação para irreversível.** `requires_approval=true` (já suportado por
   `ToolSpec`) para: clique em botão cujo nome UIA bate com
   `excluir|apagar|delete|remove|format|desinstalar|comprar|pagar|enviar|confirmar`,
   `desktop_launch` de executável fora da allowlist, e `desktop_key` com `Enter` em
   diálogo modal.
5. **Nunca digitar em campo de senha.** `desktop_type` consulta `IsPassword` do
   elemento focado e recusa. Também recusa se o texto casar com padrão de segredo.
6. **Allowlist / denylist de janelas.** Denylist default: gerenciador de senhas,
   banco, `mstsc`, UAC. Se a janela em foco está na denylist, ação nenhuma passa.
7. **Não roda elevado.** Sem UAC, sem admin. Por UIPI o agente simplesmente não
   controla janela elevada — e isso é uma proteção, não um bug a contornar.
8. **Auditoria completa.** Todo par (ação, screenshot antes/depois) vai para
   `data/desktop_audit/` com `structlog`. Sem trilha, "por que meu arquivo sumiu?"
   não tem resposta.
9. **Rate limit.** Máx. ~1 ação/300 ms e teto de ações por sessão. Cortar loop maluco
   antes que ele faça 400 cliques.
10. **Política por perfil.** Em [profiles.py](packages/agents/profiles.py): `desktop_*`
    de ação só para `executor` e `chief`. `planner`, `researcher` e `reviewer` ficam
    só com percepção (entram em `_LEITURA`; ação em `_ACAO`).
11. **Bind local.** O SSE escuta em `127.0.0.1:8765` (o container alcança via
    `host.docker.internal`), com token compartilhado no header. Porta de controle
    total de máquina não fica aberta na rede.

---

## 8. Como o fallback dispara (o coração do pedido)

O usuário pediu: *"se ele não tiver tool ou MCP para isso, ele poder ver minha tela e
decidir onde clicar"*. Duas camadas, complementares:

**Camada 1 — instrução de precedência no prompt** (resolve 90% dos casos).
No prompt do `executor`/`chief` (`packages/agents/prompts/`), ordem explícita:

> 1. Tool ou capability dedicada, se existir. 2. `desktop_launch` com URI/atalho do
> Windows. 3. Só então `desktop_inspect` → `desktop_click_element`. 4. Screenshot +
> clique por coordenada é o último recurso. Nunca use computer-use para o que uma
> tool já faz — é mais lento e erra mais.

**Camada 2 — gatilho no miss determinístico** (a rede de segurança).
Quando o registry levanta `CapabilityGapDetected` / `ToolNotFound`
(`packages/shared/ports.py:162`), a tarefa hoje trava. Passa a existir um terceiro
caminho: se o controle de desktop estiver habilitado e a sessão liberada, o gap vira
uma tentativa de computer-use antes de virar SPEC de self-evolution. Encaixa
exatamente no fluxo `Miss ➔ SPEC` já desenhado no `ESTADO_DO_PROJETO.md` §4 — com
computer-use como degrau intermediário, e a SPEC como a solução definitiva.

Detalhe importante: quando o computer-use **resolve** um pedido, isso é material de
primeira qualidade para a Experience Memory e para a SPEC — "o dono pediu X, foi
resolvido em 6 cliques, vale virar tool". O gap ganha evidência em vez de só um log.

---

## 9. Fases de entrega

### Fase 0 — Encanamento (1 dia) · *sem isto, nada funciona*
- [ ] `call_tool` preserva blocos de imagem (§6.1) + teste unitário com MCP fake.
- [ ] `chief.py` acumula imagens de tool result com teto de 2 (§6.2) + teste de que a
      rodada N+1 recebe o screenshot da rodada N.
- **Aceite:** um MCP de mentira que devolve PNG faz o modelo descrever a imagem.

### Fase 1 — Percepção (2 dias)
- [ ] `mcp/jarvis_windows_host/` com FastMCP SSE em `127.0.0.1:8765`.
- [ ] Deps: `mss`, `uiautomation`, `pyautogui`, `pywin32` (grupo opcional
      `[project.optional-dependencies] desktop` no `pyproject.toml` — não vai para a
      imagem Docker).
- [ ] `desktop_screenshot`, `desktop_inspect`, `desktop_list_windows`.
- [ ] DPI awareness + redimensionamento + Set-of-Mark.
- [ ] Script `scripts/run_desktop_host.ps1` para subir no Windows.
- **Aceite:** "o que está na minha tela agora?" no chat responde certo. Zero ação.

### Fase 2 — Ação com trava (2-3 dias)
- [ ] `desktop_click_element`, `desktop_click`, `desktop_type`, `desktop_key`,
      `desktop_scroll`, `desktop_focus_window`, `desktop_launch`.
- [ ] Toda a §7: interruptor, sessão com prazo, failsafe, denylist, campo de senha,
      auditoria, rate limit.
- [ ] Política de perfil em `profiles.py`.
- **Aceite (o caso do usuário):** "põe o Windows no modo escuro" → `desktop_launch`
      abre `ms-settings:personalization-colors`, `desktop_inspect` acha o combo,
      `desktop_click_element` troca, screenshot final confirma.

### Fase 3 — Loop autônomo e fallback (2 dias)
- [ ] Prompt de precedência (§8 camada 1).
- [ ] Gatilho no `CapabilityGapDetected` (§8 camada 2).
- [ ] Limite de passos por objetivo (~15) + auto-verificação por screenshot.
- **Aceite:** "abre o Notepad, escreve 'oi' e salva em `data/teste.txt`" completo, sem
      intervenção.

### Fase 4 — UI e confiança (2 dias)
- [ ] Painel no PWA: sessão ativa, contador, botão **PARAR** grande, trilha de
      auditoria com os screenshots.
- [ ] Modal de aprovação para as ações marcadas `requires_approval`.
- [ ] Notificação no mobile quando uma ação pede aprovação (encaixa no Gate 1 já
      planejado).

**Total estimado: ~9-10 dias.** Fases 0-2 já entregam o caso concreto que motivou
o pedido.

---

## 10. Riscos conhecidos

| Risco | Mitigação |
|---|---|
| Modelo clica no lugar errado e causa dano | UIA por id em vez de pixel; aprovação para irreversível; auditoria; failsafe |
| Screenshot estoura contexto/custo | Teto de 2 imagens, redimensionamento, preferir `desktop_inspect` (texto) a screenshot |
| Latência: cada passo é uma ida ao LLM multimodal | Preferir `desktop_launch`/URI; UIA resolve sem imagem; usar o perfil de modelo mais rápido com visão |
| Janela elevada (UAC) não responde | Por design. Documentar e devolver erro claro em vez de tentar de novo em loop |
| Servidor do host fora do ar | `client_manager` já ignora em silêncio — mas isso esconde o problema. Adicionar log e um status visível no painel |
| Modelo local (LM Studio) sem visão decente | Rotear computer-use pelo perfil `vision` do Gemini; `resolve_profile_model` já suporta perfil por tarefa |
| Multi-monitor | `desktop_list_windows` e `desktop_screenshot` recebem `monitor`; mapear coordenada em espaço virtual, não por monitor |

---

## 11. Decisões que preciso que você tome

1. **Escopo da Fase 2** — libero todas as tools de ação de uma vez, ou começo só com
   `click_element` + `launch` (sem teclado livre) para medir a taxa de acerto?
2. **Modelo de visão** — computer-use força o Gemini (melhor em UI, mas manda
   screenshot da sua tela para a nuvem), ou tenta local primeiro? Tem implicação de
   privacidade real: **cada screenshot é um upload da sua tela**.
3. **Denylist inicial** — quais janelas/apps entram na lista de "nunca toque"?
4. **`apolo_desktop_agent`** — o novo servidor absorve `abrir_navegador` e
   `executar_comando_cmd` (que hoje rodam dentro do container e não fazem o que o nome
   promete), ou deixo os dois convivendo?
