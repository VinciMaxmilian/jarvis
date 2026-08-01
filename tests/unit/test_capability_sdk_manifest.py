"""`manifest.yaml` e `permissions.yaml`: o que o SDK aceita e o que ele recusa.

Os arquivos são escritos em YAML de verdade em diretório temporário, pelo mesmo
motivo de `tests/unit/test_registry.py`: o bug que importa é o do parse e o da
coerência entre os dois arquivos, e mock de `open()` esconde exatamente esses.

A regra que estes testes fixam: **manifest inválido é recusado com erro nomeando
o campo**. Sem o nome do campo, consertar um manifest gerado pela v3 vira leitura
de arquivo inteiro — e é a v3 que vai gerar a maioria deles.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import BaseModel

from packages.capabilities import (
    Capability,
    ManifestInvalido,
    ToolRequirements,
    carregar_arquivos,
    escrever_arquivos,
    manifest_de,
    permissoes_declaradas,
    render_permissions_yaml,
    tool,
)
from packages.shared.contracts import CapabilityPermissions, CapabilityStatus

NOME = "exemplo"


def manifest_base() -> dict[str, Any]:
    return {
        "name": NOME,
        "version": "0.1.0",
        "description": "capability de teste",
        "status": "pending_approval",
        "entrypoint": "capabilities.exemplo.backend.handlers:main",
        "runtime": "python",
        "permissions": {"network": [], "filesystem": [], "process": False},
        "tools": [],
    }


def escrever(
    base: Path,
    *,
    nome_dir: str = NOME,
    manifest: dict[str, Any] | None = None,
    permissoes: dict[str, Any] | None = None,
    bruto: str | None = None,
) -> Path:
    """Cria `<base>/<dir>/` com os arquivos pedidos. Devolve o diretório."""
    diretorio = base / nome_dir
    diretorio.mkdir(parents=True, exist_ok=True)
    if bruto is not None:
        (diretorio / "manifest.yaml").write_text(bruto, encoding="utf-8")
    elif manifest is not None:
        (diretorio / "manifest.yaml").write_text(
            yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    if permissoes is not None:
        (diretorio / "permissions.yaml").write_text(
            yaml.safe_dump(permissoes, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    return diretorio


def campos(exc: ManifestInvalido) -> list[str]:
    return sorted(p.campo for p in exc.problemas)


# --------------------------------------------------------------------------- #
# Caminho feliz
# --------------------------------------------------------------------------- #


def test_manifest_valido_carrega(tmp_path: Path) -> None:
    diretorio = escrever(tmp_path, manifest=manifest_base())

    arquivos = carregar_arquivos(diretorio)

    assert arquivos.manifest.name == NOME
    assert arquivos.manifest.status == CapabilityStatus.PENDING_APPROVAL
    assert arquivos.tem_permissions_yaml is False


def test_trigger_intent_sobrevive_a_carga(tmp_path: Path) -> None:
    """O campo não está no contrato e o pydantic o descartaria em silêncio."""
    dados = manifest_base() | {"trigger_intent": ["listar arquivos", "sincronizar"]}
    diretorio = escrever(tmp_path, manifest=dados)

    assert carregar_arquivos(diretorio).trigger_intents == (
        "listar arquivos",
        "sincronizar",
    )


def test_trigger_intent_aceita_string_solta(tmp_path: Path) -> None:
    dados = manifest_base() | {"trigger_intent": "listar arquivos"}

    arquivos = carregar_arquivos(escrever(tmp_path, manifest=dados))

    assert arquivos.trigger_intents == ("listar arquivos",)


def test_permissions_yaml_espelhado_carrega(tmp_path: Path) -> None:
    dados = manifest_base()
    dados["permissions"] = {
        "network": ["192.168.1.50"],
        "filesystem": ["/mnt/nas"],
        "process": False,
    }
    diretorio = escrever(tmp_path, manifest=dados, permissoes=dados["permissions"])

    arquivos = carregar_arquivos(diretorio)

    assert arquivos.tem_permissions_yaml is True
    assert arquivos.permissions.network == ["192.168.1.50"]


def test_permissoes_declaradas_e_o_atalho_do_entrypoint(tmp_path: Path) -> None:
    dados = manifest_base()
    dados["permissions"] = {
        "network": [],
        "filesystem": ["/mnt/nas"],
        "process": False,
    }
    diretorio = escrever(tmp_path, manifest=dados)

    assert permissoes_declaradas(diretorio).filesystem == ["/mnt/nas"]


# --------------------------------------------------------------------------- #
# Recusa, com o campo nomeado
# --------------------------------------------------------------------------- #


def test_campo_obrigatorio_ausente_nomeia_o_campo(tmp_path: Path) -> None:
    dados = manifest_base()
    del dados["version"]
    diretorio = escrever(tmp_path, manifest=dados)

    with pytest.raises(ManifestInvalido) as exc:
        carregar_arquivos(diretorio)

    assert campos(exc.value) == ["version"]
    assert "version" in str(exc.value)


def test_tipo_errado_dentro_de_permissions_nomeia_o_caminho(tmp_path: Path) -> None:
    """`permissions.network` como string é o erro que gera concessão fantasma."""
    dados = manifest_base()
    dados["permissions"] = {"network": "192.168.1.50", "filesystem": [], "process": False}
    diretorio = escrever(tmp_path, manifest=dados)

    with pytest.raises(ManifestInvalido) as exc:
        carregar_arquivos(diretorio)

    assert campos(exc.value) == ["permissions.network"]


def test_campo_desconhecido_e_recusado_em_vez_de_descartado(tmp_path: Path) -> None:
    """Permissão escrita num campo com nome errado é permissão que ninguém deu."""
    dados = manifest_base() | {"permissoes": {"network": ["tudo"]}}
    diretorio = escrever(tmp_path, manifest=dados)

    with pytest.raises(ManifestInvalido) as exc:
        carregar_arquivos(diretorio)

    assert campos(exc.value) == ["permissoes"]
    assert "desconhecido" in str(exc.value)


def test_transport_renomeado_para_runtime_e_apontado(tmp_path: Path) -> None:
    """O nome antigo carregaria com o runtime default, que é pior que falhar."""
    dados = manifest_base() | {"transport": "mcp_stdio"}
    diretorio = escrever(tmp_path, manifest=dados)

    with pytest.raises(ManifestInvalido) as exc:
        carregar_arquivos(diretorio)

    assert campos(exc.value) == ["transport"]
    assert "runtime" in str(exc.value)


def test_nome_diferente_do_diretorio_e_recusado(tmp_path: Path) -> None:
    """O diretório é a chave em disco e o sufixo da branch `capability/<name>`."""
    diretorio = escrever(tmp_path, nome_dir="outro", manifest=manifest_base())

    with pytest.raises(ManifestInvalido) as exc:
        carregar_arquivos(diretorio)

    assert campos(exc.value) == ["name"]


def test_entrypoint_sem_atributo_e_recusado(tmp_path: Path) -> None:
    dados = manifest_base() | {"entrypoint": "capabilities.exemplo.backend.handlers"}
    diretorio = escrever(tmp_path, manifest=dados)

    with pytest.raises(ManifestInvalido) as exc:
        carregar_arquivos(diretorio)

    assert campos(exc.value) == ["entrypoint"]
    assert "modulo:atributo" in str(exc.value)


def test_entrypoint_de_runtime_http_e_url(tmp_path: Path) -> None:
    """A forma `modulo:atributo` é de quem roda código; http quer URL."""
    dados = manifest_base() | {
        "runtime": "http",
        "entrypoint": "https://nas.local/mcp",
    }

    arquivos = carregar_arquivos(escrever(tmp_path, manifest=dados))

    assert arquivos.manifest.runtime == "http"


def test_manifest_ausente_nomeia_o_arquivo(tmp_path: Path) -> None:
    vazio = tmp_path / NOME
    vazio.mkdir()

    with pytest.raises(ManifestInvalido) as exc:
        carregar_arquivos(vazio)

    assert campos(exc.value) == ["manifest.yaml"]


def test_yaml_quebrado_nomeia_o_arquivo(tmp_path: Path) -> None:
    diretorio = escrever(tmp_path, bruto="name: exemplo\n  version: [")

    with pytest.raises(ManifestInvalido) as exc:
        carregar_arquivos(diretorio)

    assert campos(exc.value) == ["manifest.yaml"]


def test_manifest_que_nao_e_mapa_e_recusado(tmp_path: Path) -> None:
    diretorio = escrever(tmp_path, bruto="- exemplo\n- outro\n")

    with pytest.raises(ManifestInvalido) as exc:
        carregar_arquivos(diretorio)

    assert campos(exc.value) == ["manifest.yaml"]


def test_todos_os_problemas_saem_de_uma_vez(tmp_path: Path) -> None:
    dados = manifest_base() | {"entrypoint": "sem_atributo", "extra": 1}
    del dados["description"]
    diretorio = escrever(tmp_path, nome_dir="outro_nome", manifest=dados)

    with pytest.raises(ManifestInvalido) as exc:
        carregar_arquivos(diretorio)

    # `description` aborta a validação do schema; o resto vem junto na mesma volta.
    assert "description" in campos(exc.value)
    assert "extra" in campos(exc.value)


# --------------------------------------------------------------------------- #
# O espelho: `permissions.yaml`
# --------------------------------------------------------------------------- #


def test_permissions_yaml_divergente_e_erro(tmp_path: Path) -> None:
    """O dono aprova lendo um arquivo e o kernel aplica o outro."""
    dados = manifest_base()
    dados["permissions"] = {"network": [], "filesystem": ["/mnt/nas"], "process": False}
    diretorio = escrever(
        tmp_path,
        manifest=dados,
        permissoes={"network": ["192.168.1.50"], "filesystem": [], "process": True},
    )

    with pytest.raises(ManifestInvalido) as exc:
        carregar_arquivos(diretorio)

    assert campos(exc.value) == ["permissions.yaml"]
    assert "diverge" in str(exc.value)


def test_chave_desconhecida_no_permissions_yaml_e_erro(tmp_path: Path) -> None:
    dados = manifest_base()
    diretorio = escrever(
        tmp_path,
        manifest=dados,
        permissoes={
            "network": [],
            "filesystem": [],
            "process": False,
            "filesystem_write": ["/"],
        },
    )

    with pytest.raises(ManifestInvalido) as exc:
        carregar_arquivos(diretorio)

    assert campos(exc.value) == ["permissions.yaml:filesystem_write"]


def test_render_permissions_yaml_produz_o_espelho_exato(tmp_path: Path) -> None:
    permissoes = CapabilityPermissions(
        network=["192.168.1.50"], filesystem=["/mnt/nas"], process=False
    )
    dados = manifest_base()
    dados["permissions"] = permissoes.model_dump(mode="json")
    diretorio = escrever(tmp_path, manifest=dados)
    (diretorio / "permissions.yaml").write_text(
        render_permissions_yaml(permissoes), encoding="utf-8"
    )

    assert carregar_arquivos(diretorio).tem_permissions_yaml is True


# --------------------------------------------------------------------------- #
# Geração: o manifest sai da classe, não do teclado
# --------------------------------------------------------------------------- #


class Entrada(BaseModel):
    texto: str


class Geradora(Capability):
    name = "geradora"
    version = "1.2.3"
    description = "Capability para exercitar a geração de manifest."
    trigger_intents = ("gerar manifest",)
    runtime = "python"
    dependencies = ("smbprotocol",)

    @tool(
        description="Fala com o NAS.",
        entrada=Entrada,
        requires=ToolRequirements(network=("192.168.1.50",)),
    )
    def falar(self, entrada: Entrada) -> dict[str, str]:
        return {"texto": entrada.texto}


def test_manifest_de_traz_a_declaracao_da_classe() -> None:
    manifest = manifest_de(Geradora, entrypoint="capabilities.geradora.x:main")

    assert manifest.name == "geradora"
    assert manifest.version == "1.2.3"
    assert manifest.runtime == "python"
    assert manifest.dependencies == ["smbprotocol"]
    assert [t.name for t in manifest.tools] == ["falar"]


def test_manifest_de_nao_deixa_o_codigo_se_declarar_aprovado() -> None:
    """`status` e `approved_commit` são do gate, não da classe (plan.md §8)."""
    manifest = manifest_de(Geradora, entrypoint="capabilities.geradora.x:main")

    assert manifest.status == CapabilityStatus.PENDING_APPROVAL
    assert manifest.approved_commit is None


def test_concessao_default_e_o_minimo_que_as_tools_exigem() -> None:
    manifest = manifest_de(Geradora, entrypoint="capabilities.geradora.x:main")

    assert manifest.permissions.network == ["192.168.1.50"]
    assert manifest.permissions.filesystem == []
    assert manifest.permissions.process is False


def test_arquivos_gerados_sao_coerentes_por_construcao(tmp_path: Path) -> None:
    """`escrever_arquivos` + `carregar_arquivos` fecham o ciclo sem intervenção."""
    manifest = manifest_de(
        Geradora,
        entrypoint="capabilities.geradora.backend.handlers:main",
        permissions=CapabilityPermissions(
            network=["192.168.1.50"], filesystem=["/mnt/nas"]
        ),
    )
    diretorio = tmp_path / "geradora"

    escrever_arquivos(
        diretorio, manifest, trigger_intents=Geradora.trigger_intents
    )
    arquivos = carregar_arquivos(diretorio)

    # `created_at`/`updated_at` ficam fora do arquivo de propósito: são default do
    # modelo, e gravá-los faria o diff que o Gate 2 lê mudar a cada geração.
    fora = {"created_at", "updated_at"}
    assert arquivos.manifest.model_dump(exclude=fora) == manifest.model_dump(exclude=fora)
    assert arquivos.tem_permissions_yaml is True
    assert arquivos.trigger_intents == ("gerar manifest",)


def test_manifest_gerado_nao_muda_entre_duas_geracoes(tmp_path: Path) -> None:
    """`created_at` no arquivo faria o diff do Gate 2 mudar sem ninguém editar."""
    manifest = manifest_de(Geradora, entrypoint="capabilities.geradora.x:main")
    um = tmp_path / "um" / "geradora"
    outro = tmp_path / "outro" / "geradora"

    escrever_arquivos(um, manifest)
    escrever_arquivos(
        outro, manifest_de(Geradora, entrypoint="capabilities.geradora.x:main")
    )

    assert (um / "manifest.yaml").read_text(encoding="utf-8") == (
        outro / "manifest.yaml"
    ).read_text(encoding="utf-8")
