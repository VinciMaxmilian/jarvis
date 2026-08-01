"""Configuração validada no boot. Variável obrigatória faltando derruba a app.

Toda variável declarada aqui entra em `.env.example` no mesmo commit.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from packages.shared.contracts import ProviderId

#: Raiz do repo a partir deste arquivo (packages/shared/settings.py → ../../..).
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.fspath(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- ambiente ---------------------------------------------------------- #
    environment: Literal["dev", "development", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # --- dados (obrigatório) ----------------------------------------------- #
    database_url: str = Field(
        ...,
        description="DSN async do Postgres: postgresql+asyncpg://user:pass@host:5432/jarvis",
    )
    redis_url: str = "redis://127.0.0.1:6379/0"

    # --- LLM --- #
    # Mesmo Literal de `SystemSettings.provider`: o default do .env e a escolha
    # persistida em banco não podem aceitar conjuntos diferentes de provider.
    # Default `lmstudio`: inferência local, sem custo por token. Um default que
    # gasta dinheiro quando alguém esquece de configurar é a escolha errada — o
    # lmstudio, mal configurado, falha com connection refused, que é barato e
    # óbvio. Este valor precisa concordar com o CHIEF_PROVIDER do `.env.example`.
    chief_provider: ProviderId = "lmstudio"

    # Aceita GEMINI_API_KEY ou GOOGLE_API_KEY: o segundo é o nome que outras
    # ferramentas da máquina já leem (o graphify, por exemplo), e obrigar o dono a
    # manter a mesma chave em dois nomes é convite a uma das duas ficar velha.
    gemini_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("gemini_api_key", "google_api_key"),
        description="Chave do Google AI Studio; obrigatória com CHIEF_PROVIDER=gemini",
    )
    # NÃO verificado contra a API (não havia chave na máquina). Confirme o nome real
    # em GET /v1beta/models — `GeminiProvider.list_models()` faz isso.
    gemini_model: str = "gemini-2.5-flash"

    # LM Studio — servidor OpenAI-compatible na LAN. Entrada própria (e não
    # `OPENAI_BASE_URL` reaproveitado) porque as duas coisas coexistem: `openai`
    # pode apontar para a OpenAI de verdade enquanto `lmstudio` aponta para a
    # máquina que serve o modelo local. Reusar um campo para os dois obrigaria a
    # reescrever o .env a cada troca de provider.
    #
    # `api_key` é exigido pelo SDK da OpenAI mas ignorado pelo LM Studio; o
    # literal existe só para o cliente não recusar a construção.
    lmstudio_base_url: str = "http://192.168.11.189:1234/v1"
    lmstudio_model: str = "google/gemma-4-e2b"
    lmstudio_api_key: str = "lm-studio"

    # Override por perfil de tarefa (`packages/llm/profiles.py`). Todos vazios por
    # default: vazio significa "use o mapa embutido", que já traz a escolha medida
    # contra o roster real. Existem para que retunar um perfil seja uma linha no
    # .env em vez de um commit — e são declarados só para o `lmstudio` porque só
    # ele tem um mapa de perfis. Prefixar pelo provider é o que impede a máquina
    # de casa (Gemini) de herdar um id de modelo do LM Studio.
    lmstudio_model_chief: str = ""
    lmstudio_model_cheap: str = ""
    lmstudio_model_code: str = ""
    lmstudio_model_embed: str = ""
    lmstudio_model_rerank: str = ""
    lmstudio_model_vision: str = ""

    anthropic_api_key: str = "sk-ant-dummy"
    openai_api_key: str = "sk-dummy"
    openai_base_url: str = "http://127.0.0.1:1234/v1"
    chief_model: str = "claude-opus-5"
    cheap_model: str = "claude-haiku-4-5-20251001"
    kobold_url: str = "http://host.docker.internal:5001"  # v1, provider local

    # Ollama é o runtime local que roda na máquina pessoal (4 GB de VRAM, CPU
    # pré-AVX2). Loopback por default: serve um operador só, nesta máquina.
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "adelnazmy2002/Qwen3-VL-8B-Instruct"

    # --- tools ------------------------------------------------------------- #
    tavily_api_key: str = Field(..., description="Chave da API Tavily (busca web, v0)")

    # --- Cloudflare Access (autenticação na borda, verificada na origem) ---- #
    #
    # `plan.md` §36 põe a identidade no Cloudflare Access, na frente do Tunnel.
    # Isso resolve login, MFA e revogação — mas só para quem entra PELO Tunnel.
    # O Access assina a identidade num JWT e a repassa no header
    # `Cf-Access-Jwt-Assertion`; se a origem não conferir essa assinatura, o
    # "gate" existe apenas no caminho feliz. Um segundo túnel, um hostname sem
    # policy ou uma ingress rule velha entregam a origem inteira sem senha, e o
    # sintoma é ausência de sintoma. Por isso a verificação é aqui também.
    #
    # `cf_access_team_domain` aceita "meutime" ou "meutime.cloudflareaccess.com";
    # o validador normaliza. `cf_access_aud` é a tag Application Audience da
    # aplicação no dashboard do Zero Trust (uma por aplicação, não por conta).
    cf_access_team_domain: str = Field(
        default="",
        description=(
            "Domínio da equipe Zero Trust: 'meutime' ou "
            "'meutime.cloudflareaccess.com'"
        ),
    )
    cf_access_aud: str = Field(
        default="",
        description="Application Audience (AUD) tag da aplicação no Zero Trust",
    )
    cf_access_emails: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description="Lista de e-mails dos donos; o claim `email` do token tem de estar nesta lista",
    )

    # O DEFAULT É O PONTO DELICADO DESTE ARQUIVO. As duas opções óbvias são ruins:
    #
    #   - default OFF: no dia em que o Tunnel sobe, a origem serve tudo para
    #     quem alcançá-la. Falha silenciosa, e a única evidência é um log que
    #     ninguém lê. Segurança que depende de lembrar de ligar não é segurança.
    #   - default ON: quebra `127.0.0.1:8000` no desenvolvimento, onde não existe
    #     Access nenhum e portanto não existe JWT nenhum. Um gate que impede o
    #     dono de trabalhar é desligado na primeira hora — e fica desligado.
    #
    # `auto` desempata pela única coisa que distingue os dois mundos sem exigir
    # disciplina: **a configuração existir**. Quem preencheu domínio, AUD e
    # e-mail já montou o Access — enforcement liga sozinho, sem um segundo passo
    # para esquecer. Quem não preencheu está em dev, e o gate fica fora do
    # caminho. O buraco que sobraria ("subi em prod e esqueci de preencher") é
    # fechado por `_validate_cf_access`, que DERRUBA O BOOT nesse caso: em prod,
    # sem Access configurado, não há resposta correta a dar — nem servir sem
    # autenticação, nem recusar tudo em silêncio. Melhor não subir.
    #
    # `on` força a verificação (útil para exercitar o caminho autenticado em
    # dev); `off` é a escape hatch consciente para quem põe outro gate na frente
    # — e em prod ela grita no log de boot em nível ERROR, porque desligar
    # autenticação é decisão que precisa aparecer no `docker logs`.
    #
    # Regra que vale para os três valores: configuração PELA METADE nunca vira
    # "melhor esforço". Meio configurado é erro de boot, não meio-gate.
    cf_access_enforce: Literal["auto", "on", "off"] = "auto"

    #: De quanto em quanto tempo o JWKS do Cloudflare é rebuscado por rotina.
    #: As chaves giram a cada ~6 semanas e a anterior vale mais 7 dias, então uma
    #: hora é folgado; `kid` desconhecido força uma busca fora deste ciclo.
    cf_access_jwks_ttl_seconds: int = Field(default=3600, ge=60)

    # --- v1: só ganham uso depois, mas o contrato já existe ----------------- #
    lancedb_path: str = "./data/lancedb"

    # --- API --------------------------------------------------------------- #
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    # NoDecode desliga o json.loads que o pydantic-settings faz em campo de tipo
    # complexo ANTES de qualquer validator. Sem ele o `_split_csv` abaixo nunca
    # roda: a origem separada por vírgula morre em SettingsError no parse.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173", "http://tauri.localhost", "tauri://localhost"]

    @field_validator("database_url")
    @classmethod
    def _must_be_async_dsn(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL precisa usar o driver async: postgresql+asyncpg://..."
            )
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @field_validator("cf_access_team_domain")
    @classmethod
    def _normalize_team_domain(cls, v: str) -> str:
        """Reduz o que o dono copiou do dashboard ao host puro da equipe.

        O valor circula no dashboard em quatro formas — "meutime",
        "meutime.cloudflareaccess.com", a URL completa e até a URL dos certs. As
        quatro precisam produzir o mesmo `iss`, porque o `iss` é comparado byte a
        byte contra o do token: uma barra sobrando reprovaria todo token válido,
        e o dono passaria a tarde caçando um erro de digitação.
        """
        host = v.strip().removeprefix("https://").removeprefix("http://")
        host = host.removesuffix("/cdn-cgi/access/certs").strip("/")
        if not host:
            return ""
        if "." not in host:
            host = f"{host}.cloudflareaccess.com"
        return host.lower()



    @field_validator("cf_access_aud")
    @classmethod
    def _reject_application_id_as_aud(cls, v: str) -> str:
        """Recusa o Application ID no lugar do Application Audience (AUD) tag.

        Os dois valores ficam na MESMA tela do dashboard e já foram trocados uma
        vez nesta configuração. O estrago é máximo e o sintoma é enganoso: com o
        AUD errado o Access continua autenticando na borda normalmente, o dono
        chega a fazer login, e é a origem que recusa o token válido com
        `InvalidAudienceError` — ou seja, parece que a API quebrou, não que a
        configuração está errada.

        Distingui-los é trivial e vale um erro de boot: o AUD é hexadecimal de
        64 caracteres; o Application ID é um UUID, com hífens. Só a forma de UUID
        é recusada aqui — nada de exigir exatamente 64 hex, para não derrubar o
        boot se a Cloudflare mudar o comprimento um dia.
        """
        aud = v.strip()
        regex = r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
        if aud and re.fullmatch(regex, aud):
            raise ValueError(
                "CF_ACCESS_AUD está com o formato de UUID, que é o Application "
                "ID — não o Application Audience (AUD) tag. O AUD é uma cadeia "
                "hexadecimal (64 caracteres, sem hífen). Pegue em Zero Trust -> "
                "Access controls -> Applications -> Configure -> Additional "
                "settings -> 'Application Audience (AUD) Tag'."
            )
        return aud

    @model_validator(mode="before")
    @classmethod
    def _parse_cf_access_emails(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Converte string com vírgulas em lista de emails (do .env)."""
        val = data.get("cf_access_emails")
        # Fallback para o nome antigo da variável
        if val is None and "cf_access_email" in data:
            val = data["cf_access_email"]
            
        if isinstance(val, str):
            emails = [e.strip() for e in val.split(",") if e.strip()]
            data["cf_access_emails"] = emails
        elif isinstance(val, list):
            data["cf_access_emails"] = val
        return data

    @model_validator(mode="after")
    def _validate_cf_access(self) -> Settings:
        """Recusa configuração de Access ambígua. Nunca degrada para fail-open.

        Três estados são erro de boot, e todos pelo mesmo motivo: o sistema não
        conseguiria dizer se deve ou não autenticar, e o default de "não sei" em
        autenticação jamais pode ser "deixa passar".
        """
        presentes = {
            "CF_ACCESS_TEAM_DOMAIN": bool(self.cf_access_team_domain),
            "CF_ACCESS_AUD": bool(self.cf_access_aud),
            "CF_ACCESS_EMAILS": bool(self.cf_access_emails),
        }
        faltando = sorted(nome for nome, ok in presentes.items() if not ok)
        completo = not faltando
        vazio = len(faltando) == len(presentes)

        # 1. Meio configurado. O caso perigoso é o AUD em branco: quem escreve a
        #    verificação sem pensar compara `aud` contra "" e aceita qualquer
        #    aplicação da conta. Não existe leitura benigna deste estado.
        if not completo and not vazio:
            raise ValueError(
                "Cloudflare Access está configurado pela metade — falta: "
                f"{', '.join(faltando)}. Preencha as três variáveis ou deixe as "
                "três vazias. Meia configuração de autenticação não vira "
                "meio-gate: vira gate que não existe."
            )

        # 2. `on` explícito sem os dados para verificar nada.
        if self.cf_access_enforce == "on" and not completo:
            raise ValueError(
                "CF_ACCESS_ENFORCE=on exige CF_ACCESS_TEAM_DOMAIN, CF_ACCESS_AUD "
                f"e CF_ACCESS_EMAIL. Falta: {', '.join(faltando)}."
            )

        # 3. Produção sem Access e sem decisão explícita. A app fica de pé só
        #    para servir a internet inteira; é o único cenário em que não subir é
        #    estritamente melhor do que subir.
        if self.environment == "prod" and self.cf_access_enforce == "auto" and vazio:
            raise ValueError(
                "ENVIRONMENT=prod sem Cloudflare Access configurado. A origem "
                "ficaria sem autenticação nenhuma assim que o Tunnel subisse. "
                "Preencha CF_ACCESS_TEAM_DOMAIN, CF_ACCESS_AUD e CF_ACCESS_EMAIL, "
                "ou assuma o risco por escrito com CF_ACCESS_ENFORCE=off."
            )
        return self

    # -- derivados do Cloudflare Access ------------------------------------- #

    @property
    def cf_access_configured(self) -> bool:
        """As três variáveis preenchidas. `_validate_cf_access` garante que o
        estado intermediário nem chega aqui."""
        return bool(
            self.cf_access_team_domain and self.cf_access_aud and self.cf_access_emails
        )

    @property
    def cf_access_enforced(self) -> bool:
        """Se a origem verifica a asserção do Access nesta execução."""
        if self.cf_access_enforce == "off":
            return False
        if self.cf_access_enforce == "on":
            return True
        return self.cf_access_configured

    @property
    def cf_access_issuer(self) -> str:
        """`iss` esperado no token: https://<equipe>.cloudflareaccess.com."""
        if not self.cf_access_team_domain:
            return ""
        return f"https://{self.cf_access_team_domain}"

    @property
    def cf_access_certs_url(self) -> str:
        """JWKS público da equipe (documentado pela Cloudflare)."""
        if not self.cf_access_issuer:
            return ""
        return f"{self.cf_access_issuer}/cdn-cgi/access/certs"

    @property
    def sync_database_url(self) -> str:
        """DSN síncrono, exigido pelo Alembic."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Instância única. Falha no primeiro acesso se faltar variável obrigatória."""
    return Settings()  # type: ignore[call-arg]  # campos vêm do .env/ambiente


__all__ = ["Settings", "get_settings"]
