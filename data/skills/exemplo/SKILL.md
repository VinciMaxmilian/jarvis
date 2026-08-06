---
name: exemplo
description: Skill de EXEMPLO — só demonstra o formato de um SKILL.md. Não use para responder nada ao dono; se ela for a única coisa que casa com a pergunta, responda sem carregar skill nenhuma.
triggers: [exemplo, formato de skill, modelo de skill]
knowledge_refs: []
created_at: 2026-08-06
---

## Quando usar

Nunca, para responder ao dono. Este arquivo existe como **referência de formato**:
é o molde que a síntese automática (`skill_synthesize`) deve seguir ao escrever
uma skill de verdade a partir do que foi pesquisado.

## Conceitos que eu já estudei

Uma skill real lista aqui os pontos que o corpus cobre, em tópicos curtos — um
por conceito, com o vocabulário que o dono usaria ao perguntar. Serve para eu
saber, ao ler, se o assunto está de fato coberto ou se preciso pesquisar mais.

## Como eu explico isso

Uma skill real descreve aqui o *procedimento*: por onde começar a explicação, que
analogia funciona, que erro comum antecipar, quando mostrar código. É a parte que
justifica o custo de carregar o documento — o resto o modelo já sabe.

## Fontes

Nenhuma: este arquivo foi escrito à mão como exemplo, não veio de pesquisa. Uma
skill real cita aqui as URLs curadas e os caminhos em `data/knowledge/<topico>/`
que sustentam o que está escrito acima.

## Regras do formato

- `name` só aceita `[a-z0-9-]+` — vira nome de diretório.
- `description` é o **único** campo que entra no prompt do Chief sempre. Escreva-a
  como "assunto + quando usar", em uma ou duas frases: é por ela que o modelo
  decide chamar `skill_load`.
- O corpo pode ser longo; ele só é lido sob demanda.
