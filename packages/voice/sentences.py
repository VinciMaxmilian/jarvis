"""Quebra o texto do LLM em frases sintetizáveis, à medida que ele chega.

**Por que isto existe.** Até a versão anterior, o laço de voz acumulava a resposta
inteira do modelo, mandava tudo de uma vez para o TTS e só então tocava o áudio.
Nada se sobrepunha a nada: o primeiro som saía depois do último token. Cortando
por frase, a frase 1 toca enquanto o modelo ainda escreve a frase 3 — e é daí que
vem a maior parte do ganho de latência percebida, sem trocar de fornecedor.

**Por que não é `text.split(".")`.** Três armadilhas que arruinariam a prosódia:

1. `3.14`, `R$ 1.500` e `08.02` têm ponto no meio de um número. Cortar ali produz
   "três ponto" ... "quatorze" em duas sínteses, com pausa no meio do número.
2. `Dr.`, `Sr.`, `etc.` terminam em ponto sem terminar a frase.
3. Frase de duas palavras sintetizada sozinha soa robótica: o TTS perde a curva
   de entonação do período. Por isso o mínimo de caracteres — frases curtas
   consecutivas são agrupadas em vez de viradas em pedaços separados.
"""

from __future__ import annotations

import re
from typing import Final

#: Fim de frase: pontuação terminal seguida de espaço ou fim do texto.
#: O `(?<!\d)` antes e o `(?!\d)` depois desarmam o caso do número decimal —
#: `3.14` não casa, `custa 3.` casa.
_FIM_DE_FRASE: Final = re.compile(r"(?<!\d)([.!?…]+)(?!\d)(\s+|$)|(\n+)")

#: Abreviações que terminam em ponto sem terminar a frase. Minúsculas; a
#: comparação normaliza. Lista curta de propósito: cada entrada aqui é um caso em
#: que o corte fica pior, e uma lista grande erraria para o outro lado, deixando
#: frase de verdade sem cortar.
_ABREVIACOES: Final = frozenset(
    {
        "dr", "dra", "sr", "sra", "srta", "prof", "profa",
        "etc", "ex", "obs", "pág", "pag", "núm", "num", "no",
        "av", "r", "jr", "ltda", "eua",
    }
)

#: Abaixo disto, não corta: junta com a próxima. Ver armadilha 3 do docstring.
MIN_CARACTERES: Final = 40


def _termina_em_abreviacao(texto: str) -> bool:
    """`True` se o texto termina numa abreviação conhecida seguida de ponto."""
    m = re.search(r"(\w+)\.$", texto.strip())
    if not m:
        return False
    return m.group(1).lower() in _ABREVIACOES


class SentenceBuffer:
    """Acumula tokens e entrega frases prontas para sintetizar.

    Uso:

        buf = SentenceBuffer()
        for token in stream:
            for frase in buf.feed(token):
                await tts(frase)
        for frase in buf.flush():
            await tts(frase)

    `flush()` no fim é obrigatório: a última frase da resposta costuma não ter
    pontuação terminal, e sem o flush ela seria silenciosamente descartada — o
    modo de falha mais chato possível, porque o assistente parece engolir o final.
    """

    def __init__(self, min_caracteres: int = MIN_CARACTERES) -> None:
        self._buffer = ""
        self._min = min_caracteres

    def feed(self, texto: str) -> list[str]:
        """Recebe um pedaço de texto; devolve as frases que fecharam."""
        if not texto:
            return []
        self._buffer += texto
        return self._extrair()

    def flush(self) -> list[str]:
        """Devolve o que sobrou, tenha pontuação ou não. Esvazia o buffer."""
        resto = self._buffer.strip()
        self._buffer = ""
        return [resto] if resto else []

    def _extrair(self) -> list[str]:
        prontas: list[str] = []
        while True:
            match = _FIM_DE_FRASE.search(self._buffer)
            if not match:
                break

            corte = match.end()
            candidata = self._buffer[:corte].strip()

            # Curta demais ou abreviação: não corta aqui, espera mais texto.
            # `_FIM_DE_FRASE` seria reavaliado no mesmo ponto a cada token novo,
            # então basta sair do laço — o próximo `feed` tenta de novo com mais
            # contexto.
            if len(candidata) < self._min or _termina_em_abreviacao(candidata):
                break

            prontas.append(candidata)
            self._buffer = self._buffer[corte:]

        return prontas
