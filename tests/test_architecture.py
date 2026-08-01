"""Enforcement mecânico das fronteiras de arquitetura.

`plan-execution.md` §7: invariante que depende de disciplina não é invariante.
Estas quatro regras são as que, quebradas, não dão erro em runtime — o sistema
continua funcionando e a arquitetura morre em silêncio:

1. o Chief AI nunca executa (`plan.md` §4), então não conhece registry nem runtime;
2. `packages/` não importa `apps/` — a dependência é ao contrário, porta em
   `packages`, adaptador em `apps`;
3. `packages/` não importa `sqlalchemy` — persistência é adaptador atrás de porta;
4. `packages/shared/contracts.py` é a raiz e não importa nada do projeto.

A leitura é por `ast`, não por regex nem por import real. Regex casa comentário
e string; import real executa o módulo, o que traz efeito colateral e falha por
dependência ausente em vez de falhar por violação.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGES_DIR = REPO_ROOT / "packages"
CHIEF = PACKAGES_DIR / "agents" / "chief.py"

#: Pacotes de topo do próprio monorepo (ver `[tool.setuptools.packages.find]`).
PROJETO = frozenset({"apps", "packages", "orchestrator", "capabilities"})

IGNORAR = frozenset({"__pycache__", ".venv", "node_modules"})


@dataclass(frozen=True)
class ImportRef:
    """Um import concreto, com o suficiente para o dono achar e apagar."""

    module: str
    path: Path
    line: int

    def __str__(self) -> str:
        try:
            onde = self.path.relative_to(REPO_ROOT).as_posix()
        except ValueError:  # pragma: no cover — caminho fora do repo
            onde = self.path.as_posix()
        # ASCII de propósito: em console cp1252 o pytest escapa a seta unicode e
        # embaralha exatamente a linha que diz onde consertar.
        return f"{onde}:{self.line} -> {self.module}"


def _pacote_do_arquivo(path: Path) -> list[str]:
    """Partes do pacote que contém o arquivo, para resolver import relativo."""
    relativo = path.relative_to(REPO_ROOT)
    return list(relativo.parts[:-1])


def coletar_imports(path: Path, *, source: str | None = None) -> list[ImportRef]:
    """Todos os módulos importados por um arquivo, em nome absoluto pontuado.

    `from . import x` e `from .y import z` são resolvidos contra o caminho do
    arquivo: import relativo que escapa a fronteira conta como violação igual.
    """
    texto = source if source is not None else path.read_text(encoding="utf-8")
    arvore = ast.parse(texto, filename=str(path))
    refs: list[ImportRef] = []

    for node in ast.walk(arvore):
        if isinstance(node, ast.Import):
            for alias in node.names:
                refs.append(ImportRef(alias.name, path, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = _pacote_do_arquivo(path)
                # level=1 é o próprio pacote; cada nível extra sobe um pacote.
                subida = node.level - 1
                prefixo = base[: len(base) - subida] if subida else base
                partes = [*prefixo, *(node.module.split(".") if node.module else [])]
                refs.append(ImportRef(".".join(partes), path, node.lineno))
            elif node.module:
                refs.append(ImportRef(node.module, path, node.lineno))
    return refs


def arquivos_python(raiz: Path) -> list[Path]:
    return sorted(p for p in raiz.rglob("*.py") if not IGNORAR.intersection(p.parts))


def nomes_importados(path: Path, module: str) -> list[str]:
    """`from a.b import c` → `a.b.c`, para pegar `from packages import registry`."""
    arvore = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    saida: list[str] = []
    for node in ast.walk(arvore):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            saida.extend(f"{module}.{a.name}" for a in node.names)
    return saida


def _raiz(module: str) -> str:
    return module.split(".", 1)[0]


def _reporte(titulo: str, violacoes: list[ImportRef]) -> str:
    linhas = "\n".join(f"  - {v}" for v in violacoes)
    return f"{titulo}\n{linhas}"


# --------------------------------------------------------------------------- #
# Sanidade da varredura
# --------------------------------------------------------------------------- #


def test_varredura_encontra_os_arquivos_do_repo() -> None:
    """Teste de arquitetura sobre lista vazia passa sempre e não vale nada."""
    encontrados = arquivos_python(PACKAGES_DIR)
    assert len(encontrados) >= 10, f"varredura suspeita: {encontrados}"
    assert CHIEF.is_file(), f"{CHIEF} não existe — a regra 1 ficou sem alvo"


def test_coletor_resolve_import_absoluto_e_relativo() -> None:
    """O próprio detector é testado: se ele cegar, as 4 regras passam vazias."""
    alvo = REPO_ROOT / "packages" / "agents" / "_sintetico.py"
    fonte = (
        "import os\n"
        "import packages.registry\n"
        "from packages.shared import contracts\n"
        "from . import goal_manager\n"
        "from ..llm.base import LLMProvider\n"
    )

    modulos = {ref.module for ref in coletar_imports(alvo, source=fonte)}

    assert modulos == {
        "os",
        "packages.registry",
        "packages.shared",
        "packages.agents",
        "packages.llm.base",
    }


def test_coletor_nomeia_arquivo_e_linha() -> None:
    """A mensagem de falha tem de dizer onde; sem isso o teste é inútil."""
    alvo = PACKAGES_DIR / "agents" / "_sintetico.py"
    fonte = "import os\n\nimport packages.registry\n"

    ref = next(r for r in coletar_imports(alvo, source=fonte) if "registry" in r.module)

    assert ref.line == 3
    assert str(ref) == "packages/agents/_sintetico.py:3 -> packages.registry"


# --------------------------------------------------------------------------- #
# Regra 1 — o Chief AI nunca executa
# --------------------------------------------------------------------------- #


def _proibido_para_o_chief(module: str) -> bool:
    if module == "packages.registry" or module.startswith("packages.registry."):
        return True
    if module == "packages.kernel" or module.startswith("packages.kernel."):
        return True
    # "runtime" só é proibido dentro do projeto: `typing.runtime_checkable` e
    # afins são import de nome, não de módulo de execução.
    return _raiz(module) in PROJETO and "runtime" in module.lower()


def test_chief_nao_importa_registry_kernel_nem_runtime() -> None:
    refs = coletar_imports(CHIEF)
    # `from packages import registry` é a mesma violação escrita de outro jeito.
    apelidos = [
        ImportRef(nome, CHIEF, ref.line)
        for ref in refs
        if ref.module == "packages"
        for nome in nomes_importados(CHIEF, "packages")
    ]

    violacoes = [r for r in [*refs, *apelidos] if _proibido_para_o_chief(r.module)]

    assert not violacoes, _reporte(
        "plan.md §4: o Chief AI nunca executa — chief.py não pode conhecer "
        "registry, kernel ou runtime. Delegue pela porta ToolExecutor:",
        violacoes,
    )


@pytest.mark.parametrize(
    "module",
    [
        "packages.registry",
        "packages.registry.registry",
        "packages.kernel",
        "packages.kernel.runtime.subprocess_adapter",
        "packages.runtime",
    ],
)
def test_regra_do_chief_reconhece_as_violacoes(module: str) -> None:
    assert _proibido_para_o_chief(module) is True


@pytest.mark.parametrize(
    "module",
    ["typing", "packages.llm.base", "packages.shared.ports", "structlog", "json"],
)
def test_regra_do_chief_nao_tem_falso_positivo(module: str) -> None:
    assert _proibido_para_o_chief(module) is False


# --------------------------------------------------------------------------- #
# Regras 2 e 3 — packages/ não conhece apps/ nem o ORM
# --------------------------------------------------------------------------- #


def test_packages_nao_importa_apps() -> None:
    violacoes = [
        ref
        for path in arquivos_python(PACKAGES_DIR)
        for ref in coletar_imports(path)
        if _raiz(ref.module) == "apps"
    ]

    assert not violacoes, _reporte(
        "A dependência é ao contrário: `packages` define a porta, `apps` fornece "
        "o adaptador. Mova o que é preciso para `packages/shared/ports.py`:",
        violacoes,
    )


def test_packages_nao_importa_sqlalchemy() -> None:
    violacoes = [
        ref
        for path in arquivos_python(PACKAGES_DIR)
        for ref in coletar_imports(path)
        if _raiz(ref.module) == "sqlalchemy"
    ]

    assert not violacoes, _reporte(
        "Persistência é adaptador em `apps/`, atrás de GoalStore/ConversationStore. "
        "`packages` não fala com o ORM:",
        violacoes,
    )


# --------------------------------------------------------------------------- #
# Regra 4 — contracts.py é a raiz
# --------------------------------------------------------------------------- #


def test_contracts_nao_importa_nada_do_projeto() -> None:
    contracts = PACKAGES_DIR / "shared" / "contracts.py"
    violacoes = [
        ref
        for ref in coletar_imports(contracts)
        if _raiz(ref.module) in PROJETO or ref.module == ""
    ]

    assert not violacoes, _reporte(
        "contracts.py é a fonte única e a raiz do grafo de imports: qualquer "
        "dependência interna aqui cria ciclo com quem o consome:",
        violacoes,
    )


def test_ports_so_depende_de_contracts() -> None:
    """A porta pode conhecer o contrato; nada além disso, ou vira implementação."""
    ports = PACKAGES_DIR / "shared" / "ports.py"
    violacoes = [
        ref
        for ref in coletar_imports(ports)
        if _raiz(ref.module) in PROJETO and ref.module != "packages.shared.contracts"
    ]

    assert not violacoes, _reporte(
        "ports.py só pode importar `packages.shared.contracts`:", violacoes
    )
