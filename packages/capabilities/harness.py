"""O harness: a prova de que uma capability está inteira, antes de ela rodar de verdade.

`plan-execution.md` §4 chama a v2.0 de "template, scaffold, **contrato de teste**".
Este é o contrato de teste. Toda capability tem um `tests/test_<name>.py` que faz
três linhas:

```python
harness = CapabilityHarness(DIRETORIO, MinhaCapability(permissions=concessao))
relatorio = harness.rodar(CASOS)
assert relatorio.ok, relatorio.resumo()
```

O que ele confere, e por que cada um está aqui:

| Verificação | Por que |
|---|---|
| manifest + permissions carregam | o que não carrega não instala |
| identidade do manifest == da classe | o registry lê o manifest; divergir mente |
| tools e schemas iguais aos do código | o Chief AI chama pelo schema publicado |
| entrypoint importa e é chamável | o kernel só descobriria na primeira execução |
| tudo que as tools exigem está concedido | `plan.md` §8, Gate 2, item 3, barato |
| concessão de rede que nenhuma tool usa | escopo mínimo (`plan.md` §14, aceite da v2) |
| existe `tests/` | capability sem `tests/` não passa do Gate 2 (`plan-scheme.md`) |
| `dry_run` não escreve nada | `plan.md` §9 — a primeira execução é sempre ensaio |
| cada caso executa e casa com o esperado | é o `pytest` verde que o Gate 2 exige |

**O que ele não confere: enforcement.** Negar `open()` fora do escopo é do kernel
(`packages/kernel/permissions`), roda dentro do subprocesso e não tem como ser
observado por um teste em processo. O harness prova a *declaração*; o aceite da
v1.2 prova a *aplicação*. Duplicar aqui daria a sensação de cobertura sem a
cobertura.

Erro contra aviso: erro é o que impede a capability de funcionar ou de ser
avaliada (schema divergente, permissão não concedida, tool sem teste). Aviso é o
que o dono precisa ver e pode aceitar (`approved_commit` ainda nulo, host
concedido e não usado). Aviso que vira erro faz o harness ser desligado; erro que
vira aviso faz o harness ser ignorado.
"""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from packages.capabilities.base import Capability, Ensaio, alvos_nao_concedidos
from packages.capabilities.errors import ManifestInvalido, Problema, formatar
from packages.capabilities.manifest import (
    NOME_PERMISSOES,
    ArquivosDaCapability,
    carregar_arquivos,
    specs_por_nome,
)
from packages.shared.contracts import CapabilityStatus

#: Diretórios que não entram no instantâneo de efeito colateral: são lixo de
#: execução, mudam sozinhos e fariam o `dry_run` parecer ter escrito.
IGNORADOS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})


class CasoDeTool(BaseModel):
    """Uma chamada de tool que a capability promete atender.

    `espera` é subconjunto, não igualdade: um caso que fixa a saída inteira quebra
    quando a tool ganha um campo novo, e aí o teste vira trabalho em vez de rede de
    segurança.
    """

    model_config = ConfigDict(frozen=True)

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    #: Pares que a saída tem de conter. `None` só exige que a chamada funcione.
    espera: dict[str, Any] | None = None
    descricao: str = ""


class Relatorio(BaseModel):
    """O veredito. `ok` é o aceite; `resumo()` é o que o pytest imprime."""

    model_config = ConfigDict(frozen=True)

    capability: str
    erros: tuple[Problema, ...] = ()
    avisos: tuple[Problema, ...] = ()
    tools: tuple[str, ...] = ()
    casos_executados: int = 0

    @property
    def ok(self) -> bool:
        return not self.erros

    def resumo(self) -> str:
        partes = [
            f"capability: {self.capability}",
            f"tools: {', '.join(self.tools) or 'nenhuma'}",
            f"casos executados: {self.casos_executados}",
        ]
        if self.erros:
            partes.append(f"ERROS ({len(self.erros)}):\n{formatar(self.erros)}")
        if self.avisos:
            partes.append(f"avisos ({len(self.avisos)}):\n{formatar(self.avisos)}")
        if not self.erros and not self.avisos:
            partes.append("sem erros nem avisos")
        return "\n".join(partes)


def _instantaneo(raizes: Sequence[Path]) -> dict[str, int]:
    """Caminho relativo → tamanho, de tudo que existe sob as raízes.

    Tamanho e não hash: o que se quer detectar é "o ensaio escreveu", e arquivo
    criado, apagado ou com tamanho diferente já responde isso sem ler o conteúdo
    inteiro de um diretório que pode ter gigabytes.
    """
    estado: dict[str, int] = {}
    for raiz in raizes:
        if not raiz.is_dir():
            continue
        for caminho in raiz.rglob("*"):
            if IGNORADOS.intersection(caminho.parts):
                continue
            if not caminho.is_file():
                continue
            estado[f"{raiz}::{caminho.relative_to(raiz).as_posix()}"] = (
                caminho.stat().st_size
            )
    return estado


class CapabilityHarness:
    """Verifica e exercita uma capability instalada em disco.

    A instância recebida é a que vai ser exercitada, e a concessão dela pode ser
    **diferente** da do manifest: o teste aponta `permissions.filesystem` para um
    `tmp_path`, senão o caso de escrita precisaria do NAS de casa montado. A
    conferência estática usa sempre a concessão do **manifest** — que é a que o
    kernel vai aplicar em produção — e a execução usa a da instância.
    """

    def __init__(self, directory: str | Path, capability: Capability) -> None:
        self.directory = Path(directory)
        self.capability = capability

    # ------------------------------------------------------------------ #
    # estático
    # ------------------------------------------------------------------ #

    def verificar(self) -> Relatorio:
        """Tudo que dá para saber sem chamar uma tool."""
        erros: list[Problema] = []
        avisos: list[Problema] = []
        cap = type(self.capability)

        arquivos = self._carregar(erros)
        if arquivos is not None:
            erros.extend(self._conferir_identidade(arquivos))
            erros.extend(self._conferir_catalogo(arquivos))
            erros.extend(self._conferir_concessao(arquivos))
            erros.extend(self._conferir_entrypoint(arquivos))
            avisos.extend(self._avisos_de_estado(arquivos))
            avisos.extend(self._avisos_de_escopo(arquivos))

        erros.extend(self._conferir_layout())
        avisos.extend(self._avisos_de_layout())

        return Relatorio(
            capability=cap.name,
            erros=tuple(erros),
            avisos=tuple(avisos),
            tools=tuple(d.name for d in cap.declarations()),
        )

    def _carregar(self, erros: list[Problema]) -> ArquivosDaCapability | None:
        try:
            return carregar_arquivos(self.directory)
        except ManifestInvalido as exc:
            erros.extend(exc.problemas)
            return None

    def _conferir_identidade(self, arquivos: ArquivosDaCapability) -> list[Problema]:
        cap = type(self.capability)
        manifest = arquivos.manifest
        problemas: list[Problema] = []
        for campo, no_disco, no_codigo in (
            ("name", manifest.name, cap.name),
            ("version", manifest.version, cap.version),
            ("description", manifest.description, cap.description),
            ("runtime", manifest.runtime, cap.runtime),
        ):
            if no_disco != no_codigo:
                problemas.append(
                    Problema(
                        campo=campo,
                        mensagem=(
                            f"manifest diz {no_disco!r}, a classe diz {no_codigo!r} — "
                            "o registry lê o manifest e o kernel importa a classe"
                        ),
                    )
                )
        return problemas

    def _conferir_catalogo(self, arquivos: ArquivosDaCapability) -> list[Problema]:
        """Tool por tool, schema por schema. É o que o Chief AI usa para escolher."""
        cap = type(self.capability)
        no_disco = specs_por_nome(arquivos.manifest.tools)
        no_codigo = specs_por_nome(cap.tool_specs())
        problemas: list[Problema] = []

        for nome in sorted(set(no_codigo) - set(no_disco)):
            problemas.append(
                Problema(
                    campo=f"tools.{nome}",
                    mensagem="declarada com @tool e ausente do manifest",
                )
            )
        for nome in sorted(set(no_disco) - set(no_codigo)):
            problemas.append(
                Problema(
                    campo=f"tools.{nome}",
                    mensagem=(
                        "no manifest e sem método @tool — o catálogo promete o "
                        "que não existe"
                    ),
                )
            )
        for nome in sorted(set(no_disco) & set(no_codigo)):
            if no_disco[nome] != no_codigo[nome]:
                problemas.append(
                    Problema(
                        campo=f"tools.{nome}",
                        mensagem=(
                            "a ToolSpec do manifest diverge da do código; regere o "
                            "manifest com render_manifest_yaml"
                        ),
                    )
                )
        return problemas

    def _conferir_concessao(self, arquivos: ArquivosDaCapability) -> list[Problema]:
        """O que as tools exigem contra o que o manifest concede."""
        problemas: list[Problema] = []
        for decl in type(self.capability).declarations():
            for kind, target in alvos_nao_concedidos(
                decl.requires, arquivos.permissions
            ):
                problemas.append(
                    Problema(
                        campo=f"permissions.{kind}",
                        mensagem=(
                            f"a tool {decl.name!r} exige {target!r} e o manifest não "
                            "concede — o kernel negaria na primeira execução"
                        ),
                    )
                )
        return problemas

    def _conferir_entrypoint(self, arquivos: ArquivosDaCapability) -> list[Problema]:
        """`modulo:atributo` tem de importar e ser chamável.

        O kernel resolve isto dentro do subprocesso, já com o guarda instalado; um
        entrypoint quebrado vira falha de execução com stack trace de import,
        depois de o Gate 2 ter aprovado. Aqui vira erro de manifest.
        """
        manifest = arquivos.manifest
        if manifest.runtime == "http":
            return []
        modulo_nome, _, atributo = manifest.entrypoint.partition(":")
        if not modulo_nome or not atributo:
            return []  # a forma já foi conferida em carregar_arquivos()
        try:
            modulo = importlib.import_module(modulo_nome)
        except ImportError as exc:
            return [
                Problema(campo="entrypoint", mensagem=f"módulo não importa: {exc}")
            ]
        alvo = getattr(modulo, atributo, None)
        if alvo is None:
            return [
                Problema(
                    campo="entrypoint",
                    mensagem=f"{modulo_nome} não tem o atributo {atributo!r}",
                )
            ]
        if not callable(alvo):
            return [
                Problema(
                    campo="entrypoint",
                    mensagem=f"{manifest.entrypoint} não é chamável",
                )
            ]
        return []

    def _conferir_layout(self) -> list[Problema]:
        """`plan-scheme.md`: capability sem `tests/` não passa do Gate 2."""
        testes = self.directory / "tests"
        arquivos = sorted(testes.glob("test_*.py")) if testes.is_dir() else []
        if not arquivos:
            return [
                Problema(
                    campo="tests/",
                    mensagem=(
                        "nenhum test_*.py — o resultado do pytest é anexo obrigatório "
                        "do Gate 2 (plan.md §8)"
                    ),
                )
            ]
        return []

    def _avisos_de_layout(self) -> list[Problema]:
        if not (self.directory / "docs" / "README.md").is_file():
            return [
                Problema(
                    campo="docs/README.md",
                    mensagem=(
                        "ausente — é onde se diz o que a capability exige de "
                        "credencial"
                    ),
                )
            ]
        return []

    def _avisos_de_estado(self, arquivos: ArquivosDaCapability) -> list[Problema]:
        avisos: list[Problema] = []
        manifest = arquivos.manifest

        if not arquivos.tem_permissions_yaml:
            avisos.append(
                Problema(
                    campo=NOME_PERMISSOES,
                    mensagem=(
                        "ausente — o layout de plan-scheme.md o exige e é por ele que "
                        "o dono lê o escopo. Gere com render_permissions_yaml"
                    ),
                )
            )

        if manifest.status == CapabilityStatus.ACTIVE and not manifest.approved_commit:
            avisos.append(
                Problema(
                    campo="approved_commit",
                    mensagem=(
                        "nulo com status active — o registry carrega, mas nada garante "
                        "que o código em disco é o que passou pelo Gate 2"
                    ),
                )
            )

        if not arquivos.trigger_intents:
            avisos.append(
                Problema(
                    campo="trigger_intent",
                    mensagem=(
                        "ausente — resolve() vai depender só de nome e descrição para "
                        "casar a intenção (plan.md §6)"
                    ),
                )
            )
        return avisos

    def _avisos_de_escopo(self, arquivos: ArquivosDaCapability) -> list[Problema]:
        """Escopo mínimo: concessão que nenhuma tool usa.

        Só rede e subprocesso. `filesystem` de fora de propósito: a raiz de trabalho
        chega pela própria concessão e quase nunca aparece em `requires`, então
        avisar aqui seria avisar sempre — e aviso que aparece sempre não é lido.
        """
        exigido = type(self.capability).requirements()
        usados = {h.strip().lower() for h in exigido.network}
        avisos: list[Problema] = []

        for host in arquivos.permissions.network:
            if host.strip().lower() not in usados:
                avisos.append(
                    Problema(
                        campo="permissions.network",
                        mensagem=(
                            f"{host!r} concedido e nenhuma tool o exige — escopo "
                            "mínimo é o aceite da v2 (plan.md §14)"
                        ),
                    )
                )
        if arquivos.permissions.process and not exigido.process:
            avisos.append(
                Problema(
                    campo="permissions.process",
                    mensagem="concedido e nenhuma tool inicia subprocesso",
                )
            )
        return avisos

    # ------------------------------------------------------------------ #
    # execução
    # ------------------------------------------------------------------ #

    @property
    def escopo_de_escrita(self) -> tuple[Path, ...]:
        """Onde a capability poderia escrever: o diretório dela mais a concessão."""
        raizes = [self.directory]
        raizes.extend(Path(p) for p in self.capability.permissions.filesystem)
        return tuple(raizes)

    def ensaiar(self, caso: CasoDeTool) -> Ensaio:
        """`dry_run` da tool, provando que nada foi escrito.

        A prova é um instantâneo do escopo de escrita antes e depois. Não pega
        efeito fora do escopo declarado — mas efeito fora do escopo é justamente o
        que o guarda do kernel nega, e o que sobra para o harness é o de dentro.
        """
        antes = _instantaneo(self.escopo_de_escrita)
        bruto = self.capability.call(caso.tool, caso.arguments, dry_run=True)
        depois = _instantaneo(self.escopo_de_escrita)
        ensaio = Ensaio.model_validate(bruto)
        if antes != depois:
            raise AssertionError(
                f"dry_run de {self.capability.name}.{caso.tool} mudou o disco: "
                f"{sorted(set(depois.items()) ^ set(antes.items()))}"
            )
        return ensaio

    def executar(self, caso: CasoDeTool) -> dict[str, Any]:
        """A chamada de verdade, sob a concessão da instância."""
        return self.capability.call(caso.tool, caso.arguments)

    def rodar(self, casos: Sequence[CasoDeTool] = ()) -> Relatorio:
        """Verificação estática + ensaio + execução de cada caso."""
        relatorio = self.verificar()
        if not relatorio.ok:
            return relatorio

        erros = list(relatorio.erros)
        avisos = list(relatorio.avisos)
        executados = 0

        for caso in casos:
            try:
                ensaio = self.ensaiar(caso)
                if ensaio.executado:
                    erros.append(
                        Problema(
                            campo=f"tools.{caso.tool}",
                            mensagem="o dry_run executou o handler",
                        )
                    )
                saida = self.executar(caso)
                executados += 1
            except Exception as exc:
                # `Exception` aberto de propósito: qualquer coisa que a tool levante
                # — inclusive o `AssertionError` do ensaio que escreveu — é falha do
                # caso, e o relatório existe para dizer qual caso e por quê. Deixar
                # subir daria um traceback sem o nome do caso.
                erros.append(
                    Problema(
                        campo=f"tools.{caso.tool}",
                        mensagem=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            erros.extend(_conferir_espera(caso, saida))

        avisos.extend(_avisos_de_cobertura(relatorio.tools, casos))

        return relatorio.model_copy(
            update={
                "erros": tuple(erros),
                "avisos": tuple(avisos),
                "casos_executados": executados,
            }
        )


def _conferir_espera(caso: CasoDeTool, saida: dict[str, Any]) -> list[Problema]:
    if caso.espera is None:
        return []
    problemas: list[Problema] = []
    for chave, valor in caso.espera.items():
        if chave not in saida:
            problemas.append(
                Problema(
                    campo=f"tools.{caso.tool}",
                    mensagem=f"a saída não tem a chave {chave!r}: {sorted(saida)}",
                )
            )
        elif saida[chave] != valor:
            problemas.append(
                Problema(
                    campo=f"tools.{caso.tool}",
                    mensagem=f"{chave}: esperava {valor!r}, veio {saida[chave]!r}",
                )
            )
    return problemas


def _avisos_de_cobertura(
    tools: Sequence[str], casos: Sequence[CasoDeTool]
) -> list[Problema]:
    cobertas = {caso.tool for caso in casos}
    return [
        Problema(
            campo=f"tools.{nome}",
            mensagem="nenhum CasoDeTool a exercita — o Gate 2 lê o pytest desta tool",
        )
        for nome in tools
        if nome not in cobertas
    ]


__all__ = [
    "CapabilityHarness",
    "CasoDeTool",
    "Relatorio",
]
