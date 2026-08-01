"""Bootstrap do subprocesso de uma capability `python`.

Roda como `python -P -B -m packages.kernel.runtime._child <pedido.json>`, com
`cwd` no diretório da capability. Não é API: o nome começa com `_` porque o
único chamador legítimo é `python_runtime.py`, e o contrato entre os dois é o
par de arquivos JSON descrito aqui.

Ordem das quatro operações, que é a parte que importa:

1. **Lê o pedido.** Arquivo, não `argv`: argumento de tool pode ter aspas,
   quebra de linha e megabytes, e nada disso sobrevive à linha de comando.
2. **Abre o arquivo de resultado e segura o descritor.** Antes do guarda. O
   resultado mora fora do escopo de escrita da capability (é do kernel), e se o
   descritor fosse aberto depois, o próprio guarda negaria a escrita — a
   capability rodaria e o resultado se perderia.
3. **Instala o guarda de permissões.** Depois disso, `open()` de escrita e
   `connect()` obedecem ao manifest.
4. **Importa e chama.** O import da capability vem por último de propósito: o
   código dela não pode rodar antes do guarda estar de pé, e `import` executa
   código de módulo.

Contrato do entrypoint (`manifest.entrypoint`): `modulo:atributo`, chamado como
`atributo(tool, arguments)` e devendo devolver um mapa serializável em JSON.
Mapa, e não valor solto, porque `Task.output` é `dict` e embrulhar
automaticamente esconderia o dia em que a capability devolveu `None` por engano.

**`dry_run` é um terceiro argumento opcional**, passado só a quem o declara. O
kernel inspeciona a assinatura do chamável: quem aceita `dry_run` recebe
`atributo(tool, arguments, dry_run=True)` e responde o que faria — qual arquivo,
qual host, qual payload (`plan.md` §9, o `Ensaio` do Capability SDK). Quem não
aceita continua com o contrato de dois argumentos e recebe o ensaio mínimo que o
kernel monta sozinho: importou, resolveu o entrypoint, a tool existe. A diferença
entre os dois é a diferença entre o log do Gate 2 dizer "importou" e dizer "faria
isto", e ela não pode custar a quebra de um entrypoint já escrito.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import sys
import traceback
from typing import IO, Any

#: Nome do parâmetro opcional de ensaio. Fixo: quem escolhe o nome é o contrato
#: entre kernel e capability, não cada autor.
PARAMETRO_DRY_RUN = "dry_run"

#: Códigos de saída. O kernel não depende deles (ele lê o envelope), mas eles
#: são o que aparece no log quando o envelope não chega a ser escrito.
SAIDA_OK = 0
SAIDA_FALHA_CAPABILITY = 1
SAIDA_FALHA_BOOTSTRAP = 2


def _envelope(destino: IO[str], dados: dict[str, Any]) -> None:
    """Grava o envelope e fecha. Falhar aqui é perder a execução inteira."""
    try:
        json.dump(dados, destino, ensure_ascii=False, default=str)
        destino.flush()
        os.fsync(destino.fileno())
    finally:
        destino.close()


def _resolver(entrypoint: str) -> Any:
    """`modulo:atributo` → o objeto chamável."""
    if ":" not in entrypoint:
        raise ValueError(
            f"entrypoint {entrypoint!r} não tem a forma 'modulo:atributo' — "
            "é o que o runtime python precisa para saber o que chamar"
        )
    modulo_nome, _, atributo = entrypoint.partition(":")
    modulo = importlib.import_module(modulo_nome)
    alvo = getattr(modulo, atributo, None)
    if alvo is None:
        raise AttributeError(f"{modulo_nome} não tem o atributo {atributo!r}")
    if not callable(alvo):
        raise TypeError(f"{entrypoint} não é chamável")
    return alvo


def _aceita_dry_run(alvo: Any) -> bool:
    """`True` se o chamável declara `dry_run` (ou aceita `**kwargs`).

    Assinatura ilegível (built-in, objeto em C) conta como "não aceita": o
    ensaio mínimo é sempre seguro, e chamar com um argumento a mais um chamável
    que não o declara faria a primeira execução de toda capability nova morrer
    de `TypeError` — exatamente onde ela não pode ter efeito nenhum.
    """
    try:
        parametros = inspect.signature(alvo).parameters
    except (TypeError, ValueError):
        return False
    for parametro in parametros.values():
        if parametro.kind is inspect.Parameter.VAR_KEYWORD:
            return True
        if parametro.name == PARAMETRO_DRY_RUN and parametro.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            return True
    return False


def _ensaio_minimo(pedido: dict[str, Any]) -> dict[str, Any]:
    """O que o kernel sabe sozinho quando o entrypoint não faz ensaio.

    Não chama o handler. `plan-execution.md` §7 — a primeira execução de uma
    capability nova é sempre `dry_run`, e ela não pode ter efeito.
    """
    return {
        "dry_run": True,
        "executado": False,
        "entrypoint": pedido["entrypoint"],
        "tool": pedido["tool"],
        "carregado": True,
        # Explícito para o log do Gate 2 não confundir "a capability disse que
        # não faria nada" com "a capability não sabe dizer o que faria".
        "ensaio_detalhado": False,
    }


def _serializavel(valor: object) -> dict[str, Any]:
    if not isinstance(valor, dict):
        raise TypeError(
            f"o handler devolveu {type(valor).__name__}; o contrato é um mapa "
            "JSON-serializável, que é o formato de Task.output"
        )
    json.dumps(valor)  # levanta agora, com o objeto à mão, e não no kernel
    return valor


def main(argv: list[str]) -> int:
    if len(argv) != 2:  # pragma: no cover — só se o kernel montar o argv errado
        print("uso: _child <pedido.json>", file=sys.stderr)
        return SAIDA_FALHA_BOOTSTRAP

    with open(argv[1], encoding="utf-8") as f:
        pedido: dict[str, Any] = json.load(f)

    # Passo 2: o descritor tem de existir antes do guarda (ver docstring). Sem
    # `with` de propósito: o arquivo tem de sobreviver à instalação do guarda e
    # à chamada do handler, e quem o fecha é `_envelope`, no fim das duas.
    destino: IO[str] = open(  # noqa: SIM115 — ver comentário acima
        pedido["result_path"], "w", encoding="utf-8"
    )

    # Import tardio: `guard` tem efeito colateral global no processo, e o
    # processo só existe para esta execução.
    from packages.kernel.permissions.guard import install, negados
    from packages.kernel.permissions.policy import PermissionPolicy

    policy = PermissionPolicy.model_validate(pedido["policy"])
    install(policy)

    try:
        alvo = _resolver(str(pedido["entrypoint"]))
        tool = pedido["tool"]
        argumentos = pedido.get("arguments") or {}
        saida: dict[str, Any]
        if not pedido.get("dry_run"):
            saida = _serializavel(alvo(tool, argumentos))
        elif _aceita_dry_run(alvo):
            saida = _serializavel(alvo(tool, argumentos, dry_run=True))
        else:
            saida = _ensaio_minimo(pedido)
    except Exception as exc:
        _envelope(
            destino,
            {
                "ok": False,
                "error": str(exc) or type(exc).__name__,
                "error_type": type(exc).__name__,
                "denied": negados(),
                "traceback": "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                )[-4000:],
            },
        )
        return SAIDA_FALHA_CAPABILITY

    _envelope(destino, {"ok": True, "output": saida, "denied": negados()})
    return SAIDA_OK


if __name__ == "__main__":  # pragma: no cover — o teste roda o processo inteiro
    sys.exit(main(sys.argv))
