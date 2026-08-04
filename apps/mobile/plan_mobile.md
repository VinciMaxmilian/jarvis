> ## ⚠️ STATUS: VISÃO FUTURA (v3) — NÃO IMPLEMENTADA
>
> **Este documento não descreve o aplicativo que existe.** Ele é um plano de longo prazo (fase v3) mantido como referência de direção. Nada do RunAnywhere SDK, inferência local ou pipeline de voz on-device está implementado.
>
> **O app real hoje** (`apps/mobile/`) é um **cliente fino do servidor Jarvis**, em Expo / React Native:
> - Autenticação Cloudflare Access via WebView (token em `expo-secure-store`).
> - Chat por WebSocket contra a API; telas de Goals, Brain, History e Settings.
> - Estado em `zustand`, HTTP em `axios`. **Toda** a inferência acontece no servidor.
>
> **Impedimento técnico:** o RunAnywhere SDK exige módulos nativos, ou seja, *dev build* / `expo prebuild`. Isso é **incompatível com o Expo Go**, que é o fluxo de desenvolvimento atual do app. Adotar este plano significa abandonar o Expo Go.
>
> ### Gap para o Gate 1 (aprovação mobile de SPECs de self-evolution)
> O papel mais próximo e mais barato para o mobile é ser o comunicador push do Gate 1. Falta tudo:
> - **Sem `expo-notifications`** — a dependência não está no `package.json`; não há push nem registro de token de device.
> - **Sem tela de aprovação de SPEC** — nenhuma tela lista SPECs pendentes ou emite aprovar/rejeitar.
> - **Sem endpoint no servidor** — a API não expõe rota para listar SPECs pendentes nem para registrar a decisão.
>
> Referência do estado real do projeto: `ESTADO_DO_PROJETO.md` (raiz).

---

# Módulo Mobile – Integração com RunAnywhere SDK

## Objetivo

A versão mobile do J.A.R.V.I.S. utilizará o **RunAnywhere SDK** como camada de inferência local para dispositivos Apple. O objetivo é permitir que o aplicativo execute modelos de IA totalmente offline, utilizando aceleração nativa do hardware (Apple Silicon/Metal), mantendo baixa latência, baixo consumo de energia e uma experiência semelhante a um assistente pessoal.

Esta integração deve servir como base inicial do aplicativo, podendo futuramente ser substituída por uma implementação própria caso seja necessário maior controle sobre a inferência.

---

## Objetivos da integração

* Executar modelos LLM localmente.
* Permitir funcionamento completamente offline.
* Utilizar aceleração nativa do dispositivo.
* Possibilitar troca dinâmica de modelos.
* Suportar streaming de respostas.
* Preparar a arquitetura para múltiplos modelos especializados.

---

## Recursos que deverão ser utilizados do RunAnywhere SDK

### Inferência Local

* Execução de modelos de linguagem.
* Streaming de tokens.
* Gerenciamento automático de memória.
* Download e gerenciamento de modelos.
* Carregamento sob demanda.
* Compatibilidade com modelos GGUF, MLX e formatos suportados pelo SDK.

---

### Pipeline de Voz

O aplicativo deverá utilizar o pipeline completo de voz disponibilizado pelo SDK quando possível.

Fluxo esperado:

Microfone
↓
Speech-to-Text
↓
LLM Local
↓
Tool Calling
↓
Text-to-Speech
↓
Resposta ao usuário

---

### Tool Calling

O modelo local deverá ser capaz de solicitar a execução de funções internas do aplicativo.

Exemplos:

* abrir aplicativos
* criar lembretes
* controlar dispositivos
* executar comandos locais
* consultar memória
* enviar tarefas ao servidor
* iniciar agentes especializados

O LLM nunca executará diretamente ações críticas; toda chamada deverá passar pela camada de autorização do J.A.R.V.I.S.

---

## Arquitetura

### Offline

Usuário
↓
Speech-to-Text
↓
LLM Local (RunAnywhere SDK)
↓
Memory Manager
↓
Tool Manager
↓
Text-to-Speech
↓
Usuário

---

### Online

Usuário
↓
LLM Local
↓
Bridge
↓
Servidor J.A.R.V.I.S.
↓
Agente Supervisor
↓
Agentes Especializados
↓
LanceDB
↓
Ferramentas
↓
Resposta

---

## Seleção Inteligente

O aplicativo deverá decidir automaticamente:

* quando responder localmente;
* quando utilizar o servidor remoto;
* quando utilizar ambos.

Critérios:

* complexidade da tarefa;
* disponibilidade da internet;
* disponibilidade do servidor;
* consumo de bateria;
* desempenho esperado;
* preferência do usuário.

---

## Modelos

O sistema deverá permitir instalação dinâmica de modelos.

Categorias:

* Conversação
* Programação
* Raciocínio
* Tradução
* Visão
* Resumo
* Ferramentas

O usuário poderá definir um modelo padrão ou permitir seleção automática conforme a tarefa.

---

## Gerenciamento de Recursos

O aplicativo deverá monitorar continuamente:

* uso de RAM;
* temperatura;
* consumo de bateria;
* velocidade de inferência;
* tokens por segundo;
* tempo até o primeiro token.

Caso o desempenho caia abaixo do limite definido, o sistema poderá reduzir automaticamente o contexto ou alternar para um modelo mais leve.

---

## Sincronização com o Ecossistema J.A.R.V.I.S.

Quando conectado ao servidor pessoal, o aplicativo poderá sincronizar:

* memória episódica;
* histórico;
* preferências;
* agentes disponíveis;
* ferramentas;
* documentos vetorizados;
* estado das tarefas.

A sincronização deverá ocorrer em segundo plano, preservando a operação offline quando não houver conectividade.

---

## Filosofia da Arquitetura

O J.A.R.V.I.S. Mobile deve ser um assistente autônomo, capaz de funcionar integralmente sem conexão com a internet, utilizando o RunAnywhere SDK como mecanismo de inferência local. Quando um servidor J.A.R.V.I.S. estiver disponível, o aplicativo expandirá automaticamente suas capacidades, delegando tarefas complexas ao ecossistema de agentes sem interromper a experiência do usuário. O objetivo é oferecer uma transição transparente entre processamento local e distribuído, priorizando privacidade, velocidade e inteligência contextual.
