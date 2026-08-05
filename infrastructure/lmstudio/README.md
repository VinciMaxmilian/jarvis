# LM Studio — chat template do Qwen2.5-VL com tool calling

## O problema

O GGUF do `qwen2.5-vl-3b-instruct` (lmstudio-community / bartowski) embute o chat
template original do Qwen2.5-**VL**, que trata imagem e vídeo mas **não tem bloco
`{% if tools %}`**. Sem esse bloco não existe lugar no prompt onde as ferramentas
caibam: o llama.cpp recebe o array `tools` da requisição, não acha onde encaixar e
**descarta em silêncio** — HTTP 200, nenhum erro, nenhum aviso.

O sintoma é o pior possível: o modelo responde com sinceridade que "não tem acesso
ao seu computador". Não é recusa nem alucinação. Do ponto de vista dele é verdade —
ferramenta nenhuma chegou ao prompt.

O modelo em si é capaz: o README do próprio Qwen descreve o Qwen2.5-VL como
"visual agent that can reason and dynamically direct tools, capable of computer
use". O que faltava era o template, não o modelo.

## Como isso foi medido

Duas requisições idênticas ao LM Studio, mudando só a presença de `tools`:

```
SEM tools          prompt_tokens=20
COM tool GIGANTE   prompt_tokens=20     (descrição de 2340 chars ≈ 585 tokens)
```

585 tokens não desaparecem por arredondamento de contador. Isso prova a não
injeção sem depender de interpretar o comportamento do modelo. `tool_choice:
"required"` também não produziu chamada nenhuma — o campo é aceito e ignorado.

## Confirmado funcionando (2026-08-05)

Com o template deste diretório aplicado e o modelo recarregado, a mesma medição:

```
qwen2.5-vl-3b-instruct   SEM tools           prompt_tokens=20
qwen2.5-vl-3b-instruct   COM tool GIGANTE    prompt_tokens=681   <- injetando
google/gemma-3n-e4b      COM tool GIGANTE    prompt_tokens=10    <- ainda descarta
```

E a chamada de verdade, ponta a ponta:

```
tool_calls: 1
  -> desktop_abrir {"alvo":"Microsoft Teams"}
```

**Cuidado ao trocar de modelo.** O conserto é por modelo, porque o template é do
GGUF. O `google/gemma-3n-e4b` não tem bloco de tools no template dele e volta ao
comportamento antigo — o agente responde que não tem acesso ao computador. Se o
Jarvis regredir para esse sintoma, a primeira coisa a checar é qual modelo está
selecionado em `system_settings.model`.

## Como aplicar

1. LM Studio → **My Models** → `qwen2.5-vl-3b-instruct` → **Prompt Template**.
2. Cole o conteúdo de [`qwen2.5-vl-tools.jinja`](qwen2.5-vl-tools.jinja).
3. **Recarregue o modelo** — o template é aplicado no load, não na requisição.

## O que o template faz

Mescla as duas metades que estavam separadas:

- **Visão, do template do VL:** `<|vision_start|><|image_pad|><|vision_end|>` para
  conteúdo em lista, que é como o PWA manda imagem e como o computer use manda
  screenshot. Sem isto o Jarvis perde os olhos.
- **Tools, do template do Qwen2.5-Instruct de texto:** bloco `# Tools` no system,
  `<tool_call>` para o que o assistant pede e `<tool_response>` para o que volta.

Validado renderizando três casos: com tools, sem tools mas com imagem, e o ciclo
completo (assistant chama → tool responde → assistant continua).

## Se não resolver

O controle que isola de vez é rodar o mesmo teste de tokens contra um modelo de
texto do Qwen já servido (`qwen2.5-coder-7b-instruct`), cujo GGUF traz o template
com tools de fábrica:

- tokens sobem lá e não aqui → é o template do VL (este arquivo é a correção);
- não sobem em lugar nenhum → é a configuração do servidor LM Studio, e o template
  não tem culpa.
