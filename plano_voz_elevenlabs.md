> **SUPERSEDIDO por `plano_voz_rapido.md`.** Este documento foi escrito antes de
> duas descobertas que mudam o problema: (1) o caminho de voz não usa o `ChiefAI`
> e portanto **não tem tools, memória nem MCP** hoje; (2) o gargalo de latência é
> o laço serial e bufferizado, não a escolha de fornecedor de TTS — trocar o TTS
> sem consertar isso dá voz melhor com a mesma demora. O que continua válido aqui
> e foi reaproveitado lá: a análise de PCM/ffmpeg (§2) e o raciocínio de custo
> (§7). Mantido para histórico.

# Plano: voz da ElevenLabs na conversação

Substituir o `edge_tts` por ElevenLabs no laço de voz. Escopo é **só a síntese** —
VAD, STT e o LLM ficam como estão.

## 0. Antes de tudo: este plano concorre com o `plano_voz.md`

O `plano_voz.md` argumenta **contra** a ElevenLabs, em dois pontos explícitos:

> §2, Opção 2: *"Estes modelos novos substituem a necessidade de usar ElevenLabs
> ou Google Cloud TTS clássico"*
>
> §5: *"Você elimina integrações com Whisper e ElevenLabs. Tudo acontece dentro
> da API do Google AI Studio, reduzindo dores de cabeça com faturamento e
> múltiplas chaves."*

Os dois caminhos são legítimos e **mutuamente exclusivos na prática** — não vale
manter os dois vivos, porque cada um exige um contrato de áudio diferente no
front. A diferença real entre eles:

| | Live API do Gemini (`plano_voz.md`) | ElevenLabs (este documento) |
|---|---|---|
| Arquitetura | Áudio→áudio nativo; STT, LLM e TTS somem como etapas | Mantém as 3 etapas; troca só a última |
| Qualidade da voz | Boa | O motivo de existir deste plano |
| Escolha de voz | Catálogo fechado do Google | Catálogo grande + clonagem de voz |
| Tamanho da mudança | Reescreve `voice.py` inteiro e o cliente | ~1 função em `voice.py` |
| Chaves e faturamento | Uma só (já existe) | Mais uma |
| Reversível | Não, na prática | Sim — o `edge_tts` fica como fallback |

**Este plano é o incremental.** Ele não fecha a porta da Live API: se um dia a
migração acontecer, a camada de TTS inteira é descartada junto, e nada aqui vira
dívida. É por isso que ele é seguro de fazer antes de decidir o rumo maior.

## 1. Onde exatamente entra

O laço de hoje vive em [`apps/api/routers/voice.py`](apps/api/routers/voice.py),
no WebSocket `/api/voice/call`:

```
cliente → PCM16 16kHz mono (base64)
  → webrtcvad(3) decide início/fim de fala          voice.py:60
  → faster-whisper "tiny", cpu/int8, pt             voice.py:91
  → LM Studio (openai SDK), stream, max_tokens=200   voice.py:110
  → edge_tts "pt-BR-AntonioNeural" → MP3            voice.py:131  ← AQUI
  → pydub decodifica o MP3 (precisa de ffmpeg)      voice.py:140
  → resample p/ 24kHz mono 16-bit, manda PCM cru    voice.py:143
```

A troca é **só das linhas 129–144**. Nada antes muda.

## 2. O achado que decide a arquitetura

A ElevenLabs aceita `output_format` na requisição, e entre as opções há **PCM
16-bit little-endian mono em 24 kHz** — que é, byte por byte, o formato que
`voice.py:143` produz hoje com o pydub e que o player do PWA já espera.

Consequência: pedindo PCM direto, **o transcode desaparece**.

- Some o `AudioSegment.from_file(..., format="mp3")` da linha 140.
- Some a dependência de `ffmpeg` no caminho de voz — aquela que custou ~700 MB
  na imagem da API. (O `pydub` continua no `pyproject.toml` por causa do
  `pcm16_to_audio_segment` do lado da entrada, na linha 32, mas o **binário**
  do ffmpeg deixa de ser necessário e o bloco no `apps/api/Dockerfile` pode
  sair.)
- Some o custo de CPU do decode+resample a cada resposta, num i5-3470.

Isso inverte o balanço de custo do plano: parte do preço da ElevenLabs é paga de
volta em imagem menor e CPU livre.

> **Verificar antes de codar:** o `pcm_24000` é oferecido, mas a ElevenLabs já
> restringiu formatos PCM por plano no passado. Confirme na conta que o seu
> plano libera PCM; se não liberar, o caminho continua funcionando via MP3 — só
> perde a economia acima e mantém o ffmpeg. Meu conhecimento tem corte em maio de
> 2026: **trate todo nome de modelo e limite de plano deste documento como algo a
> reconferir na documentação atual**, não como fato.

## 3. Duas formas de chamar, e qual escolher

### 3.a REST streaming — `POST /v1/text-to-speech/{voice_id}/stream`

Manda o texto **completo** e recebe o áudio em stream.

- Simples: é um `httpx.AsyncClient.stream()` e um `async for` repassando bytes.
- Encaixa no código atual quase sem mudar a forma.
- **Custo:** a síntese só começa depois que o LLM terminou de gerar. O
  `max_tokens=200` da linha 114 vira latência acumulada antes do primeiro som.

### 3.b WebSocket — `/v1/text-to-speech/{voice_id}/stream-input`

Manda o texto **em pedaços, conforme o LLM gera**, e recebe áudio em paralelo.

- O laço da linha 117 (`async for chunk in stream`) já tem os tokens saindo um a
  um; hoje eles vão só para a UI. Aqui eles alimentam a ElevenLabs ao mesmo
  tempo.
- O primeiro áudio sai enquanto o LLM ainda está escrevendo o fim da frase.
- **Custo:** mais peças — conexão a manter, `flush`, alinhamento de fronteira de
  palavra para a prosódia não picotar.

**Recomendação: começar em 3.a, migrar para 3.b se a latência incomodar.** O 3.a
já é uma melhora de qualidade sobre o `edge_tts` e cabe numa tarde; a diferença
de latência entre os dois só aparece em resposta longa, e o sistema já limita a
200 tokens. Trocar depois é local — a função de síntese tem uma responsabilidade
só.

## 4. Modelo e voz

- **Modelo:** a família "flash"/"turbo" existe para tempo real, com latência
  anunciada na casa de dezenas de milissegundos, contra a família
  "multilingual", de qualidade maior e mais lenta. Para chamada de voz, o
  trade-off pende para o rápido: numa conversa, atraso é pior que timbre.
- **Voz:** o `voice_id` é opaco e não tem default sensato — precisa ser escolhido
  na conta e colocado no `.env`. Confirme que a voz escolhida suporta português
  do Brasil; várias vozes do catálogo são treinadas em inglês e sotacam feio em
  pt-BR.
- **Clonagem:** se a ideia é uma voz própria, é aqui que ela entra, e é a única
  coisa deste plano que o caminho do Gemini não oferece.

## 5. Configuração

Três campos em [`packages/shared/settings.py`](packages/shared/settings.py),
seguindo o padrão dos campos do `lmstudio` (linhas 71–73):

```python
# --- ElevenLabs (TTS da conversação por voz) --- #
# Default vazio, e é isso que mantém a voz funcionando sem conta: o laço cai no
# edge_tts quando a chave falta (ver §6). Um default que gasta dinheiro quando
# alguém esquece de configurar é a escolha errada — mesmo raciocínio do
# `chief_provider` acima.
elevenlabs_api_key: str = ""
# Sem default: `voice_id` é opaco e específico da conta. Um id chutado aqui
# renderia 404 em runtime, ou pior, a voz errada.
elevenlabs_voice_id: str = ""
elevenlabs_model: str = "eleven_flash_v2_5"   # CONFERIR nome atual
elevenlabs_output_format: str = "pcm_24000"   # casa com o player do PWA
```

`.env.example` ganha as quatro linhas comentadas. A chave **não** entra no
`Settings` como obrigatória: o fail-fast existe para o que a app não consegue
funcionar sem, e voz é opcional.

## 6. Fallback, e por que ele não é opcional

Se a chave faltar, se a cota estourar ou se a API responder 5xx, **a voz cai para
`edge_tts`** — que é gratuito, já está integrado e já funciona.

Sem isso, uma conta zerada às 23h transforma a conversa por voz num erro mudo.
Com isso, ela fica com a voz pior e continua de pé. O fallback deve ser **por
requisição**, não só no boot: cota acaba no meio do uso, não no start.

Registrar em log toda vez que o fallback dispara (`voice.tts.fallback`, com o
motivo). Sem isso, a degradação é invisível: você percebe que a voz mudou e não
tem como saber por quê — que é exatamente o buraco que o `chat.py` tinha antes de
ganhar `chat.ws.failed`.

## 7. Custo — o item que decide se este plano vale a pena

A ElevenLabs cobra **por caractere sintetizado**, e conversa por voz consome
caractere rápido: o `max_tokens=200` da linha 114 dá algo em torno de 600–900
caracteres por resposta. Cem respostas por dia colocam isso na casa das dezenas
de milhares de caracteres diárias.

Faça a conta com o preço do seu plano **antes de implementar**. Este é o único
item do documento que pode reprovar o plano inteiro, e é barato de verificar.

Duas defesas baratas, se o custo apertar:

1. **Só na conversa por voz.** Nunca sintetizar resposta de chat de texto.
2. **Teto diário de caracteres**, com queda para `edge_tts` ao atingir. Reusa
   exatamente o caminho do §6 — o mecanismo já vai existir.

## 8. Interrupção (barge-in)

Hoje o `processing_lock` da linha 73 **descarta** a fala do usuário que chega
enquanto o Jarvis responde (linha 76–78: `"ignoring overlapping utterance"`).
Numa conversa real isso é ruim: falar por cima é como gente interrompe.

Não é problema criado por este plano — já existe. Mas piora com voz melhor,
porque respostas boas convidam a interromper. Se for tratar, o mínimo é: ao
detectar fala do usuário durante a reprodução, parar de enviar chunks de áudio e
abortar a requisição de síntese. Com a ElevenLabs isso também **economiza**, já
que áudio não gerado não é cobrado.

Sugiro deixar para uma fase própria, depois que a voz estiver de pé.

## 9. Fases

**Fase 1 — a troca (meio dia).**
Configuração do §5, função de síntese nova com REST streaming (§3.a), fallback do
§6, log de fallback. Aceite: a voz sai pela ElevenLabs numa chamada real, e
desligar a chave no `.env` derruba para `edge_tts` sem quebrar a conversa.

**Fase 2 — colher a economia (1–2h).**
Confirmado o PCM do §2, remover o decode do MP3 da linha 140 e o bloco `ffmpeg`
do `apps/api/Dockerfile`. Aceite: a imagem da API encolhe e a chamada continua
funcionando. *Só depois da Fase 1 estar verificada* — são duas mudanças
independentes e juntá-las confunde o diagnóstico se algo quebrar.

**Fase 3 — latência (opcional).**
Migrar para o WebSocket do §3.b. Só se a Fase 1 mostrar espera perceptível.

**Fase 4 — barge-in (opcional).**
O §8.

## 10. Riscos

| Risco | Efeito | Mitigação |
|---|---|---|
| Custo por caractere | Pode reprovar o plano | §7, conferir **antes** de codar |
| PCM restrito por plano | Perde a economia da Fase 2 | Manter MP3+ffmpeg; Fase 1 não depende disso |
| Voz ruim em pt-BR | Sotaque pior que o `edge_tts` | Testar o `voice_id` antes de fixar |
| Nomes de modelo mudados | Código não roda de primeira | Conferir na doc atual (ver aviso do §2) |
| Latência de rede | Voz "engasga" | Fase 3 |
| Conflito com `plano_voz.md` | Trabalho jogado fora se a Live API vencer | §0 — a camada de TTS é descartável por desenho |

## 11. O que este plano não faz

- Não troca o STT. `faster-whisper "tiny"` continua, com a qualidade que tem.
- Não troca o LLM da voz. Continua LM Studio, separado do `chief` do chat.
- Não mexe no chat de texto.
- Não implementa a Live API do Gemini — isso é o `plano_voz.md`, e é uma decisão
  diferente.
