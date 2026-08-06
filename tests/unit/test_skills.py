"""Testes do `SkillRegistry`.

O caso que carrega mais peso aqui é `test_registry_ignora_malformado`: o
`SKILL.md` é escrito por um LLM a partir de texto baixado da web, então
frontmatter quebrado é ocorrência esperada e não pode derrubar a montagem do
system prompt. Todo o resto do arquivo existe para garantir que a divulgação
progressiva funciona — descrição barata no prompt, corpo caro só sob demanda.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from packages.agents.skills import Skill, SkillInvalida, SkillRegistry


def escrever(base: Path, nome: str, conteudo: str) -> Path:
    caminho = base / nome / "SKILL.md"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(conteudo, encoding="utf-8")
    return caminho


SKILL_COMPLETA = """---
name: logica-de-programacao
description: Fundamentos de lógica — algoritmo, pseudocódigo, condicionais, laços.
triggers: [algoritmo, pseudocódigo, laço]
knowledge_refs: [logica_de_programacao/*]
created_at: 2026-08-06
---

## Quando usar

Quando o dono perguntar sobre algoritmos.

## Fontes

- https://exemplo.com/algoritmos
"""


def test_registry_descobre_skills(tmp_path: Path) -> None:
    escrever(tmp_path, "logica", "---\nname: logica\ndescription: Lógica.\n---\n\ncorpo")
    escrever(tmp_path, "redes", "---\nname: redes\ndescription: Redes.\n---\n\ncorpo")
    # Diretório sem SKILL.md não é skill: pasta de rascunho não pode virar item
    # no prompt.
    (tmp_path / "vazio").mkdir()

    registry = SkillRegistry(base_dir=tmp_path)

    assert [s.name for s in registry.discover()] == ["logica", "redes"]


def test_registry_carrega_frontmatter(tmp_path: Path) -> None:
    caminho = escrever(tmp_path, "logica-de-programacao", SKILL_COMPLETA)

    (skill,) = SkillRegistry(base_dir=tmp_path).discover()

    assert skill.name == "logica-de-programacao"
    assert skill.description.startswith("Fundamentos de lógica")
    assert skill.triggers == ["algoritmo", "pseudocódigo", "laço"]
    assert skill.knowledge_refs == ["logica_de_programacao/*"]
    assert skill.created_at == "2026-08-06"
    assert skill.path == caminho


def test_registry_ignora_malformado(tmp_path: Path) -> None:
    """Quatro formas de arquivo ruim; nenhuma pode contaminar as boas."""
    escrever(tmp_path, "boa", "---\nname: boa\ndescription: Serve.\n---\n\ncorpo")
    escrever(tmp_path, "sem-frontmatter", "# Só markdown, sem cabeçalho\n\ncorpo")
    escrever(tmp_path, "yaml-quebrado", '---\nname: [ aberto\ndescription: "x\n---\n\ncorpo')
    escrever(tmp_path, "sem-nome", "---\ndescription: Falta o nome.\n---\n\ncorpo")
    escrever(tmp_path, "sem-descricao", "---\nname: sem-descricao\n---\n\ncorpo")
    # Frontmatter aberto e nunca fechado — escrita interrompida no meio.
    escrever(tmp_path, "truncado", "---\nname: truncado\ndescription: Nunca fecha.\n")

    registry = SkillRegistry(base_dir=tmp_path)
    skills = registry.discover()

    assert [s.name for s in skills] == ["boa"]
    # E o boot continua: o bloco de prompt sai normal, com a skill que presta.
    assert "boa" in registry.render_prompt_block()


def test_registry_recusa_nome_com_travessia_no_frontmatter(tmp_path: Path) -> None:
    escrever(tmp_path, "malicioso", "---\nname: ../../etc\ndescription: x.\n---\n\ncorpo")

    assert SkillRegistry(base_dir=tmp_path).discover() == []


def test_load_devolve_corpo_sem_frontmatter(tmp_path: Path) -> None:
    escrever(tmp_path, "logica-de-programacao", SKILL_COMPLETA)

    corpo = SkillRegistry(base_dir=tmp_path).load("logica-de-programacao")

    assert corpo is not None
    assert corpo.startswith("## Quando usar")
    assert "name:" not in corpo
    assert "triggers:" not in corpo
    assert "https://exemplo.com/algoritmos" in corpo


def test_load_de_skill_inexistente_devolve_none(tmp_path: Path) -> None:
    registry = SkillRegistry(base_dir=tmp_path)

    assert registry.load("nao-existe") is None
    assert registry.load("../../../etc/passwd") is None


@pytest.mark.parametrize("nome", ["../etc", "nome com espaço", "", "Maiuscula", "a/b"])
def test_save_recusa_nome_invalido(tmp_path: Path, nome: str) -> None:
    registry = SkillRegistry(base_dir=tmp_path)
    skill = Skill(name=nome, description="x", path=tmp_path / "x")

    with pytest.raises(SkillInvalida):
        registry.save(skill, "corpo")

    # Recusa é recusa: nada foi escrito em lugar nenhum.
    assert list(tmp_path.rglob("SKILL.md")) == []


def test_save_escreve_e_e_relido(tmp_path: Path) -> None:
    registry = SkillRegistry(base_dir=tmp_path)
    skill = Skill(
        name="redes-de-computadores",
        description="Camadas, TCP/IP, DNS.",
        triggers=["tcp", "dns"],
        knowledge_refs=["redes/*"],
        created_at="2026-08-06",
        path=tmp_path / "ignorado",
    )

    destino = registry.save(skill, "## Quando usar\n\nQuando perguntarem de rede.")

    assert destino == tmp_path / "redes-de-computadores" / "SKILL.md"
    (relida,) = registry.discover()
    assert relida.name == "redes-de-computadores"
    assert relida.triggers == ["tcp", "dns"]
    assert registry.load("redes-de-computadores") == (
        "## Quando usar\n\nQuando perguntarem de rede."
    )


def test_render_prompt_block_vazio_sem_skills(tmp_path: Path) -> None:
    # Sem cabeçalho órfão: um "## Skills disponíveis" sem lista faz o modelo
    # inventar nome e chamar `skill_load` num alvo que não existe.
    assert SkillRegistry(base_dir=tmp_path).render_prompt_block() == ""
    assert SkillRegistry(base_dir=tmp_path / "nem-existe").render_prompt_block() == ""


def test_render_prompt_block_lista_descricoes(tmp_path: Path) -> None:
    escrever(tmp_path, "logica-de-programacao", SKILL_COMPLETA)

    bloco = SkillRegistry(base_dir=tmp_path).render_prompt_block()

    assert bloco.startswith("## Skills disponíveis")
    assert "`logica-de-programacao`" in bloco
    assert "Fundamentos de lógica" in bloco
    assert "algoritmo" in bloco
    assert "skill_load" in bloco
    # O corpo NÃO vai para o prompt — é este o ponto do recurso inteiro.
    assert "## Quando usar" not in bloco


def test_cache_invalida_por_mtime(tmp_path: Path) -> None:
    escrever(tmp_path, "primeira", "---\nname: primeira\ndescription: Uma.\n---\n\ncorpo")
    registry = SkillRegistry(base_dir=tmp_path)
    assert [s.name for s in registry.discover()] == ["primeira"]

    # Skill nova escrita pelo pipeline enquanto a API está de pé.
    escrever(tmp_path, "segunda", "---\nname: segunda\ndescription: Duas.\n---\n\ncorpo")

    assert [s.name for s in registry.discover()] == ["primeira", "segunda"]

    # E edição de arquivo existente também: `mtime_ns` muda, o parse reroda.
    time.sleep(0.01)
    escrever(tmp_path, "primeira", "---\nname: primeira\ndescription: Editada.\n---\n\nx")
    descricoes = {s.name: s.description for s in registry.discover()}
    assert descricoes["primeira"] == "Editada."

    # Remoção some da lista sem recriar o registry.
    (tmp_path / "segunda" / "SKILL.md").unlink()
    assert [s.name for s in registry.discover()] == ["primeira"]


def test_default_vem_da_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Sem `base_dir`, o caminho sai do `SchedulerConfig` — não hardcoded."""
    monkeypatch.setenv("JARVIS_SKILLS_PATH", str(tmp_path / "custom"))

    assert SkillRegistry().base_dir == tmp_path / "custom"
