"""Casamento determinístico de intenção contra o catálogo (D-1).

`plan.md` §6: `resolve()` casa a intenção da tarefa contra as capabilities
`active`. **É código determinístico — matching sobre o catálogo, não julgamento
do modelo.** O motivo não é economia de token: se o LLM decidisse, o mesmo
pedido resolveria hoje e daria miss amanhã, e o gatilho da auto-evolução (o
miss) deixaria de ser confiável. Aqui, a mesma entrada dá a mesma saída em
qualquer máquina e sem modelo nenhum rodando.

O que entra no catálogo de uma capability, do mais forte ao mais fraco:

- `name`, `tools[].name` e `trigger_intents` casam a **frase inteira** e dão
  acerto direto: é o nome que quem chama já sabe.
- os tokens dessas mesmas fontes pesam 1.0 — identificador é escolhido para
  descrever.
- os tokens de `description` e `tools[].description` pesam 0.5 — prosa acerta o
  assunto e erra o verbo.

**Errar para o lado do miss é de propósito.** Miss bloqueia o goal e pede
capability nova — caro, mas visível e reversível. Acerto errado executa a
capability errada com os argumentos de outra, e isso escreve em disco. Daí o
limiar exigir que a maioria dos tokens significativos da intenção esteja no
catálogo, e não "algum".
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

import structlog

from packages.shared.contracts import CapabilityManifest

logger = structlog.get_logger(__name__)

#: Fração dos tokens significativos da intenção que precisa estar no catálogo.
#: 0.6 deixa passar "sincronizar arquivos com o NAS" contra uma capability cujo
#: nome é `nas_sync` e cuja descrição fala de arquivos, e barra pedido que só
#: encosta em uma palavra ("mandar o relatório para o NAS" não é sincronizar).
LIMIAR_COBERTURA = 0.6

#: Peso de token que aparece em identificador (nome, tool, trigger_intent).
PESO_FORTE = 1.0
#: Peso de token que só aparece em prosa (description).
PESO_FRACO = 0.5

#: Comprimento mínimo para casar por prefixo. Abaixo disso o prefixo é ruído
#: ("nas" casaria "nasa"); a partir daí ele resolve flexão verbal do português
#: sem stemmer ("sincronizar" ↔ "sincroniza"), que é o caso real.
MINIMO_PREFIXO = 5

#: Palavras que não distinguem uma capability de outra. Lista curta e fechada
#: por dois motivos: stopword demais apaga o sentido do pedido ("sem" e "não"
#: invertem a intenção), e as contrações `na/nas/no/nos` colidem com sigla do
#: próprio domínio — "NAS" é o alvo da primeira capability do sistema, e
#: descartá-lo transformaria "sincronizar com o NAS" em um pedido sem assunto.
STOPWORDS = frozenset(
    (
        "a", "as", "ao", "aos", "com", "da", "das", "de", "do", "dos", "e",
        "em", "o", "os", "para", "pelo", "pela", "por", "que", "um", "uma",
        "the", "to", "of", "for", "and", "with",
    )
)


def normalizar(texto: str) -> list[str]:
    """Tokens minúsculos, sem acento, quebrados em qualquer não-alfanumérico.

    `sync_files`, `sync-files` e `Sync Files` viram a mesma lista: separador de
    identificador é convenção de quem escreveu o manifest, não parte do nome.
    """
    plano = unicodedata.normalize("NFKD", texto.casefold())
    sem_acento = "".join(c for c in plano if not unicodedata.combining(c))
    tokens: list[str] = []
    atual: list[str] = []
    for char in sem_acento:
        if char.isalnum():
            atual.append(char)
        elif atual:
            tokens.append("".join(atual))
            atual = []
    if atual:
        tokens.append("".join(atual))
    return tokens


def frase(texto: str) -> str:
    """Forma canônica para comparação exata: tokens normalizados, separados por
    espaço. `nas_sync`, `NAS-Sync` e `nas sync` colapsam na mesma frase."""
    return " ".join(normalizar(texto))


def tokens_significativos(texto: str) -> list[str]:
    """Tokens de `normalizar()` sem stopword e sem token de um caractere."""
    return [t for t in normalizar(texto) if len(t) > 1 and t not in STOPWORDS]


def casa(a: str, b: str) -> bool:
    """Igualdade, ou prefixo suficientemente longo (flexão verbal e plural)."""
    if a == b:
        return True
    if len(a) >= MINIMO_PREFIXO and b.startswith(a):
        return True
    return len(b) >= MINIMO_PREFIXO and a.startswith(b)


@dataclass(frozen=True)
class CatalogIndex:
    """O que de uma capability entra no casamento. Pré-calculado no `discover()`.

    Frozen e sem referência ao manifest de propósito: o índice é derivado, e
    índice que aponta para o objeto vivo silenciosamente desatualiza quando o
    manifest é recarregado.
    """

    name: str
    #: Frases para acerto direto: nome da capability, nome de cada tool, cada
    #: entrada de `trigger_intents`.
    frases: frozenset[str]
    #: Tokens vindos dessas mesmas fontes.
    fortes: frozenset[str]
    #: Tokens vindos de `description` e das descrições das tools.
    fracos: frozenset[str]

    def cobertura(self, tokens: Sequence[str]) -> float:
        """Fração ponderada dos tokens da intenção presentes no catálogo."""
        if not tokens:
            return 0.0
        total = 0.0
        for token in tokens:
            if any(casa(token, alvo) for alvo in self.fortes):
                total += PESO_FORTE
            elif any(casa(token, alvo) for alvo in self.fracos):
                total += PESO_FRACO
        return total / len(tokens)


def build_index(manifest: CapabilityManifest) -> CatalogIndex:
    """Monta o índice de casamento de uma capability.

    Tudo vem do manifest, inclusive `trigger_intents`: enquanto o campo vivia
    fora do contrato, quem chamasse esta função sem passar a lista à parte
    construía um índice silenciosamente pior do que o do registry.
    """
    identificadores = [manifest.name, *(t.name for t in manifest.tools)]
    intents = list(manifest.trigger_intents)
    frases = {frase(x) for x in [*identificadores, *intents] if frase(x)}

    fortes: set[str] = set()
    for texto in [*identificadores, *intents]:
        fortes.update(tokens_significativos(texto))

    fracos: set[str] = set()
    for texto in [manifest.description, *(t.description for t in manifest.tools)]:
        fracos.update(tokens_significativos(texto))
    fracos -= fortes

    return CatalogIndex(
        name=manifest.name,
        frases=frozenset(frases),
        fortes=frozenset(fortes),
        fracos=frozenset(fracos),
    )


def match_intent(intent: str, entries: Sequence[CatalogIndex]) -> str | None:
    """Nome da capability que atende a intenção, ou `None` (miss).

    Empate é resolvido pelo nome em ordem alfabética **e registrado em log**:
    determinismo é obrigatório, mas duas capabilities disputando o mesmo pedido
    é catálogo mal recortado, e isso precisa aparecer para alguém.
    """
    alvo = frase(intent)
    if not alvo or not entries:
        return None

    exatos = sorted(e.name for e in entries if alvo in e.frases)
    if exatos:
        _avisar_ambiguidade(intent, exatos, exato=True)
        return exatos[0]

    tokens = tokens_significativos(intent)
    if not tokens:
        return None

    pontuados = sorted(
        ((e.cobertura(tokens), e.name) for e in entries),
        key=lambda par: (-par[0], par[1]),
    )
    melhor, nome = pontuados[0]
    if melhor < LIMIAR_COBERTURA:
        return None

    empatados = [n for pontos, n in pontuados if pontos == melhor]
    _avisar_ambiguidade(intent, empatados, exato=False)
    return nome


def _avisar_ambiguidade(intent: str, candidatos: list[str], *, exato: bool) -> None:
    if len(candidatos) > 1:
        logger.warning(
            "capability.intencao_ambigua",
            intent=intent,
            candidatos=candidatos,
            escolhida=candidatos[0],
            criterio="frase_exata" if exato else "cobertura",
        )


__all__ = [
    "LIMIAR_COBERTURA",
    "STOPWORDS",
    "CatalogIndex",
    "build_index",
    "casa",
    "frase",
    "match_intent",
    "normalizar",
    "tokens_significativos",
]
