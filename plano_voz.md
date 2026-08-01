# Plano de Implementação: Conversação por Voz (Jarvis)

Este documento detalha o plano arquitetural e técnico para adicionar suporte a conversas por voz em tempo real no projeto Jarvis, **atualizado para utilizar os modelos mais recentes da família Gemini 3 e Gemini 2.5 (Live API)**.

## 1. Nova Visão Geral da Arquitetura (Áudio-para-Áudio Nativo)
Com base na documentação mais recente do Google AI Studio, a arquitetura de voz sofreu uma evolução massiva. Os modelos da série **Live** (como o Gemini 3.1 Flash Live) são modelos **A2A (Audio-to-Audio) nativos**.

Isso significa que a arquitetura clássica de 3 passos (STT -> LLM Texto -> TTS) **foi completamente eliminada**. O fluxo agora é direto e unificado:
1. **Entrada e Saída:** O cliente (Web/Tauri/Mobile) abre uma conexão bidirecional contínua (WebSockets/WebRTC) com a API do Gemini.
2. **Processamento Único:** O áudio do usuário flui para o modelo, que "pensa" nativamente em áudio e já devolve a resposta em formato de áudio (streaming de voz).

## 2. Escolha de Tecnologias e Modelos

De acordo com o ecossistema Gemini atualizado, recomendamos as seguintes opções:

### Opção 1: O Padrão Ouro (Live API - Tudo em Um)
*   **Modelo Recomendado:** `Gemini 3.1 Flash Live Preview` (ou `Gemini 2.5 Flash Live Preview` como fallback).
*   **Como funciona:** Este é um modelo de áudio-para-áudio (A2A) de baixíssima latência. Ele suporta agentes de voz bidirecionais.
*   **Vantagem Máxima:** O modelo compreende instantaneamente a entonação do usuário e responde com voz natural sem precisar converter para texto em nenhum momento do processo. O modelo gerencia a própria interrupção.

### Opção 2: Abordagem Modular (Áudio in -> Texto -> TTS Gemini)
*Cenário onde você precise manter o histórico de texto perfeitamente sincronizado antes de gerar a voz.*
*   **Processamento (STT + Cérebro):** `Gemini 3.6 Flash` (recebe áudio nativamente e devolve texto rápido).
*   **Voz (TTS):** `Gemini 3.1 Flash TTS Preview` ou `Gemini 2.5 Flash TTS Preview`. (Estes modelos novos substituem a necessidade de usar ElevenLabs ou Google Cloud TTS clássico, oferecendo geração de voz poderosa, controlável e de baixíssima latência na mesma API).

## 3. Desafio Técnico Principal: Live API e Conexão Contínua
A conversação precisa ser fluida e bidirecional. O foco técnico sai do "como transcrever" e passa para "como manter o fluxo de rede estável":

1. **Protocolo:** O backend (ou diretamente o cliente, caso seja seguro) precisa estabelecer uma conexão de streaming (WebSockets) com a *Live API* do Gemini.
2. **Microfone Aberto:** O cliente captura o áudio do microfone continuamente e envia pacotes raw para a API.
3. **Reprodução em Tempo Real:** Conforme a API retorna pacotes de áudio da resposta do Jarvis, o cliente os reproduz imediatamente usando a Web Audio API.

## 4. Passos para Implementação (Foco na Live API)

### Fase 1: Prototipação Modular (Fallback)
*   Usar `Gemini 3.6 Flash` para receber áudio do microfone do usuário e gerar um texto.
*   Enviar o texto gerado para o `Gemini 3.1 Flash TTS Preview` para gerar o áudio de resposta.
*   *Objetivo:* Familiarizar-se com as novas capacidades nativas de áudio da API antes de pular para streaming complexo.

### Fase 2: Integração com a Live API (Áudio-para-Áudio)
*   Mudar a arquitetura para usar o `Gemini 3.1 Flash Live Preview`.
*   Implementar a conexão WebSocket de ponta a ponta.
*   Nesta fase, o modelo já deve ser capaz de falar e ouvir simultaneamente, resolvendo grande parte dos problemas de latência automaticamente.

### Fase 3: Refinamento de UX e Interrupções
*   Implementar a lógica de cliente para tratar *barge-in* (quando o usuário interrompe o Jarvis). Na Live API, enviar novo áudio enquanto o modelo fala geralmente já sinaliza a interrupção.
*   Gerenciar estados na UI (ex: animação pulsante quando o Jarvis está ouvindo vs. quando está falando).

## 5. Vantagens Absolutas do Ecossistema Atualizado
*   **Latência de Nível Humano:** Ao usar modelos A2A (Audio-to-Audio), a resposta do Jarvis pode começar em menos de 1 segundo após o usuário terminar de falar.
*   **Consolidação de Stack:** Você elimina integrações com Whisper e ElevenLabs. Tudo acontece dentro da API do Google AI Studio, reduzindo dores de cabeça com faturamento e múltiplas chaves.
*   **Expressividade Aprimorada:** O modelo `Gemini 3.1 Flash TTS` traz novas tags de áudio expressivas, permitindo que o Jarvis tenha controle preciso sobre narração, pausas e tom.
