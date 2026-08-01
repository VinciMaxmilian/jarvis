"""A decisão de permissão, separada de quem a aplica.

`CapabilityPermissions` (o contrato) é o que o manifest **declara**;
`PermissionPolicy` é o que o kernel **decide** a partir da declaração mais o
diretório da capability. A separação existe porque a decisão precisa rodar em
dois lugares muito diferentes: dentro do subprocesso da capability (o guarda de
`open()`/`connect()`) e no processo do kernel (o adapter HTTP, que nem chega a
abrir socket se o host não estiver declarado). Uma classe sem I/O, serializável
em JSON, é o que atravessa a fronteira do processo sem levar o kernel junto.

Três regras que o código sozinho não explica:

- **O diretório da própria capability é sempre gravável.** É o `cwd` do
  subprocesso e o único lugar onde uma capability pode escrever sem declarar
  nada. Consequência que vale registrar: escrever lá muda o digest do
  diretório, e o `discover()` do próximo boot recusa a capability por
  divergência de `approved_commit` (D-3). Isso é o comportamento certo — uma
  capability que reescreve o próprio código é exatamente o que o gate existe
  para pegar.
- **Leitura não é restrita, escrita é.** Restringir leitura significaria negar
  o `open()` da stdlib no import do próprio interpretador. `plan-execution.md`
  §v1.2 pede o wrapper que "levanta em `open()` de escrita fora de
  `permissions.filesystem`", e é isso e só isso.
- **`network: []` é sem rede, não é sem regra.** Lista vazia nega tudo; lista
  com host nega todo o resto. Não existe valor que signifique "libera geral" —
  quem precisa de tudo declara os hosts que usa, ou descobre no primeiro erro
  que não sabia quais eram.

Limite conhecido (`plan-execution.md` §8, R-4): o modelo de ameaça é **erro, não
malícia**. `ctypes`, `os.system` e um `import socket` recarregado passam por
cima disto. O que o guarda pega é o bug de path e a chamada de rede que ninguém
declarou — que é o que de fato acontece quando um modelo escreve a capability.
"""

from __future__ import annotations

import os
import os.path
from pathlib import Path, PurePath

from pydantic import BaseModel, ConfigDict, Field

from packages.shared.contracts import CapabilityPermissions


def _normalizar(caminho: str | PurePath) -> str:
    """Caminho absoluto em forma canônica, sem tocar o disco.

    `resolve()` seria melhor, mas ele consulta o sistema de arquivos e a
    política precisa valer para caminho que ainda não existe — que é o caso
    normal: a capability está prestes a **criar** o arquivo. `normpath` resolve
    `..` e `.` sintaticamente, que é o que pega o erro de path.
    """
    return os.path.normpath(os.path.abspath(caminho))


class PermissionPolicy(BaseModel):
    """Escopo efetivo de uma execução. Imutável e serializável."""

    model_config = ConfigDict(frozen=True)

    capability: str = ""
    #: Raízes graváveis, absolutas e normalizadas. Sempre contém o diretório da
    #: capability (ver docstring do módulo).
    write_roots: tuple[str, ...] = ()
    #: Hosts/IPs alcançáveis. Vazio = sem rede.
    hosts: frozenset[str] = Field(default_factory=frozenset)
    #: Pode iniciar subprocesso externo (`permissions.process` do manifest).
    process: bool = False

    # -- construção -------------------------------------------------------- #

    @classmethod
    def from_manifest(
        cls,
        permissions: CapabilityPermissions,
        *,
        capability_dir: str | Path,
        capability: str = "",
    ) -> PermissionPolicy:
        """Monta a política a partir do manifest e do diretório da capability."""
        raizes = [_normalizar(capability_dir)]
        raizes.extend(_normalizar(p) for p in permissions.filesystem)
        return cls(
            capability=capability,
            write_roots=tuple(dict.fromkeys(raizes)),
            hosts=frozenset(h.strip().lower() for h in permissions.network if h.strip()),
            process=permissions.process,
        )

    # -- decisão ----------------------------------------------------------- #

    def pode_escrever(self, caminho: str | PurePath) -> bool:
        """`True` se o caminho está dentro de alguma raiz gravável.

        Comparação por prefixo **com separador**: sem ele `/dados/nas` liberaria
        `/dados/nas_publico`, que é outro diretório.
        """
        alvo = _normalizar(caminho)
        for raiz in self.write_roots:
            if alvo == raiz or alvo.startswith(raiz.rstrip(os.sep) + os.sep):
                return True
        return False

    def pode_conectar(self, host: str) -> bool:
        """`True` se o host está declarado em `permissions.network`."""
        if not self.hosts:
            return False
        return host.strip().lower() in self.hosts

    @property
    def sem_rede(self) -> bool:
        return not self.hosts


#: Modos de `open()` que escrevem. `r` sozinho é o único que não escreve; `r+`
#: escreve, e é o esquecimento clássico de quem filtra por `"w" in mode`.
MODOS_DE_ESCRITA = frozenset("wxa+")


def modo_escreve(mode: str) -> bool:
    """`True` se o modo de `open()` pode modificar o arquivo."""
    return bool(MODOS_DE_ESCRITA.intersection(mode))


__all__ = ["MODOS_DE_ESCRITA", "PermissionPolicy", "modo_escreve"]
