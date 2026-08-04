"""O que a capability `filesystem` faz: ler, escrever e reorganizar arquivos.

É a primeira capability de uso geral do Jarvis, e o que ela tem de diferente de
`exemplo_nas` é a **fronteira dinâmica**. O NAS trabalha numa raiz só, fixada no
manifest. Esta trabalha sobre qualquer caminho que o chamador mandar — e por isso
a pergunta "este caminho está dentro do que o dono concedeu?" deixa de ser
estática e passa a ser feita a cada chamada, em `_resolver()`.

Três camadas, com papéis que não se sobrepõem:

1. **O modelo de entrada** (`schemas/models.py`) recusa `..`, `~` e caminho vazio.
   É onde erro de digitação morre, com o nome do campo na mensagem.
2. **`_resolver()`** normaliza o caminho e o confere contra `permissions.filesystem`
   com `concedido()` — a mesma função que o harness usa para conferir declaração.
   Fora do escopo é `PermissaoNaoDeclarada`, com o caminho negado em `target`.
3. **O guarda do kernel** (`packages/kernel/permissions`) intercepta o `open()` de
   verdade dentro do subprocesso. Ele é a rede de baixo e continua valendo: a
   camada 2 pode ser burlada por symlink criado entre a conferência e a abertura,
   a camada 3 não.

**Nenhum `OSError` sobe cru.** `FileNotFoundError`, `NotADirectoryError`,
`PermissionError` do sistema operacional e afins viram `EntradaInvalida` nomeando
o campo — `caminho`, `origem` ou `destino`. A escolha do erro merece justificativa:
`EntradaInvalida` é o erro do SDK para "o argumento não serve", e "o arquivo que
você pediu não existe" é exatamente isso, do ponto de vista de quem chamou. O
alternativa seria devolver uma saída com `ok: false`, o que obrigaria todo chamador
a conferir um campo que ninguém confere. O erro é o contrato mais honesto.

Sobre `permissions.filesystem` com mais de uma raiz: a **primeira** é a raiz de
trabalho, contra a qual o caminho relativo é resolvido; as demais são alcançáveis
por caminho absoluto. Sem isso, conceder duas pastas seria conceder uma.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import NoReturn

from capabilities.filesystem.schemas import (
    ApagarEntrada,
    ApagarSaida,
    CopiarEntrada,
    CopiarSaida,
    CriarPastaEntrada,
    CriarPastaSaida,
    EntradaInfo,
    EscreverEntrada,
    EscreverSaida,
    LerEntrada,
    LerSaida,
    ListarEntrada,
    ListarSaida,
    MoverEntrada,
    MoverSaida,
)
from packages.capabilities import (
    Capability,
    EntradaInvalida,
    PermissaoNaoDeclarada,
    Problema,
    concedido,
    entrypoint,
    permissoes_declaradas,
    tool,
)

#: Diretório da capability. Derivado de `__file__` e não do `cwd`: o `cwd` é o do
#: kernel no subprocesso e o do pytest no teste, e o manifest tem de ser achado
#: nos dois.
DIRETORIO = Path(__file__).resolve().parents[1]


class SistemaDeArquivos(Capability):
    """Lê, escreve e reorganiza arquivos dentro das pastas concedidas."""

    name = "filesystem"
    version = "0.1.0"
    description = (
        "Lê, escreve, lista, move, copia e apaga arquivos e pastas dentro das "
        "pastas concedidas no manifest."
    )
    trigger_intents = (
        "ler um arquivo",
        "escrever um arquivo",
        "listar arquivos de uma pasta",
        "mover ou renomear um arquivo",
        "copiar um arquivo ou pasta",
        "apagar um arquivo ou pasta",
        "criar uma pasta",
    )
    #: `python` é o adapter que chama `entrypoint(tool, arguments)` em subprocesso
    #: (`packages/kernel/runtime/_child.py`).
    runtime = "python"

    # ------------------------------------------------------------------ #
    # fronteira
    # ------------------------------------------------------------------ #

    @property
    def raiz(self) -> Path:
        """A primeira pasta concedida. É contra ela que o relativo é resolvido.

        Levantar `PermissaoNaoDeclarada` aqui — e não `IndexError` — é o que faz a
        mensagem dizer o conserto: declare `permissions.filesystem` no manifest.
        """
        if not self.permissions.filesystem:
            raise PermissaoNaoDeclarada(
                "filesystem", "<raiz de trabalho>", self.name
            )
        return Path(self.permissions.filesystem[0])

    def _resolver(self, caminho: str, *, tool_name: str) -> Path:
        """Caminho do argumento em caminho absoluto conferido contra a concessão.

        Relativo é resolvido contra `raiz`; absoluto é usado como veio. Os dois
        passam pela mesma conferência, porque a origem do caminho não muda a
        pergunta: ele está dentro do que o dono concedeu?

        `resolve()` não é usado de propósito — ele exige que o caminho exista em
        parte do trajeto e segue symlink, e o que se quer aqui é a forma canônica
        do caminho **pedido**. Seguir symlink é decisão do kernel, que vê a
        chamada de verdade.
        """
        pedido = Path(caminho) if caminho else self.raiz
        alvo = pedido if pedido.is_absolute() else self.raiz / pedido
        alvo = Path(os.path.normpath(os.path.abspath(alvo)))

        if not concedido("filesystem", str(alvo), self.permissions):
            raise PermissaoNaoDeclarada("filesystem", str(alvo), self.name, tool_name)
        return alvo

    def _relativo(self, alvo: Path) -> str:
        """O caminho como o chamador pode reusá-lo na próxima chamada."""
        try:
            return alvo.relative_to(self.raiz).as_posix()
        except ValueError:
            return alvo.as_posix()

    def _recusar(self, tool_name: str, campo: str, mensagem: str) -> NoReturn:
        """Falha de I/O em erro do SDK, nomeando o campo. Nunca `OSError` cru."""
        raise EntradaInvalida(
            self.name, tool_name, [Problema(campo=campo, mensagem=mensagem)]
        )

    # ------------------------------------------------------------------ #
    # tools
    # ------------------------------------------------------------------ #

    @tool(
        description=(
            "Lê o conteúdo de um arquivo de texto dentro das pastas concedidas."
        ),
        entrada=LerEntrada,
        saida=LerSaida,
        idempotent=True,
    )
    def fs_ler(self, entrada: LerEntrada) -> LerSaida:
        alvo = self._resolver(entrada.caminho, tool_name="fs_ler")

        if not alvo.exists():
            self._recusar("fs_ler", "caminho", f"não existe: {alvo}")
        if alvo.is_dir():
            self._recusar(
                "fs_ler", "caminho", f"é uma pasta, não um arquivo: {alvo}"
            )

        tamanho = alvo.stat().st_size
        if tamanho > entrada.max_bytes:
            self._recusar(
                "fs_ler",
                "max_bytes",
                (
                    f"o arquivo tem {tamanho} bytes e o teto pedido é "
                    f"{entrada.max_bytes} — leitura recusada em vez de truncada, "
                    "para o chamador não confundir pedaço com arquivo"
                ),
            )

        try:
            conteudo = alvo.read_text(encoding=entrada.encoding)
        except (OSError, ValueError, LookupError) as exc:
            self._recusar("fs_ler", "caminho", f"não deu para ler {alvo}: {exc}")

        return LerSaida(caminho=str(alvo), conteudo=conteudo, bytes=tamanho)

    @tool(
        description=(
            "Grava texto num arquivo dentro das pastas concedidas, substituindo "
            "ou acrescentando ao fim."
        ),
        entrada=EscreverEntrada,
        saida=EscreverSaida,
    )
    def fs_escrever(self, entrada: EscreverEntrada) -> EscreverSaida:
        alvo = self._resolver(entrada.caminho, tool_name="fs_escrever")
        if alvo.is_dir():
            self._recusar(
                "fs_escrever", "caminho", f"é uma pasta, não um arquivo: {alvo}"
            )

        existia = alvo.exists()
        if entrada.criar_pastas:
            alvo.parent.mkdir(parents=True, exist_ok=True)
        elif not alvo.parent.is_dir():
            self._recusar(
                "fs_escrever",
                "caminho",
                (
                    f"a pasta {alvo.parent} não existe e criar_pastas está "
                    "desligado"
                ),
            )

        modo = "a" if entrada.anexar else "w"
        try:
            with open(alvo, modo, encoding=entrada.encoding, newline="") as arquivo:
                gravados = arquivo.write(entrada.conteudo)
        except (OSError, ValueError, LookupError) as exc:
            self._recusar(
                "fs_escrever", "caminho", f"não deu para gravar {alvo}: {exc}"
            )

        return EscreverSaida(
            caminho=str(alvo), bytes=gravados, criado=not existia
        )

    @tool(
        description=(
            "Lista arquivos e pastas de um diretório concedido, com ou sem "
            "recursão."
        ),
        entrada=ListarEntrada,
        saida=ListarSaida,
        idempotent=True,
    )
    def fs_listar(self, entrada: ListarEntrada) -> ListarSaida:
        alvo = self._resolver(entrada.caminho, tool_name="fs_listar")

        if not alvo.is_dir():
            # Pasta inexistente devolve lista vazia, e não erro: "o disco externo
            # não está montado" é estado do ambiente, não falha da tool — a mesma
            # decisão de `exemplo_nas.nas_listar`.
            return ListarSaida(entradas=[], total=0, truncado=False)

        try:
            achados = sorted(
                alvo.rglob("*") if entrada.recursivo else alvo.iterdir(),
                key=lambda p: p.as_posix(),
            )
        except OSError as exc:
            self._recusar("fs_listar", "caminho", f"não deu para listar {alvo}: {exc}")

        entradas = [
            EntradaInfo(
                nome=p.name,
                caminho=self._relativo(p),
                tipo="pasta" if p.is_dir() else "arquivo",
                bytes=p.stat().st_size if p.is_file() else 0,
            )
            for p in achados[: entrada.limite]
        ]
        return ListarSaida(
            entradas=entradas,
            total=len(entradas),
            truncado=len(achados) > entrada.limite,
        )

    @tool(
        description=(
            "Move ou renomeia um arquivo ou pasta, com origem e destino dentro "
            "das pastas concedidas."
        ),
        entrada=MoverEntrada,
        saida=MoverSaida,
    )
    def fs_mover(self, entrada: MoverEntrada) -> MoverSaida:
        origem = self._resolver(entrada.origem, tool_name="fs_mover")
        destino = self._resolver(entrada.destino, tool_name="fs_mover")

        if not origem.exists():
            self._recusar("fs_mover", "origem", f"não existe: {origem}")
        if destino.exists() and not entrada.sobrescrever:
            self._recusar(
                "fs_mover",
                "destino",
                f"já existe: {destino} — passe sobrescrever para substituir",
            )

        destino.parent.mkdir(parents=True, exist_ok=True)
        try:
            if destino.exists():
                _remover(destino)
            shutil.move(str(origem), str(destino))
        except (OSError, shutil.Error) as exc:
            self._recusar(
                "fs_mover", "destino", f"não deu para mover para {destino}: {exc}"
            )

        return MoverSaida(origem=str(origem), destino=str(destino))

    @tool(
        description=(
            "Copia um arquivo ou uma pasta inteira, com origem e destino dentro "
            "das pastas concedidas."
        ),
        entrada=CopiarEntrada,
        saida=CopiarSaida,
    )
    def fs_copiar(self, entrada: CopiarEntrada) -> CopiarSaida:
        origem = self._resolver(entrada.origem, tool_name="fs_copiar")
        destino = self._resolver(entrada.destino, tool_name="fs_copiar")

        if not origem.exists():
            self._recusar("fs_copiar", "origem", f"não existe: {origem}")
        if destino.exists() and not entrada.sobrescrever:
            self._recusar(
                "fs_copiar",
                "destino",
                f"já existe: {destino} — passe sobrescrever para substituir",
            )

        destino.parent.mkdir(parents=True, exist_ok=True)
        try:
            if origem.is_dir():
                shutil.copytree(origem, destino, dirs_exist_ok=entrada.sobrescrever)
                arquivos = _contar_arquivos(destino)
            else:
                shutil.copy2(origem, destino)
                arquivos = 1
        except (OSError, shutil.Error) as exc:
            self._recusar(
                "fs_copiar", "destino", f"não deu para copiar para {destino}: {exc}"
            )

        return CopiarSaida(
            origem=str(origem), destino=str(destino), arquivos=arquivos
        )

    @tool(
        description=(
            "Apaga um arquivo ou uma pasta dentro das pastas concedidas. Pasta "
            "com conteúdo exige o modo recursivo."
        ),
        entrada=ApagarEntrada,
        saida=ApagarSaida,
        #: O dono aprova antes. É a única tool daqui cujo efeito não tem desfazer:
        #: gravar por cima ainda deixa o arquivo, apagar não deixa nada.
        requires_approval=True,
    )
    def fs_apagar(self, entrada: ApagarEntrada) -> ApagarSaida:
        alvo = self._resolver(entrada.caminho, tool_name="fs_apagar")

        if not alvo.exists():
            if entrada.ausente_ok:
                return ApagarSaida(caminho=str(alvo), apagados=0, ausente=True)
            self._recusar("fs_apagar", "caminho", f"não existe: {alvo}")

        if alvo.is_dir() and not entrada.recursivo and any(alvo.iterdir()):
            self._recusar(
                "fs_apagar",
                "recursivo",
                (
                    f"{alvo} é uma pasta com conteúdo — passe recursivo para "
                    "apagar o que está dentro junto"
                ),
            )

        apagados = _contar_arquivos(alvo) if alvo.is_dir() else 1
        try:
            _remover(alvo)
        except OSError as exc:
            self._recusar("fs_apagar", "caminho", f"não deu para apagar {alvo}: {exc}")

        return ApagarSaida(caminho=str(alvo), apagados=apagados, ausente=False)

    @tool(
        description="Cria uma pasta dentro das pastas concedidas, com os níveis "
        "intermediários que faltarem.",
        entrada=CriarPastaEntrada,
        saida=CriarPastaSaida,
        idempotent=True,
    )
    def fs_criar_pasta(self, entrada: CriarPastaEntrada) -> CriarPastaSaida:
        alvo = self._resolver(entrada.caminho, tool_name="fs_criar_pasta")

        if alvo.exists():
            if not entrada.existe_ok:
                self._recusar("fs_criar_pasta", "caminho", f"já existe: {alvo}")
            if not alvo.is_dir():
                self._recusar(
                    "fs_criar_pasta",
                    "caminho",
                    f"já existe e é um arquivo, não uma pasta: {alvo}",
                )
            return CriarPastaSaida(caminho=str(alvo), criado=False)

        try:
            alvo.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._recusar(
                "fs_criar_pasta", "caminho", f"não deu para criar {alvo}: {exc}"
            )

        return CriarPastaSaida(caminho=str(alvo), criado=True)


def _remover(alvo: Path) -> None:
    """Apaga arquivo ou árvore, sem decidir por quem chamou se pode."""
    if alvo.is_dir():
        shutil.rmtree(alvo)
    else:
        alvo.unlink()


def _contar_arquivos(raiz: Path) -> int:
    """Arquivos sob uma árvore. Só arquivos: pasta vazia não é dado apagado."""
    if raiz.is_file():
        return 1
    return sum(1 for p in raiz.rglob("*") if p.is_file())


def construir() -> SistemaDeArquivos:
    """A capability sob a concessão que está no manifest em disco.

    É a fábrica que o kernel usa. Ela lê o `manifest.yaml` — leitura, que o guarda
    de permissões não restringe (`packages/kernel/permissions/policy.py`) — e monta
    a instância com a concessão que o dono aprovou, nunca com uma inventada aqui.
    """
    return SistemaDeArquivos(permissoes_declaradas(DIRETORIO))


#: O que `manifest.entrypoint` aponta: `atributo(tool, arguments) -> dict`.
main = entrypoint(construir)

__all__ = [
    "DIRETORIO",
    "SistemaDeArquivos",
    "construir",
    "main",
]
