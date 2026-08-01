"""Perfil de tarefa → modelo. Um modelo por tipo de trabalho, não um por sistema.

Antes disto havia um `LMSTUDIO_MODEL` só, e toda chamada — planejar, classificar,
gerar código, embutir texto — ia para ele. Isso desperdiça das duas pontas: paga
um modelo grande para classificar uma frase e entrega um modelo pequeno para o
trabalho que precisa de contexto longo. O mapa aqui existe para que a escolha do
modelo seja uma propriedade DA TAREFA, não da máquina que está ligada hoje.

**Por que este módulo é uma função pura e não conhece `Settings` nem `deps`.**
A resolução precisa rodar em três lugares com origens de dados diferentes: no
wiring do FastAPI (que tem `Settings`), no orchestrator (que não passa por HTTP) e
no teste (que não tem nem um nem outro). Recebendo override, default e roster
como argumentos, `resolve_model` é testável sem rede, sem `.env` e sem import
circular — `deps.py` importa `packages.llm`, então o contrário nunca pode existir.

**A degradação é o requisito, não o caminho feliz.** O dono tem duas máquinas: a
do trabalho serve LM Studio com o roster abaixo; a de casa vai usar a API do
Gemini e não tem NENHUM destes modelos. Por isso nenhum id de modelo daqui pode
ser tratado como garantido. A cadeia é, nesta ordem:

    1. override explícito do dono (`LMSTUDIO_MODEL_<PERFIL>` no .env);
    2. o mapa `PROFILE_MODELS[provider][perfil]`;
    3. `FALLBACK_MODEL` (`google/gemma-4-e2b`), o fallback declarado pelo dono;
    4. o modelo default do próprio provider.

Os passos 1 e 2 são específicos do provider: se o roster for desconhecido, valem
por confiança (foi o dono, ou fomos nós, que os declararam PARA ESTE provider). O
passo 3 é o único candidato provider-agnóstico e por isso é o único que EXIGE
PROVA: `gemma-4-e2b` só entra quando o roster é conhecido e o contém. Sem essa
regra, `CHIEF_PROVIDER=gemini` sem roster resolveria todo perfil para um modelo do
LM Studio e a máquina de casa quebraria em toda geração — que é exatamente o
"escolher errado em silêncio" que este módulo existe para impedir. O passo 4 é
terminal e sempre aceito: é o contrato do próprio provider, não há nada melhor.

Nada aqui levanta exceção. Perfil que não pode ser servido degrada com log e
segue; erro de import ou 500 por causa de um perfil seria trocar um problema de
qualidade de modelo por uma indisponibilidade total.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Mapping
from typing import Final, Literal, get_args

from pydantic import BaseModel

logger = logging.getLogger(__name__)

#: Os seis tipos de trabalho que o sistema distingue hoje.
#:
#: `chief`  — planejar, chamar tool, raciocinar em contexto longo (baixo volume).
#: `cheap`  — classificar, resumir, rotear (alto volume, resposta curta).
#: `code`   — geração de capability da v3 (`plan.md`), prompt do tamanho de um repo.
#: `embed`  — vetorizar para busca semântica.
#: `rerank` — reordenar candidatos de busca.
#: `vision` — ler imagem/screenshot.
#:
#: NÃO existem perfis `stt`, `tts` e `ocr` mesmo com whisper, kokoro e paddleocr no
#: roster: nenhum deles é alcançável pelo `LLMProvider` (não são chat completions),
#: e perfil que nada consegue chamar é entrada morta num mapa que precisa ser lido
#: como verdade. Quando existir uma porta de áudio, o perfil nasce com ela.
TaskProfile = Literal["chief", "cheap", "code", "embed", "rerank", "vision"]

#: Ordem estável para a UI e para os testes; a mesma do Literal.
TASK_PROFILES: Final[tuple[str, ...]] = get_args(TaskProfile)

#: Fallback declarado pelo dono para todo perfil não mapeado ou não servido.
#: `type=vlm`, 131072 de contexto, `e2b` (poucos parâmetros ativos) — cabe junto
#: com os outros na VRAM e aguenta texto e imagem. Escolha do dono, não sugestão.
FALLBACK_MODEL: Final = "google/gemma-4-e2b"

#: Mapa por PROVIDER, nunca global. `openai`/`local` apontam para outro backend
#: OpenAI-compatible (vLLM, Koboldcpp, a OpenAI de verdade) que não serve estes
#: ids; herdar o mapa do LM Studio lá dentro seria escolher errado em silêncio.
#: Provider sem entrada aqui não é erro — é um provider que resolve tudo pelo seu
#: próprio default, que é o caso do `gemini` na máquina de casa.
#:
#: Justificativa de cada escolha, medida em `GET /api/v0/models` do LM Studio
#: (campos `type`, `max_context_length`, `state`), não adivinhada:
#:
#: | perfil | modelo                              | por quê                          |
#: |--------|-------------------------------------|----------------------------------|
#: | chief  | qwen3-vl-8b-instruct                | 262144 de contexto, o maior do   |
#: |        |                                     | roster, e o maior modelo geral    |
#: |        |                                     | presente (8B); já `loaded`.       |
#: | cheap  | google/gemma-4-e2b                  | menor modelo do roster e já o     |
#: |        |                                     | fallback: volume alto não gasta   |
#: |        |                                     | VRAM extra nem tempo de load.     |
#: | code   | deepseek-coder-v2-lite-instruct     | único especializado em código;    |
#: |        |                                     | 163840 de contexto cabe um repo.  |
#: |        |                                     | `not-loaded` custa latência no    |
#: |        |                                     | primeiro request (o LM Studio     |
#: |        |                                     | carrega sob demanda), não erro.   |
#: | embed  | text-embedding-qwen3-embedding-0.6b | único `type=embeddings` carregado;|
#: |        |                                     | 1024 dimensões verificadas em     |
#: |        |                                     | `POST /v1/embeddings`. O nomic    |
#: |        |                                     | perde: 2048 de contexto e frio.   |
#: | rerank | qwen3-reranker-0.6b                 | único reranker do roster.         |
#: | vision | qwen3-vl-8b-instruct                | `type=vlm` com 262144 de contexto;|
#: |        |                                     | o phi-3.5-vision tem metade disso |
#: |        |                                     | e está frio, e o gemma já é o     |
#: |        |                                     | fallback de qualquer jeito.       |
#:
#: `rerank` ainda não tem consumidor: o LM Studio não expõe rerank pela API
#: OpenAI. A entrada fica porque o mapa é declaração de intenção do dono e a busca
#: da v1 vai precisar dela — mas quem ler o código não deve procurar o call site.
PROFILE_MODELS: Final[Mapping[str, Mapping[str, str]]] = {
    "lmstudio": {
        "chief": "qwen3-vl-8b-instruct",
        "cheap": "google/gemma-4-e2b",
        "code": "deepseek-coder-v2-lite-instruct",
        "embed": "text-embedding-qwen3-embedding-0.6b",
        "rerank": "qwen3-reranker-0.6b",
        "vision": "qwen3-vl-8b-instruct",
    },
}

#: De onde veio o modelo escolhido. Vai para a API para que o PWA mostre "o que
#: está servindo o quê" sem ter de reimplementar a cadeia de fallback no browser.
ResolutionSource = Literal[
    "override",  # o dono nomeou o modelo no .env
    "profile_map",  # o mapa acima, para este provider
    "fallback",  # google/gemma-4-e2b, provado no roster
    "provider_default",  # o default do próprio provider
    "unresolved",  # não sobrou nada; a fábrica do provider decide
]


class ModelResolution(BaseModel):
    """O modelo escolhido para um perfil, com a razão da escolha.

    `reason` não é decoração: quando o dono vê o perfil `code` sendo servido pelo
    gemma, a única pergunta é "por quê", e a resposta ("deepseek não está no
    roster") tem de vir junto da resposta errada — senão vira uma tarde de debug.
    """

    profile: str
    provider: str
    model: str
    source: ResolutionSource
    #: `True` quando o modelo entregue não é o mapeado para o perfil.
    degraded: bool = False
    reason: str = ""


def profile_env_var(provider: str, profile: str) -> str:
    """Nome da variável de ambiente que sobrescreve um perfil.

    Fonte única: `Settings` declara os campos com este mesmo formato e a API cita
    o nome nas mensagens. Convenção em dois lugares é convenção que diverge.
    """
    return f"{provider}_MODEL_{profile}".upper()


def resolve_model(
    profile: str,
    provider: str,
    *,
    override: str = "",
    provider_default: str = "",
    served: Collection[str] | None = None,
) -> ModelResolution:
    """Resolve perfil → modelo para um provider. Nunca levanta.

    `served` é o roster REAL do provider (ids que ele diz servir agora) ou `None`
    quando não deu para saber — provider offline, sem endpoint de listagem, ou
    chamador que não quis pagar a ida à rede. `None` significa "desconhecido", e
    desconhecido NÃO é "vazio": tratar os dois igual faria todo perfil degradar
    para o default assim que o LM Studio demorasse a responder.
    """
    conhecido: frozenset[str] | None = None if served is None else frozenset(served)

    def servido(model: str) -> bool:
        return conhecido is None or model in conhecido

    trilha: list[str] = []

    def resultado(model: str, source: ResolutionSource) -> ModelResolution:
        # Degradado é "não foi o mapeado para o perfil", não "não foi o ideal":
        # um override do dono é a escolha certa por definição.
        res = ModelResolution(
            profile=profile,
            provider=provider,
            model=model,
            source=source,
            degraded=source not in ("override", "profile_map") or bool(trilha),
            reason="; ".join(trilha),
        )
        _log(res)
        return res

    # 1. Override explícito. Vem antes do mapa porque o dono sabe da máquina dele
    #    mais do que a tabela acima — mas ainda passa pelo roster: id com erro de
    #    digitação no .env viraria 404 na primeira geração, longe da causa.
    if override:
        if servido(override):
            return resultado(override, "override")
        trilha.append(
            f"{profile_env_var(provider, profile)}={override!r} não está no roster"
        )

    # 2. O mapa deste provider.
    mapeado = PROFILE_MODELS.get(provider, {}).get(profile, "")
    if mapeado:
        if servido(mapeado):
            return resultado(mapeado, "profile_map")
        trilha.append(f"modelo mapeado {mapeado!r} não está no roster")
    elif provider in PROFILE_MODELS:
        trilha.append(f"perfil {profile!r} não está mapeado para {provider!r}")
    else:
        trilha.append(f"{provider!r} não tem mapa de perfis")

    # 3. O fallback declarado. Único candidato que não é específico do provider e
    #    portanto o único que exige prova: sem roster, não há como afirmar que
    #    este provider serve um modelo do LM Studio.
    if conhecido is not None and FALLBACK_MODEL in conhecido:
        return resultado(FALLBACK_MODEL, "fallback")
    trilha.append(
        f"fallback {FALLBACK_MODEL!r} indisponível"
        if conhecido is not None
        else f"fallback {FALLBACK_MODEL!r} não verificável sem roster"
    )

    # 4. O default do provider. Terminal: é o contrato dele, não existe melhor.
    if provider_default:
        return resultado(provider_default, "provider_default")

    # 5. Nem isso. Devolve vazio de propósito: a fábrica do provider trata modelo
    #    vazio como "use o seu default", então quem chama continua funcionando.
    return resultado("", "unresolved")


def _log(res: ModelResolution) -> None:
    """Nível pelo que o dono pode consertar, não pela gravidade sentida.

    Provider sem mapa (o `gemini` da máquina de casa) é configuração esperada e
    sai em INFO — se fosse WARNING, todo request da casa gritaria e o log viraria
    ruído que ninguém lê. Já modelo declarado que o provider não serve é sempre
    acionável (id errado, modelo removido do LM Studio) e sai em WARNING.
    """
    if not res.degraded:
        return
    acionavel = "não está no roster" in res.reason
    logger.log(
        logging.WARNING if acionavel else logging.INFO,
        "perfil %r no provider %r resolvido para %r (%s): %s",
        res.profile,
        res.provider,
        res.model or "<default do provider>",
        res.source,
        res.reason,
    )


__all__ = [
    "FALLBACK_MODEL",
    "PROFILE_MODELS",
    "TASK_PROFILES",
    "ModelResolution",
    "ResolutionSource",
    "TaskProfile",
    "profile_env_var",
    "resolve_model",
]
