# Plano: voz rápida, com o Jarvis de verdade dentro

Manter a arquitetura modular (STT → LLM → TTS) e atacar a latência onde ela
realmente está. **Substitui o `plano_voz_elevenlabs.md`**, que foi escrito antes
de duas descobertas que mudam o problema (§0 e §1).

## 0. A descoberta que reenquadra tudo: o Jarvis não está na voz

[`voice.py:63-65`](apps/api/routers/voice.py) monta a própria lista de mensagens:

```python
messages = [
    {"role": "system", "content": "Você é o Jarvis. Responda de forma concisa..."}
]
```

e chama o LM Studio direto ([`voice.py:110`](apps/api/routers/voice.py)), **sem
passar o parâmetro `tools`**.

O que isso significa na prática: a conversa por voz de hoje não tem `web_search`,
não tem `search_memory`, não tem os servidores MCP, não tem o `chief.md`, não tem
o histórico do banco, não tem RAG. É um assistente separado que se apresenta como
Jarvis e não é.

Portanto este plano tem **dois objetivos, não um**:

1. Colocar o `ChiefAI` no caminho de voz (o Jarvis de verdade).
2. Fazer o resultado ser mais rápido do que o brinquedo que está lá hoje.

O segundo é mais difícil por causa do primeiro — tools custam segundos. É por
isso que o §3 existe.

## 1. Onde a latência está de fato

O laço de hoje é **serial e bufferizado duas vezes**:

```
[fala do usuário termina]
  → VAD espera N frames de silêncio
  → whisper transcreve a fala INTEIRA
  → LLM gera os 200 tokens ATÉ O ÚLTIMO         voice.py:110-123
  → edge_tts sintetiza a resposta INTEIRA
     e o MP3 é acumulado num BytesIO             voice.py:133-137  ← o pior
  → pydub decodifica o MP3 INTEIRO               voice.py:140
  → resample                                     voice.py:143
  → [primeiro som sai]
```

Nada se sobrepõe a nada. O `edge_tts` já entrega em chunks (`communicate.stream()`
na linha 134), e o código joga essa vantagem fora acumulando tudo antes de tocar.

**A conclusão que importa: o maior ganho não está em trocar de fornecedor, está
em parar de esperar.** Trocar TTS sem consertar o serial dá uma voz melhor com a
mesma demora.

## 2. Os três consertos, em ordem de retorno

### 2.a Sintetizar por frase, não por resposta — **maior ganho, menor risco**

Conforme o LLM emite tokens, acumular num buffer e disparar o TTS assim que
fechar uma frase (`.`, `!`, `?`, `\n`). A frase 1 toca enquanto o modelo ainda
escreve a frase 3.

O primeiro som passa de *"depois de tudo"* para *"depois da primeira frase"* —
numa resposta de 4 frases, corta perto de 70% da espera percebida.

Dois detalhes que fazem a diferença entre funcionar e soar quebrado:

- **Ordem é obrigatória.** Se as sínteses rodarem concorrentes, o áudio precisa
  ser enviado na ordem das frases mesmo que a frase 2 fique pronta antes da 1.
  Uma fila com envio sequencial resolve; sínteses paralelas com envio fora de
  ordem produzem resposta embaralhada, que é pior que lentidão.
- **Não picotar demais.** Frase de duas palavras sintetizada sozinha soa
  robótica, porque o TTS perde a prosódia do período. Vale um mínimo (~40
  caracteres) antes de cortar, juntando frases curtas consecutivas.

### 2.b Trocar o `ChiefAI` no lugar do LM Studio cru

Substituir as linhas 104-125 por consumo de `chief.respond(...)`, que já devolve
`AsyncIterator[StreamChunk]` com `type` em `"text" | "tool_call" | "done" |
"error"` ([`packages/llm/base.py:59-66`](packages/llm/base.py)).

O `type="text"` alimenta o buffer de frase do §2.a. O `type="tool_call"` é o
gatilho do §3.

**Ganho colateral:** o histórico da conversa por voz passa a ser o mesmo do chat
de texto — hoje são universos separados, e o que você fala não existe para o
Jarvis que você digita.

**Custo:** o prompt do `chief.md` é grande e pede markdown, que é veneno para
TTS. Precisa de um perfil de voz — provavelmente um `AgentProfile` novo em
[`packages/agents/profiles.py`](packages/agents/profiles.py), reaproveitando as
tools do `chief` com um `prompt_file` próprio que proíbe markdown e pede frases
curtas. A estrutura de perfis já existe exatamente para isso.

### 2.c PCM direto, matando o transcode

Se o TTS escolhido entregar PCM 24 kHz mono 16-bit, some o
`AudioSegment.from_file(..., format="mp3")` da linha 140, some o resample da 143
e some a necessidade do binário `ffmpeg` na imagem (~700 MB). Num i5-3470, o
decode+resample por frase não é desprezível.

Menor dos três ganhos em latência, maior em custo de máquina.

## 3. "Responder, agir, responder" — o padrão que salva o tool call

Com o `ChiefAI` dentro, uma pergunta como *"como está o tempo?"* dispara
`web_search`, que é uma ida ao Tavily. São segundos de silêncio absoluto, e
silêncio numa chamada de voz lê como travamento — o usuário repete a pergunta e
piora tudo.

O `chief.respond()` emite `StreamChunk(type="tool_call")` **antes** de executar a
ferramenta. Esse chunk é o gancho:

```
usuário pergunta
  → chunk tool_call chega
  → FALA IMEDIATA de preenchimento ("deixa eu procurar isso")   ← esconde a espera
  → a tool roda (Tavily, MCP, o que for)
  → chunks de texto voltam → §2.a sintetiza por frase
  → resposta real
```

Regras que fazem isso soar natural em vez de irritante:

- **Variar a frase.** Um punhado de opções sorteadas. A mesma frase toda vez vira
  tique em dois dias de uso.
- **Escolher pela tool.** `web_search` pede "deixa eu procurar"; `search_memory`
  pede "deixa eu lembrar". O nome da tool está no chunk — usar isso é barato e o
  ganho de naturalidade é grande.
- **Só se a espera valer.** Tool que responde em 200 ms não precisa de
  preenchimento; o filler viraria atraso. Um limiar (dispara só se a tool não
  respondeu em ~600 ms) evita falar à toa.
- **Não gravar no histórico.** O preenchimento é um artefato de UX, não fala do
  assistente. Entrar no histórico envenena o contexto das próximas respostas.

Esse padrão é o que mais aproxima a sensação da conversa com um agente dedicado,
sem abrir mão do cérebro.

## 4. Gemini ou ElevenLabs — e por que a resposta é "os dois, e você decide depois"

O repositório já resolveu esse tipo de escolha uma vez: `LLMProvider` é um
Protocol em [`packages/llm/base.py`](packages/llm/base.py) com quatro adaptadores
(gemini, ollama, openai, anthropic), e o provider vem do `.env`. **Fazer o mesmo
com TTS é a decisão certa aqui**, e custa pouco porque a superfície é mínima:

```python
class TTSProvider(Protocol):
    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """Texto → PCM 16-bit mono 24 kHz, em chunks."""
```

Três adaptadores, e o `.env` escolhe:

| | A favor | Contra |
|---|---|---|
| **`edge_tts`** (hoje) | Grátis, já funciona, ótimo fallback | Voz mediana, sem controle |
| **Gemini** | **Chave já existe** e já é validada no `Settings`; uma conta só; mesmo ecossistema do `chief` | Catálogo de vozes fechado |
| **ElevenLabs** | Melhor timbre; clonagem de voz | Mais uma chave; custo por caractere; qualidade em pt-BR varia por voz |

**Recomendação: começar pelo Gemini.** O motivo é operacional, não técnico — a
chave já está configurada (`gemini_api_key`, com `AliasChoices` para
`GOOGLE_API_KEY`), então não há conta nova, cobrança nova nem segredo novo para
gerenciar. Se o timbre decepcionar, trocar para ElevenLabs vira uma linha no
`.env`, porque o port já vai existir.

O `edge_tts` **fica** como fallback permanente. Cota estourada às 23h deve
degradar a voz, não derrubar a conversa — e o fallback precisa ser por
requisição, não só no boot, porque cota acaba no meio do uso.

> **Sobre a ElevenLabs especificamente:** o id que você tem
> (`agent_1501kywwsr1rfcqrd8wra8hvv4sx`) é de **agente da Conversational AI**, não
> de voz para TTS. Ele não serve para este plano — aqui o que entra é um
> `voice_id`. O agente pertence ao outro caminho, o de áudio-para-áudio, que é o
> assunto do `plano_voz.md`.

## 5. Fases

**Fase 1 — pipeline por frase (§2.a).** Sem trocar nada de fornecedor, sem tocar
no cérebro. Continua `edge_tts`, continua LM Studio. Aceite: o primeiro som sai
antes de a resposta terminar de ser gerada. *Esta fase sozinha já entrega a maior
parte do ganho de latência, e é a mais fácil de reverter se algo soar errado.*

**Fase 2 — port de TTS (§4) + Gemini.** Aceite: trocar `TTS_PROVIDER` no `.env`
troca a voz sem tocar em código, e derrubar a chave cai para `edge_tts` sem
quebrar a chamada.

**Fase 3 — `ChiefAI` na voz (§2.b) + perfil de voz.** Aqui a voz ganha tools,
memória e histórico compartilhado. Aceite: perguntar por voz algo que exija
`web_search` funciona, e o que foi dito por voz aparece no chat de texto.

**Fase 4 — responder/agir/responder (§3).** Só depois da 3, porque só aí existem
tool calls para esconder. Aceite: pergunta que dispara tool não tem silêncio
maior que ~1s.

**Fase 5 — PCM direto (§2.c).** Depois que o provider estiver definido. Aceite: o
bloco `ffmpeg` sai do `apps/api/Dockerfile` e a chamada continua funcionando.

A ordem é deliberada: **cada fase é entregável e verificável sozinha**, e as duas
primeiras não tocam no cérebro. Se o tempo acabar na fase 2, o sistema fica
melhor do que está hoje, e não pela metade.

## 6. Riscos

| Risco | Efeito | Mitigação |
|---|---|---|
| Frases curtas soam robóticas | Voz picotada | Mínimo de caracteres (§2.a) |
| Áudio fora de ordem | Resposta embaralhada — pior que lenta | Fila com envio sequencial (§2.a) |
| Prompt do `chief` pede markdown | TTS lendo asterisco | Perfil de voz próprio (§2.b) |
| Filler virando tique | Irritação em dias | Variar + limiar de tempo (§3) |
| Custo do TTS pago | Conta indesejada | `edge_tts` como fallback; teto diário |
| Latência do LM Studio na LAN | Piso que o TTS não resolve | Considerar Gemini no perfil de voz |

## 7. O que este plano não faz

- **Não conserta o barge-in.** O `processing_lock` de
  [`voice.py:73-78`](apps/api/routers/voice.py) continua descartando a fala do
  usuário durante a resposta (`"ignoring overlapping utterance"`). É o maior
  problema de UX restante depois da latência, e merece plano próprio — com
  síntese por frase fica *mais fácil* de resolver, porque dá para parar entre
  frases em vez de abortar um blob de áudio.
- **Não troca o STT.** `faster-whisper "tiny"` continua. Se depois das 5 fases o
  gargalo for ele, aí sim vale medir.
- **Não implementa áudio-para-áudio.** Isso é o `plano_voz.md`, e é uma decisão
  diferente — inclusive é o único caminho onde o `agent_...` que você tem entra.
