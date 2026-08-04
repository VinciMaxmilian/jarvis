from __future__ import annotations

import datetime
from pathlib import Path
from typing import NoReturn

from capabilities.memory_writer.schemas import (
    EscreverEntrada,
    EscreverSaida,
)
from packages.capabilities import (
    Capability,
    EntradaInvalida,
    PermissaoNaoDeclarada,
    Problema,
    entrypoint,
    permissoes_declaradas,
    tool,
)

DIRETORIO = Path(__file__).resolve().parents[1]


class MemoryWriter(Capability):
    """Guarda anotações na memória de longo prazo."""

    name = "memory_writer"
    version = "0.1.0"
    description = "Guarda informações úteis, preferências ou fatos na base de conhecimento."
    trigger_intents = (
        "salvar uma anotação",
        "lembrar de um fato",
        "guardar preferência",
    )
    runtime = "python"

    def _recusar(self, tool_name: str, campo: str, mensagem: str) -> NoReturn:
        raise EntradaInvalida(
            self.name, tool_name, [Problema(campo=campo, mensagem=mensagem)]
        )

    @tool(
        description="Salva a anotação fornecida de forma permanente.",
        entrada=EscreverEntrada,
        saida=EscreverSaida,
        requires_approval=True,
    )
    def memory_save(self, entrada: EscreverEntrada) -> EscreverSaida:
        if not self.permissions.filesystem:
            raise PermissaoNaoDeclarada(
                "filesystem", "<raiz do conhecimento>", self.name, "memory_save"
            )
        
        knowledge_dir = Path(self.permissions.filesystem[0])
        arquivo = knowledge_dir / "preferencias_usuario.md"
        
        agora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        bloco = f"\n- [{agora}] {entrada.anotacao.strip()}"
        
        try:
            knowledge_dir.mkdir(parents=True, exist_ok=True)
            with open(arquivo, "a", encoding="utf-8") as f:
                f.write(bloco)
        except OSError as exc:
            self._recusar("memory_save", "anotacao", f"falha ao escrever: {exc}")

        return EscreverSaida(sucesso=True, caminho=str(arquivo))


def construir() -> MemoryWriter:
    return MemoryWriter(permissoes_declaradas(DIRETORIO))


main = entrypoint(construir)

__all__ = ["DIRETORIO", "MemoryWriter", "construir", "main"]
