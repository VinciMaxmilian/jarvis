"""Digest do código em disco de uma capability (D-3).

`plan.md` §6: o registry recusa carregar capability cujo código no disco não bate
com o `approved_commit` do manifest. Sem essa conferência, editar um arquivo já
aprovado e reiniciar o processo instala a mudança sem passar por gate nenhum —
é a porta da automodificação silenciosa, e ela é a razão de a v3 poder existir.

Duas escolhas explicam o resto do módulo:

- **O `manifest.yaml` fica de fora do digest.** É nele que o `approved_commit`
  mora: incluí-lo tornaria o valor impossível de calcular, porque escrever o
  hash mudaria o hash. O que o digest protege é o *código*; o que protege o
  manifest é o `status`, que só o gate move.
- **Digest de conteúdo, não SHA de commit git.** O nome do campo vem do Gate 2
  (`plan.md` §8), mas quem confere é um processo que roda sem git à mão e sobre
  um diretório que pode nem ter virado commit ainda. Conteúdo é o que de fato
  responde à pergunta "isto aqui é o que foi aprovado?"; um SHA de commit
  responde "alguém disse que era", que é outra pergunta. Quem aprova grava o
  retorno de `compute_capability_digest` no manifest.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

#: Metadados da capability. Excluído do digest — ver docstring do módulo.
MANIFEST_FILENAME = "manifest.yaml"

#: Lixo de execução: existe ou não conforme a máquina, e não é código aprovado.
#: Incluí-lo faria a mesma capability ter digest diferente em casa e no trabalho.
DIRETORIOS_IGNORADOS = frozenset(
    {
        "__pycache__",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "node_modules",
    }
)

SUFIXOS_IGNORADOS = frozenset({".pyc", ".pyo"})


def arquivos_do_digest(directory: Path) -> list[Path]:
    """Arquivos que compõem o digest, em ordem estável.

    A ordem é a do caminho relativo em posix: `rglob` não promete ordem, e ordem
    do sistema de arquivos faria o mesmo diretório dar dois digests diferentes.
    """
    raiz = Path(directory)
    escolhidos: list[Path] = []
    for path in raiz.rglob("*"):
        if not path.is_file():
            continue
        relativo = path.relative_to(raiz)
        if DIRETORIOS_IGNORADOS.intersection(relativo.parts[:-1]):
            continue
        if path.suffix in SUFIXOS_IGNORADOS:
            continue
        if relativo.as_posix() == MANIFEST_FILENAME:
            continue
        escolhidos.append(path)
    return sorted(escolhidos, key=lambda p: p.relative_to(raiz).as_posix())


def compute_capability_digest(directory: str | Path) -> str:
    """SHA-256 do conteúdo do diretório da capability, exceto o `manifest.yaml`.

    O caminho relativo e o tamanho de cada arquivo entram no hash junto com o
    conteúdo: sem isso, renomear `a.py` para `b.py` ou mover uma linha de um
    arquivo para o outro daria o mesmo digest, e o que se está tentando detectar
    é exatamente mudança de código.
    """
    raiz = Path(directory)
    h = hashlib.sha256()
    for path in arquivos_do_digest(raiz):
        conteudo = path.read_bytes()
        h.update(path.relative_to(raiz).as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(str(len(conteudo)).encode("ascii"))
        h.update(b"\0")
        h.update(conteudo)
        h.update(b"\0")
    return h.hexdigest()


def integridade_confere(directory: str | Path, approved_commit: str) -> bool:
    """`True` quando o código em disco é exatamente o aprovado."""
    return compute_capability_digest(directory) == approved_commit.strip().lower()


__all__ = [
    "DIRETORIOS_IGNORADOS",
    "MANIFEST_FILENAME",
    "SUFIXOS_IGNORADOS",
    "arquivos_do_digest",
    "compute_capability_digest",
    "integridade_confere",
]
