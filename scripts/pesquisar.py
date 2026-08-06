"""Roda uma pesquisa web à mão, sem passar pelo chat nem pelo orchestrator.

Existe por causa do passo 4 da ordem de execução do `plano-pesquisa-knowledge.md`:
**antes** de deixar o LLM disparar pesquisa sozinho, alguém precisa abrir os `.md`
gerados e julgar se aquilo é conhecimento ou lixo bem formatado. Depois que a tool
estiver ligada o corpus cresce sem supervisão, e aí já é tarde para descobrir que o
curador aprova página de índice.

    python scripts/pesquisar.py "lógica de programação" --profundidade rasa
    python scripts/pesquisar.py "lógica de programação" --max-fontes 3 --dry-run

`--dry-run` para no estágio de descoberta: mostra o que SERIA baixado, sem gastar
download, curadoria nem embedding. É o modo barato de calibrar o tópico.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


async def _executar(args: argparse.Namespace) -> int:
    from apps.api.db.engine import dispose_engine, get_session_factory
    from apps.api.deps import build_research_pipeline

    factory = get_session_factory()
    async with factory() as session:
        pipeline = await build_research_pipeline(session)

        if args.dry_run:
            cfg = pipeline._resolver_config(args.profundidade, args.max_fontes)
            from packages.rag.research import ResearchReport

            relatorio = ResearchReport(topico=args.topico, topico_slug="")
            consultas = await pipeline._expandir(args.topico, cfg)
            print(f"\nSubconsultas ({len(consultas)}):")
            for c in consultas:
                print(f"  - {c}")

            fontes = await pipeline._descobrir(consultas, cfg, relatorio)
            print(f"\nFontes que seriam baixadas ({len(fontes)}):")
            for f in fontes:
                marca = "raw" if f.raw_content else "fetch"
                print(f"  [{marca:5}] {f.url}")
                print(f"          {f.titulo}")
            if relatorio.erros:
                print("\nErros:")
                for e in relatorio.erros:
                    print(f"  ! {e}")
            await dispose_engine()
            return 0

        async def progresso(etapa: str, dados: dict) -> None:
            print(f"[{etapa}] {dados}")

        relatorio = await pipeline.run(
            args.topico,
            profundidade=args.profundidade,
            max_fontes=args.max_fontes,
            progresso=progresso,
        )

    await dispose_engine()

    print("\n" + "=" * 70)
    print(relatorio.resumo_curto)
    print("=" * 70)
    print(f"encontradas: {relatorio.fontes_encontradas}")
    print(f"baixadas:    {relatorio.fontes_baixadas}")
    print(f"em cache:    {relatorio.fontes_em_cache}")
    print(f"descartadas: {relatorio.fontes_descartadas}")
    if relatorio.encerrado_por_orcamento:
        print("AVISO: encerrada por teto de chunks — o corpus está incompleto.")
    print("\nDocumentos:")
    for doc in relatorio.documentos:
        print(f"  {doc.chunks:4d} trechos  {doc.caminho}")
        print(f"                 {doc.url}")
    if relatorio.erros:
        print("\nErros:")
        for erro in relatorio.erros:
            print(f"  ! {erro}")

    print(
        "\nAgora ABRA os arquivos acima e leia. "
        "Se tiver menu de navegação, paywall ou texto sem relação com o tópico, "
        "o curador está frouxo — ajuste _PROMPT_CURAR antes de seguir para a Fase 3."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Pesquisa web → base de conhecimento")
    parser.add_argument("topico")
    parser.add_argument(
        "--profundidade",
        default="rasa",
        choices=["rasa", "media", "profunda"],
        help="default rasa — o script é para conferência, não para popular a base",
    )
    parser.add_argument("--max-fontes", type=int, default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="só descobre as fontes; não baixa, não cura, não vetoriza",
    )
    args = parser.parse_args()

    try:
        return asyncio.run(_executar(args))
    except KeyboardInterrupt:
        print("\ninterrompido")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
