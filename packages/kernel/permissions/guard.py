"""O wrapper que faz a permissão negar de verdade, dentro do subprocesso.

`plan-execution.md` §v1.2: "wrapper que levanta em `open()` de escrita fora de
`permissions.filesystem` e em conexão fora de `permissions.network`". A frase
que resume o módulo: **negação é comportamento observável, não campo em YAML.**
Antes disto, `permissions` era documentação — uma capability com `network: []`
abria socket exatamente como uma que declarasse o mundo inteiro.

Roda no processo da capability, nunca no do kernel: patch em `builtins.open` do
orchestrator negaria escrita do próprio sistema. Quem instala é
`packages/kernel/runtime/_child.py`, depois de o kernel já ter aberto tudo de
que precisava e logo antes de importar o código da capability.

O que é interceptado, e por que cada um:

- `builtins.open` **e** `io.open`: são atributos distintos apontando para a mesma
  função, e `pathlib.Path.open` chama `io.open` — trocar só um deixa o outro
  caminho aberto.
- `os.open`: descritor cru. `os.open(p, os.O_WRONLY)` não passa por
  `builtins.open`.
- `os.remove`/`unlink`/`rmdir`/`mkdir`/`rename`/`replace`/...: apagar e mover não
  são `open()` de escrita, e são escrita.
- `socket.socket.connect`/`connect_ex`: o ponto por onde toda biblioteca HTTP
  passa, do `httpx` ao `urllib`.
- `socket.create_connection` e `socket.getaddrinfo`: negar já na resolução evita
  a consulta DNS sair da máquina só para o connect falhar em seguida.
- `subprocess.Popen`, `os.system`, `os.fork`, `os.exec*`: `permissions.process:
  false` significa "não inicia processo externo".

Cada negação é **registrada** em `negados()` antes de levantar: o aceite da v1.2
é o alvo negado aparecer no log da task, e uma capability que engole a exceção
com `except Exception` apagaria o fato sem esse registro.

Limite conhecido (`plan-execution.md` §8, R-4): o modelo de ameaça é **erro, não
malícia**. `ctypes`, um `importlib.reload(socket)` ou o descritor 3 herdado
passam por cima disto. O que o guarda pega é o bug de path e a chamada de rede
que ninguém declarou — que é o que de fato acontece quando um modelo escreve a
capability.
"""

from __future__ import annotations

import builtins
import io
import os
import socket
import subprocess
from collections.abc import Callable
from typing import Any

from packages.kernel.errors import PermissionDenied
from packages.kernel.permissions.policy import PermissionPolicy, modo_escreve

#: Prefixo por tipo de permissão no registro de negados. Curto porque vai para
#: `Task.error`, que é lido no celular.
PREFIXO = {"filesystem": "fs", "network": "net", "process": "proc"}

#: Alvos negados nesta execução, na ordem em que aconteceram. Módulo-global de
#: propósito: o processo é de uma capability só e morre no fim da execução.
_NEGADOS: list[str] = []

_INSTALADO = False


def negados() -> list[str]:
    """Alvos negados até agora, na ordem: `["fs:/etc/passwd", "net:1.1.1.1:80"]`."""
    return list(_NEGADOS)


def _negar(kind: str, target: str, capability: str) -> PermissionDenied:
    """Registra a negação e devolve o erro, para quem chama levantar."""
    _NEGADOS.append(f"{PREFIXO[kind]}:{target}")
    return PermissionDenied(kind, target, capability)


def install(policy: PermissionPolicy) -> None:
    """Instala os guardas. Idempotente — a segunda chamada não empilha wrapper.

    Não existe `uninstall()`: o processo da capability vive uma execução e morre
    depois dela, e um `uninstall` seria a porta para o código da capability
    desligar o próprio guarda — o oposto do ponto.
    """
    global _INSTALADO
    if _INSTALADO:
        return
    _INSTALADO = True

    _instalar_filesystem(policy)
    _instalar_rede(policy)
    if not policy.process:
        _instalar_processo(policy)


# --------------------------------------------------------------------------- #
# Filesystem
# --------------------------------------------------------------------------- #

#: Funções de `os` que criam, apagam ou movem caminho. Todas conferem **todos**
#: os argumentos posicionais que pareçam caminho: em `rename(a, b)` os dois são
#: escrita, e conferir só o primeiro deixaria mover para fora do escopo passar.
FUNCOES_DE_ESCRITA = (
    "remove",
    "unlink",
    "rmdir",
    "removedirs",
    "mkdir",
    "makedirs",
    "rename",
    "renames",
    "replace",
    "link",
    "symlink",
    "truncate",
    "chmod",
)


def _texto_de_caminho(alvo: object) -> str | None:
    """O argumento em forma de caminho, ou `None` se ele não é um caminho.

    `bytes` é decodificado porque a política compara texto; caminho que não seja
    UTF-8 vira alvo com caractere de substituição, e conferir um alvo ilegível é
    melhor do que deixá-lo passar sem conferência.
    """
    bruto: object = alvo
    if isinstance(bruto, os.PathLike):
        bruto = bruto.__fspath__()
    if isinstance(bruto, bytes):
        return bruto.decode("utf-8", errors="replace")
    if isinstance(bruto, str):
        return bruto
    return None


def _liberado(policy: PermissionPolicy, alvo: object) -> bool:
    """Descritor já aberto (int) passa: quem o abriu já foi conferido."""
    caminho = _texto_de_caminho(alvo)
    if caminho is None:
        return True
    return policy.pode_escrever(caminho)


def _instalar_filesystem(policy: PermissionPolicy) -> None:
    open_original = builtins.open
    os_open_original = os.open

    def open_guardado(file: Any, mode: Any = "r", *args: Any, **kwargs: Any) -> Any:
        if modo_escreve(str(mode)) and not _liberado(policy, file):
            raise _negar("filesystem", str(file), policy.capability)
        return open_original(file, mode, *args, **kwargs)

    def os_open_guardado(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        escrita = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND))
        if escrita and not _liberado(policy, path):
            raise _negar("filesystem", str(path), policy.capability)
        return os_open_original(path, flags, *args, **kwargs)

    builtins.open = open_guardado
    io.open = open_guardado
    os.open = os_open_guardado

    for nome in FUNCOES_DE_ESCRITA:
        _envolver_caminhos(nome, policy)


def _envolver_caminhos(nome: str, policy: PermissionPolicy) -> None:
    """Envolve `os.<nome>`, negando se algum argumento-caminho está fora do escopo."""
    original: Callable[..., Any] | None = getattr(os, nome, None)
    if original is None:  # pragma: no cover — depende da plataforma
        return

    def guardado(*args: Any, **kwargs: Any) -> Any:
        for arg in args:
            if not _liberado(policy, arg):
                raise _negar("filesystem", str(arg), policy.capability)
        return original(*args, **kwargs)

    setattr(os, nome, guardado)


# --------------------------------------------------------------------------- #
# Rede
# --------------------------------------------------------------------------- #


def _host_de(address: object) -> str:
    """Host de um endereço de socket (`(host, port)` ou caminho de socket unix)."""
    if isinstance(address, tuple) and address:
        return str(address[0])
    return str(address)


def _alvo_de(address: object) -> str:
    if isinstance(address, tuple) and len(address) >= 2:
        return f"{address[0]}:{address[1]}"
    return str(address)


def _instalar_rede(policy: PermissionPolicy) -> None:
    connect_original = socket.socket.connect
    connect_ex_original = socket.socket.connect_ex
    create_original = socket.create_connection
    getaddrinfo_original = socket.getaddrinfo

    def conferir(address: object) -> None:
        if not policy.pode_conectar(_host_de(address)):
            raise _negar("network", _alvo_de(address), policy.capability)

    def connect_guardado(self: socket.socket, address: Any) -> None:
        conferir(address)
        connect_original(self, address)

    def connect_ex_guardado(self: socket.socket, address: Any) -> int:
        conferir(address)
        return connect_ex_original(self, address)

    def create_connection_guardado(address: Any, *args: Any, **kwargs: Any) -> Any:
        conferir(address)
        return create_original(address, *args, **kwargs)

    def getaddrinfo_guardado(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
        if not policy.pode_conectar(str(host)):
            raise _negar("network", f"{host}:{port}", policy.capability)
        return getaddrinfo_original(host, port, *args, **kwargs)

    # `socket.socket` passa por uma referência `Any` de propósito: trocar método
    # de classe da stdlib não é expressável no tipo (a assinatura fecha o
    # endereço em `tuple | str | Buffer`, e o guarda precisa aceitar o que a
    # capability passar para poder negá-lo). A alternativa era um `type: ignore`
    # com dois códigos em cada linha, que envelhece pior que esta.
    classe_socket: Any = socket.socket
    classe_socket.connect = connect_guardado
    classe_socket.connect_ex = connect_ex_guardado
    socket.create_connection = create_connection_guardado
    socket.getaddrinfo = getaddrinfo_guardado


# --------------------------------------------------------------------------- #
# Processo
# --------------------------------------------------------------------------- #

FUNCOES_DE_PROCESSO = (
    "system",
    "fork",
    "forkpty",
    "posix_spawn",
    "posix_spawnp",
    "execv",
    "execve",
    "execvp",
    "execvpe",
    "execl",
    "execle",
    "execlp",
    "startfile",
)


def _descrever(args: object) -> str:
    if isinstance(args, (list, tuple)):
        return " ".join(str(a) for a in args)
    return str(args)


def _instalar_processo(policy: PermissionPolicy) -> None:
    def popen_guardado(args: Any = "", *rest: Any, **kwargs: Any) -> Any:
        raise _negar("process", _descrever(args), policy.capability)

    # `subprocess.run`, `call` e `check_output` resolvem `Popen` como global do
    # módulo na hora da chamada, então trocar o atributo cobre os quatro.
    subprocess.Popen = popen_guardado  # type: ignore[misc,assignment]

    for nome in FUNCOES_DE_PROCESSO:
        if getattr(os, nome, None) is None:  # pragma: no cover — plataforma
            continue

        def guardado(*args: Any, __nome: str = nome, **kwargs: Any) -> Any:
            alvo = _descrever(args[0]) if args else __nome
            raise _negar("process", alvo, policy.capability)

        setattr(os, nome, guardado)


__all__ = ["PREFIXO", "install", "negados"]
