"""Registro de **skills declarativas** — procedimento em texto que o Jarvis leu,
escreveu e passa a carregar sozinho quando o assunto volta.

A razão de existir deste módulo é custo de contexto, não organização de arquivo.
Uma skill é um `SKILL.md` inteiro (facilmente 2-4 KB); trinta delas no system
prompt são dezenas de milhares de tokens pagos em **todo** turno, inclusive nos
que não têm nada a ver com o assunto. Por isso a divulgação é progressiva: o
prompt recebe só o `name` + `description` de cada skill (~20 tokens), e o corpo
só entra quando a tool `skill_load` for chamada. Trinta skills custam ~600 tokens
fixos em vez de trinta documentos.

Duas consequências de projeto que valem ser ditas em voz alta:

**Nada aqui pode levantar exceção no caminho de boot.** O `SKILL.md` é escrito
por um LLM a partir de material baixado da web — frontmatter truncado, YAML com
aspa aberta e campo faltando são o caso normal, não a exceção. Uma skill
malformada é *pulada com warning*; derrubar a montagem do prompt por causa de um
arquivo ruim tiraria o Jarvis inteiro do ar por um documento acessório.

**`name` vira caminho de diretório.** O nome vem do modelo, e o modelo vê texto
de terceiros; `../../.ssh` é um nome perfeitamente plausível de sair de um LLM
envenenado. A validação é allow-list (`[a-z0-9-]+`), mesma postura de
`_knowledge_save` em `packages/agents/tools/executor.py`, com a checagem de
contenção do caminho resolvido por cima — cinto e suspensório, porque o custo de
errar aqui é escrita arbitrária em disco.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import structlog
import yaml
from pydantic import BaseModel, ConfigDict, Field

from packages.scheduler.config import SchedulerConfig

logger = structlog.get_logger(__name__)

#: Nome válido de skill. Allow-list, não deny-list: o nome é gerado por LLM e
#: vira componente de caminho, então tudo que não estiver descrito aqui é lixo.
_NOME_VALIDO = re.compile(r"^[a-z0-9-]+$")

#: Teto de leitura do `SKILL.md`. Um procedimento maior que isto não é
#: procedimento, é o corpus colado dentro do arquivo errado — e ele iria inteiro
#: para o contexto no `load()`.
MAX_BYTES = 256 * 1024

#: Cabeçalho do bloco injetado no prompt. Fica aqui e não no `chief.md` porque
#: quem sabe se existe skill alguma é o registry: cabeçalho sem lista embaixo é
#: pior que ausência de cabeçalho — o modelo passa a alucinar skills.
_CABECALHO = "## Skills disponíveis"


class SkillInvalida(ValueError):
    """Nome de skill recusado antes de virar caminho em disco."""


class Skill(BaseModel):
    """Metadado de uma skill. **Sem o corpo**, de propósito.

    O corpo é o que custa contexto e é justamente o que não pode viajar junto
    com a listagem: se ele estivesse neste modelo, `list_descriptions()`
    devolveria os documentos inteiros e a divulgação progressiva viraria
    decoração. Corpo se lê por `SkillRegistry.load(nome)`.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    triggers: list[str] = Field(default_factory=list)
    knowledge_refs: list[str] = Field(default_factory=list)
    created_at: str | None = None
    #: Arquivo de origem. Guardado para que `load()` não precise remontar o
    #: caminho a partir do nome (e portanto não precise confiar no nome).
    path: Path


class SkillRegistry:
    """Varre `data/skills/*/SKILL.md`, valida e serve o que o prompt precisa.

    O cache é invalidado por assinatura de `mtime_ns` + tamanho do conjunto de
    arquivos, não por TTL nem por reinício. A escolha vem do fluxo real: o
    pipeline de pesquisa escreve uma skill nova enquanto a API está de pé, e ela
    tem que aparecer no próximo turno — exigir restart transformaria a única
    parte autônoma do recurso em tarefa manual. O preço é um `glob` + `stat` por
    montagem de prompt, que para dezenas de arquivos é ruído perto de qualquer
    chamada de LLM; o parse de YAML, esse sim caro, só reroda quando algo mudou.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        # Default via `SchedulerConfig` (e não constante local) porque é o mesmo
        # contrato que resolve `knowledge_dir`: caminho relativo é ancorado na
        # raiz do repo, nunca no cwd. O orchestrator e a API sobem com cwd
        # diferentes, e uma skill gravada em cwd errado é uma skill perdida.
        self._base_dir = Path(base_dir) if base_dir is not None else SchedulerConfig().skills_dir
        self._cache: list[Skill] = []
        self._assinatura: tuple[tuple[str, int, int], ...] | None = None

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    # -- leitura ------------------------------------------------------------ #

    def discover(self) -> list[Skill]:
        """Todas as skills válidas, ordenadas por nome. Nunca levanta."""
        assinatura = self._assinar()
        if self._assinatura is not None and assinatura == self._assinatura:
            return list(self._cache)

        skills: list[Skill] = []
        for caminho_str, _, _ in assinatura:
            caminho = Path(caminho_str)
            skill = self._parse(caminho)
            if skill is not None:
                skills.append(skill)

        skills.sort(key=lambda s: s.name)
        self._cache = skills
        self._assinatura = assinatura
        return list(skills)

    def list_descriptions(self) -> list[Skill]:
        """O que entra no prompt: nome + descrição, sem corpo."""
        return self.discover()

    def load(self, nome: str) -> str | None:
        """Corpo do markdown, já sem frontmatter. `None` se não existir.

        Resolve pelo `path` descoberto, não por concatenação com o `nome`
        recebido: o argumento vem do LLM, e comparar contra a lista já validada
        elimina a classe inteira de travessia de caminho em vez de tentar
        filtrá-la.
        """
        alvo = (nome or "").strip().lower()
        for skill in self.discover():
            if skill.name == alvo:
                try:
                    bruto = skill.path.read_text(encoding="utf-8")
                except OSError as exc:
                    logger.warning("skill.load_falhou", skill=alvo, error=str(exc))
                    return None
                return _sem_frontmatter(bruto)
        logger.info("skill.nao_encontrada", skill=alvo)
        return None

    def render_prompt_block(self) -> str:
        """Bloco pronto para concatenar no system prompt.

        String **vazia** quando não há skill: um `## Skills disponíveis` seguido
        de nada é um convite explícito para o modelo inventar nome de skill e
        chamar `skill_load` num alvo inexistente.
        """
        skills = self.discover()
        if not skills:
            return ""

        linhas = [_CABECALHO, ""]
        for skill in skills:
            linha = f"- `{skill.name}` — {skill.description.strip()}"
            if skill.triggers:
                linha += f" (gatilhos: {', '.join(skill.triggers)})"
            linhas.append(linha)
        linhas.append("")
        linhas.append(
            "Só a descrição está acima. Antes de responder sobre um destes assuntos, "
            "chame `skill_load(nome)` para ler o procedimento completo."
        )
        return "\n".join(linhas)

    # -- escrita ------------------------------------------------------------ #

    def save(self, skill: Skill, corpo: str) -> Path:
        """Escreve `<base_dir>/<name>/SKILL.md` com frontmatter. Devolve o caminho.

        Levanta `SkillInvalida` se o nome não passar na allow-list — recusar é
        deliberado em vez de sanitizar em silêncio: `../etc` sanitizado viraria
        `etc`, um nome plausível que esconde do log a tentativa de travessia.
        """
        nome = (skill.name or "").strip()
        if not _NOME_VALIDO.match(nome):
            raise SkillInvalida(
                f"nome de skill inválido: {skill.name!r} (esperado [a-z0-9-]+)"
            )

        destino = (self._base_dir / nome / "SKILL.md").resolve()
        raiz = self._base_dir.resolve()
        # Redundante depois do regex, e é para ser: symlink dentro de `base_dir`
        # muda o destino sem mudar o nome, e o regex não enxerga symlink.
        if raiz not in destino.parents:
            raise SkillInvalida(f"caminho fora de {raiz}: {destino}")

        frontmatter = {
            "name": nome,
            "description": skill.description.strip(),
            "triggers": list(skill.triggers),
            "knowledge_refs": list(skill.knowledge_refs),
            "created_at": skill.created_at or date.today().isoformat(),
        }
        # `sort_keys=False` mantém a ordem acima: o arquivo é lido por humano na
        # revisão do que o Jarvis aprendeu, e `allow_unicode` evita transformar
        # "pseudocódigo" em escape ilegível.
        cabecalho = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            f"---\n{cabecalho}---\n\n{corpo.strip()}\n", encoding="utf-8"
        )

        # Invalida na marra: no Windows a granularidade de `mtime` é grosseira o
        # bastante para uma reescrita no mesmo instante passar despercebida.
        self._assinatura = None
        logger.info("skill.salva", skill=nome, path=str(destino))
        return destino

    # -- internos ----------------------------------------------------------- #

    def _assinar(self) -> tuple[tuple[str, int, int], ...]:
        """Impressão digital do diretório: (caminho, mtime_ns, tamanho) por arquivo."""
        if not self._base_dir.is_dir():
            return ()

        itens: list[tuple[str, int, int]] = []
        for caminho in sorted(self._base_dir.glob("*/SKILL.md")):
            try:
                st = caminho.stat()
            except OSError:  # sumiu entre o glob e o stat
                continue
            itens.append((str(caminho), st.st_mtime_ns, st.st_size))
        return tuple(itens)

    def _parse(self, caminho: Path) -> Skill | None:
        """Lê um `SKILL.md`. Devolve `None` e loga em vez de levantar."""
        try:
            if caminho.stat().st_size > MAX_BYTES:
                logger.warning("skill.arquivo_grande_demais", path=str(caminho))
                return None
            bruto = caminho.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("skill.ilegivel", path=str(caminho), error=str(exc))
            return None

        cru = _extrair_frontmatter(bruto)
        if cru is None:
            logger.warning("skill.sem_frontmatter", path=str(caminho))
            return None

        try:
            dados = yaml.safe_load(cru)
        except yaml.YAMLError as exc:
            logger.warning("skill.yaml_invalido", path=str(caminho), error=str(exc))
            return None

        if not isinstance(dados, dict):
            logger.warning("skill.frontmatter_nao_e_mapa", path=str(caminho))
            return None

        nome = str(dados.get("name") or "").strip().lower()
        descricao = str(dados.get("description") or "").strip()
        if not _NOME_VALIDO.match(nome):
            logger.warning(
                "skill.nome_invalido", path=str(caminho), name=dados.get("name")
            )
            return None
        if not descricao:
            # Sem descrição a skill é invisível no prompt e portanto nunca seria
            # carregada — manter no registry só criaria um item morto.
            logger.warning("skill.sem_descricao", path=str(caminho), name=nome)
            return None

        created_at = dados.get("created_at")
        try:
            return Skill(
                name=nome,
                description=descricao,
                triggers=_lista_de_texto(dados.get("triggers")),
                knowledge_refs=_lista_de_texto(dados.get("knowledge_refs")),
                created_at=str(created_at) if created_at is not None else None,
                path=caminho,
            )
        except Exception as exc:  # pragma: no cover - rede de segurança do pydantic
            logger.warning("skill.invalida", path=str(caminho), error=str(exc))
            return None


# --------------------------------------------------------------------------- #
# Frontmatter
# --------------------------------------------------------------------------- #


def _extrair_frontmatter(texto: str) -> str | None:
    """Devolve o YAML entre os dois `---`, ou `None` se o arquivo não tiver."""
    linhas = texto.lstrip("﻿").splitlines()
    if not linhas or linhas[0].strip() != "---":
        return None
    for i in range(1, len(linhas)):
        if linhas[i].strip() in {"---", "..."}:
            return "\n".join(linhas[1:i])
    # Abriu e não fechou: frontmatter truncado, provavelmente escrita
    # interrompida. Tratar o arquivo inteiro como YAML daria erro pior.
    return None


def _sem_frontmatter(texto: str) -> str:
    """O corpo do markdown. Arquivo sem frontmatter volta inteiro."""
    limpo = texto.lstrip("﻿")
    linhas = limpo.splitlines()
    if not linhas or linhas[0].strip() != "---":
        return limpo.strip()
    for i in range(1, len(linhas)):
        if linhas[i].strip() in {"---", "..."}:
            return "\n".join(linhas[i + 1 :]).strip()
    return limpo.strip()


def _lista_de_texto(valor: object) -> list[str]:
    """Normaliza `triggers`/`knowledge_refs`.

    Aceita lista e string separada por vírgula porque o LLM alterna entre as
    duas formas com frequência, e perder os gatilhos por causa de sintaxe não
    justifica descartar a skill inteira.
    """
    if valor is None:
        return []
    if isinstance(valor, str):
        return [p.strip() for p in valor.split(",") if p.strip()]
    if isinstance(valor, (list, tuple, set)):
        return [str(item).strip() for item in valor if str(item).strip()]
    return [str(valor).strip()]


__all__ = ["MAX_BYTES", "Skill", "SkillInvalida", "SkillRegistry"]
