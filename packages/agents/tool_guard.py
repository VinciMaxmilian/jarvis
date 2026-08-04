"""Aplicação da `ToolPolicy` de um perfil sobre um `ToolExecutor`.

O perfil declara o que o papel pode chamar; este módulo é o que torna a
declaração verdadeira. São coisas separadas de propósito: `profiles.py` é dado
puro e não conhece a porta de execução, e a checagem mora onde a execução passa.

**Por que envelope e não checagem dentro do agente.** Se o agente perguntasse
"posso?" antes de cada chamada, a restrição valeria só enquanto todo call site
lembrasse de perguntar — e o próximo agente escrito esqueceria. Envelopando o
`ToolExecutor`, o caminho até a tool passa obrigatoriamente pela política: não há
como um perfil chamar o que ele não pode sem trocar o objeto que lhe deram.

**A filtragem de specs é metade do trabalho, não o trabalho todo.** Esconder a
tool do catálogo evita que o modelo a peça, mas modelo alucina nome de tool e
histórico de conversa carrega chamadas de outro papel. Por isso `execute()`
rejeita ANTES de tocar no executor de baixo: o catálogo filtrado é ergonomia, a
recusa em `execute` é a garantia.
"""

from __future__ import annotations

import structlog

from packages.agents.profiles import AgentProfile
from packages.shared.contracts import ToolSpec
from packages.shared.ports import ToolExecutor

logger = structlog.get_logger(__name__)


class ToolDenied(PermissionError):
    """O papel tentou uma tool que a política dele não permite.

    Distinta de `ToolNotFound`: a tool existe e funciona, quem não pode é o
    chamador. Tratar as duas como a mesma coisa faria o log dizer "tool não
    registrada" para uma tool registrada, e o dono procuraria o bug no catálogo.
    """

    def __init__(self, profile: str, tool: str) -> None:
        super().__init__(f"perfil {profile!r} não pode chamar a tool {tool!r}")
        self.profile = profile
        self.tool = tool


class ProfiledToolExecutor:
    """`ToolExecutor` visto através da política de um perfil.

    Satisfaz a mesma porta que envolve, então quem consome não sabe (nem precisa
    saber) que está falando com uma versão restrita do catálogo.
    """

    def __init__(self, inner: ToolExecutor, profile: AgentProfile) -> None:
        self._inner = inner
        self._profile = profile

    @property
    def profile(self) -> AgentProfile:
        return self._profile

    @property
    def inner(self) -> ToolExecutor:
        """O executor envolvido. Exposto para diagnóstico, não para desvio."""
        return self._inner

    def _permitidas(self, specs: list[ToolSpec]) -> list[ToolSpec]:
        return [s for s in specs if self._profile.tools.permite(s.name)]

    def specs(self) -> list[ToolSpec]:
        return self._permitidas(self._inner.specs())

    async def get_all_specs(self) -> list[ToolSpec]:
        """Catálogo completo (sistema + MCP), filtrado.

        Delega ao `get_all_specs` de baixo quando ele existe e cai no `specs()`
        síncrono quando não — é o mesmo `hasattr` que o `ChiefAI` fazia, movido
        para cá para que o agente pare de conhecer as duas formas do catálogo.
        """
        obter = getattr(self._inner, "get_all_specs", None)
        if obter is None:
            return self.specs()
        todas: list[ToolSpec] = await obter()
        return self._permitidas(todas)

    def has(self, name: str) -> bool:
        """`False` para tool negada, mesmo que o executor de baixo a tenha.

        Mentir aqui é intencional: `has()` responde "dá para chamar?", e para
        este perfil não dá. A alternativa — dizer `True` e explodir no
        `execute()` — empurraria a surpresa para o meio da execução.
        """
        return self._profile.tools.permite(name) and self._inner.has(name)

    async def execute(
        self, name: str, arguments: dict[str, object], dry_run: bool = False
    ) -> dict[str, object]:
        if not self._profile.tools.permite(name):
            logger.warning(
                "tool.denied", profile=self._profile.name, tool=name, dry_run=dry_run
            )
            raise ToolDenied(self._profile.name, name)
        return await self._inner.execute(name, arguments, dry_run=dry_run)


def guard_tools(tools: ToolExecutor, profile: AgentProfile) -> ProfiledToolExecutor:
    """Envelopa `tools` na política de `profile`.

    Envelopa sempre, inclusive quando a política libera tudo. Um atalho do tipo
    "se permite tudo, devolve o original" faria o caminho de produção do perfil
    permissivo ser um código diferente do que os testes exercitam, e a diferença
    só apareceria no dia em que alguém apertasse a política.
    """
    return ProfiledToolExecutor(tools, profile)


__all__ = ["ProfiledToolExecutor", "ToolDenied", "guard_tools"]
