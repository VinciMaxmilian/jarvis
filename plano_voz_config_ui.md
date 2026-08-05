# Plano — configurar voz (TTS) pela aba Rules

Objetivo: na aba Rules, além de PROVIDER/MODEL do chat, ter **TTS PROVIDER**, **TTS MODEL**
e **VOICE** escolhíveis pela UI e persistidos em banco.

> Revisado com a doc atual do Gemini (Speech generation + Live API overview). O que a doc
> muda em relação ao código de hoje está na seção "Delta da doc do Gemini".

## Estado atual

| O quê | Onde | Fonte |
|---|---|---|
| `tts_provider`, `tts_gemini_model`, `tts_gemini_voice`, `tts_edge_voice` | `packages/shared/settings.py:115-121` | `.env`, estático, só muda com restart |
| Construção do TTS | `apps/api/routers/voice.py:65-71` (`make_tts`) | lê `.env` no accept do websocket |
| Chamada ao Gemini | `packages/voice/tts.py:102-136` | `POST /v1beta/models/{model}:generateContent` |
| Extração do áudio | `packages/voice/tts.py:139-151` | `candidates[0].content.parts[].inlineData.data` |
| Config editável pela UI | `SystemSettings` (`packages/shared/contracts.py:337`) → `system_settings` (id=1) | banco, via `PUT /api/settings/` |
| Tela | `apps/web/src/pages/RulesPage.tsx` (seção CHIEF AI CONFIG) | — |

Ou seja: existem **duas** trilhas de configuração e a voz está na errada. O trabalho é
mover a decisão de voz do `.env` para o mesmo caminho que provider/model já usam,
mantendo o `.env` como default de boot.

## Delta da doc do Gemini

1. **Catálogo de vozes confirmado: 30 vozes.** Some a dúvida do plano anterior. Zephyr,
   Puck, Charon, Kore, Fenrir, Leda, Orus, Aoede, Callirrhoe, Autonoe, Enceladus,
   Iapetus, Umbriel, Algieba, Despina, Erinome, Algenib, Rasalgethi, Laomedeia,
   Achernar, Alnilam, Schedar, Gacrux, Pulcherrima, Achird, Zubenelgenubi,
   Vindemiatrix, Sadachbia, Sadaltager, Sulafat. Cada uma tem descritor (Kore = *Firm*,
   Puck = *Upbeat*, Achird = *Friendly*…) → o descritor vira o rótulo na UI, porque
   "Sadaltager" sozinho não diz nada a quem escolhe.
2. **Português é suportado e o idioma é detectado do texto** — nenhum campo de idioma na UI.
3. **Três modelos de TTS**, e a diferença é operacional: `gemini-3.1-flash-tts-preview`
   (único com streaming), `gemini-2.5-flash-preview-tts` (o default de hoje),
   `gemini-2.5-pro-preview-tts`. Como a escolha tem consequência real de latência e
   custo, **TTS MODEL entra na UI** (mudança em relação ao plano anterior, que deixava
   o modelo só no `.env`).
4. **Superfície de API nova: `POST /v1beta/interactions`.** Corpo `{model, input,
   response_format:{type:"audio"}, generation_config:{speech_config:[{voice}]}}`, áudio
   em `output_audio.data` (base64). O adaptador atual fala `:generateContent` com
   `contents` + `speechConfig.voiceConfig.prebuiltVoiceConfig.voiceName` e lê
   `candidates[]`. **Duas formas incompatíveis de request e de parse.**
5. **Saída continua PCM 16-bit mono 24 kHz.** O contrato do módulo (`tts.py:39-42`) e o
   player do PWA seguem válidos — é o que torna a migração de endpoint uma troca
   interna, sem tocar no cliente.
6. **O 3.1 devolve `500` aleatório** numa fração pequena de requisições (a doc
   recomenda retry). Isso conflita com `TTSComFallback`, que hoje não faz retry por
   decisão explícita de latência (`tts.py:202-208`).
7. **Live API é outro produto, não este.** WebSocket stateful, barge-in, transcrição —
   substituiria Whisper + VAD + TTS de uma vez. Fora de escopo aqui; ver "Fora de escopo".

## Decisões de design

1. **Um campo `tts_voice`, não um por provider.** Mesma escolha que `model` já fez:
   trocar de provider troca a voz junto (default do catálogo). Guardar
   `gemini_voice` + `edge_voice` separados duplica estado que a UI nunca mostra ao
   mesmo tempo. Vale igual para `tts_model`.
2. **Vazio = default do módulo** (`GEMINI_TTS_VOICE` / `pt-BR-AntonioNeural`). Igual a
   `model` vazio → `provider_default_model()`. Renomeação de voz pelo fornecedor não
   exige migração de dados.
3. **Voice é `input` com `datalist`, não `select` fechado.** As 30 vozes de hoje são um
   ponto no tempo — a doc está em Preview e o próprio `tts.py:44-48` já foi escrito
   avisando disso. Select fechado transforma catálogo velho em voz inescolhível;
   input com sugestões, não. Mesmo raciocínio para `tts_model` (o `.env` continua
   podendo apontar para um modelo que a UI não lista).
4. **Banco sobrescreve `.env`, `.env` continua sendo o default.** Nenhuma
   instalação existente quebra: linha sem valor cai no que já estava no `.env`.
5. **Campos opcionais no PUT (`None` = não mexer).** O `apps/mobile` também faz
   `PUT /api/settings/` com só quatro campos. Se os novos campos tiverem default
   não-nulo no contrato, salvar config pelo mobile **apaga a escolha de voz feita
   no web**. Este é o único risco de regressão real do plano.
6. **Migrar o `GeminiTTS` para `/v1beta/interactions` só depois de verificar por curl.**
   A doc nova documenta `interactions`; ela não afirma que `:generateContent` morreu.
   Trocar às cegas é arriscar substituir um caminho que funciona por um que não testei.
   Ordem: curl nos dois → migrar se `interactions` responder → manter o parse antigo
   como fallback de leitura, que é barato (`output_audio` ou `candidates[]`).
7. **Retry só no 500, só uma vez, só antes do fallback.** O motivo de não ter retry era
   latência; um 500 que a doc chama de aleatório é o caso em que a segunda tentativa
   custa menos que trocar a voz no meio da conversa. Não vale para 4xx (cota, voz
   inválida, modelo errado): esses não melhoram na segunda tentativa.

## Passos

### 1. Catálogo — `packages/voice/tts.py`

- `TTS_CATALOG: Final[dict[str, TTSCatalogEntry]]` por provider, com `default_voice`,
  `voices` (id + rótulo descritivo) e `models` (+ `default_model`).
  - `gemini`: as 30 vozes com descritor; modelos `gemini-3.1-flash-tts-preview`,
    `gemini-2.5-flash-preview-tts` (default atual), `gemini-2.5-pro-preview-tts`.
  - `edge`: `pt-BR-AntonioNeural` (default), `pt-BR-FranciscaNeural`,
    `pt-BR-ThalitaNeural`; sem modelos.
- `tts_provider_ids()`, `tts_default_voice(provider)`, `tts_default_model(provider)`.
- Fica aqui, e não no router: é o mesmo módulo que sabe montar cada adaptador. O router
  de settings vira consumidor, como já é de `deps.valid_provider_ids()`.

### 2. Adaptador Gemini — `packages/voice/tts.py`

- Verificar por curl, com a chave real, **antes de editar**:
  `POST /v1beta/interactions` (corpo da doc) e o `:generateContent` de hoje.
- Se `interactions` responder: `GeminiTTS.synthesize` passa a montar
  `{model, input, response_format:{type:"audio"}, generation_config:{speech_config:[{voice}]}}`.
- `_extrair_pcm` aceita as duas formas: `output_audio.data` primeiro,
  `candidates[0].content.parts[].inlineData.data` depois. Poucas linhas, e é o que
  permite voltar de modelo sem voltar de código.
- Um retry em `500`/`503`, sem backoff, antes de levantar `TTSError` (decisão 7). Log
  `voice.tts.retry` — retry silencioso esconde fornecedor degradado.
- `make_tts` ganha `gemini_model`/`gemini_voice` já vindos resolvidos de cima; a
  assinatura atual (`tts.py:228-235`) já comporta isso sem mudança.

### 3. Contrato — `packages/shared/contracts.py`

- `TTSProviderId = Literal["gemini", "edge"]` (espelha o `Literal` do `Settings`).
- Em `SystemSettings`: `tts_provider: TTSProviderId | None = None`,
  `tts_model: str | None = None`, `tts_voice: str | None = None`. Nulável pela decisão 5.
- Exportar `TTSProviderId` no `__all__`.

### 4. Banco — `apps/api/db/models.py` + migração

- `SystemSettingsRow`: `tts_provider String(20)`, `tts_model String(100)`,
  `tts_voice String(100)`, todas `default=""` e `server_default=""` — a linha id=1 já
  existe e um `NOT NULL` sem default derruba o upgrade.
- Migração nova em `apps/api/alembic/versions/`; rodar `alembic heads` antes para
  pendurar no head certo (hoje: `0001` → `6c0c7a8deed0` → `0003`, confirmar).

### 5. API — `apps/api/routers/settings.py`

- `GET /api/settings/voices` →
  `{"providers":[{"id","default_voice","default_model","voices":[{"id","label"}],"models":[...]}]}`.
  Endpoint próprio, puro em memória, mesma razão que separa `/providers` de `/profiles`:
  não pode falhar por causa de rede.
- `GET /`: devolver `tts_provider`/`tts_model`/`tts_voice` já resolvidos (row vazia →
  `.env` → default do módulo). A UI recebe sempre valor concreto para exibir.
- `PUT /`: `tts_provider is not None` → validar contra `tts_provider_ids()` (422 com a
  lista válida, igual ao provider de LLM). `tts_model`/`tts_voice` gravam como vierem —
  string vazia é escolha legítima ("usa o default"). Campo `None` não toca a coluna.

### 6. Runtime — `apps/api/routers/voice.py`

- No accept do websocket, antes do `make_tts` (linha 65), abrir sessão com
  `get_session_factory()` (padrão já usado na linha 172) e ler `SystemSettingsRow`.
- Precedência: banco → `.env` → default do módulo.
- Falha ao ler o banco **não** derruba a chamada: loga `voice.tts.config_fallback` e usa
  o `.env`. Voz pior > chamada caída (mesma regra do fallback do `tts.py`).

### 7. UI — `apps/web/src/pages/RulesPage.tsx`

- Estado: `ttsProvider`, `ttsModel`, `ttsVoice`, `voiceCatalog`.
- `useEffect`: `fetch('/api/settings/voices')` junto dos dois fetches que já existem.
- Nova `<section>` **VOICE CONFIG** depois de CHIEF AI CONFIG, mesmo layout `hud-panel`:
  - `TTS PROVIDER` — select.
  - `TTS MODEL` — input + `datalist` (só aparece para `gemini`; `edge` não tem modelo).
  - `VOICE` — input + `datalist` com `Kore — Firm`, `Puck — Upbeat`, … O descritor é o
    que torna a lista escolhível; o valor salvo é só o nome.
- `handleTtsProviderChange`: troca provider e já troca modelo e voz para os defaults do
  novo — mesma proteção que `handleProviderChange` faz para `model`
  (`RulesPage.tsx:55-56`).
- `handleSave`: incluir os três campos no body.
- `apps/mobile/src/screens/SettingsScreen.tsx`: **não mexer**. Continua mandando só os
  quatro campos antigos e, pela decisão 5, não apaga nada.

### 8. Testes — `tests/unit/`

- `PUT` com `tts_provider` inválido → 422.
- `PUT` sem os campos de voz (payload do mobile) → colunas de voz **inalteradas**. É o
  teste que trava a regressão da decisão 5.
- `GET /` com row vazia → devolve o default do `.env`.
- `GET /voices` → todo provider de `tts_provider_ids()` presente, com `default_voice` e
  `default_model` não vazios, e todo `default_voice` contido na própria lista `voices`.
- `_extrair_pcm` com corpo `output_audio` e com corpo `candidates[]` → mesmos bytes.
- `GeminiTTS` com 500 no primeiro POST e 200 no segundo → sintetiza (retry), e com 429
  nos dois → `TTSError` sem segunda tentativa.
- Precedência no `voice.py`: banco preenchido vence `.env`.

### 9. Fechamento

- `graphify update .`
- Com o LM Studio ligado: trocar voz na UI → **nova** chamada de voz usa a voz nova (a
  chamada em curso não muda: o `tts` é construído uma vez por conexão, `voice.py:65`).

## Fora de escopo (decidido)

- Modelo LLM separado para o perfil `voice`; escolha do modelo Whisper (STT) pela UI.
- **Streaming de TTS** (`stream:true`, eventos `step.delta`, só no 3.1). Reduz latência
  por frase de verdade, mas mexe no `Locutor`/`SentenceBuffer`, não na tela de config.
  Vale como trabalho seguinte, depois que `tts_model` estiver escolhível — sem isso não
  dá nem para pôr o 3.1 em produção para testar.
- **Live API.** Outro produto: WebSocket stateful, barge-in nativo, transcrição inclusa
  — substituiria Whisper + VAD + `Locutor` inteiros. Se um dia entrar, entra como
  **outro port** ao lado do `TTSProvider`, não como mais um adaptador dele: o port atual
  é texto → PCM por frase, e o Live é uma sessão bidirecional. Nada neste plano atrapalha
  isso.
