# Friday — archived

This repository held the first attempt: a TypeScript monorepo (pnpm + Turborepo,
hexagonal architecture, KoboldCpp provider abstraction). Its full content is
preserved in history at commit `7385d24`.

**The project continued as Jarvis**, rewritten in Python with the same idea — a
personal cognitive operating system that takes *objectives*, not prompts.

- Live repository: `jarvis/` (its own git repo — <https://github.com/VinciMaxmilian/jarvis>)
- Vision and roadmap: `jarvis/plan.md`
- Repository layout: `jarvis/plan-scheme.md`
- Stack and data contracts: `jarvis/tools.md`

What carried over from this attempt:

| Idea | Where it lives now |
|---|---|
| Provider abstraction over the inference engine | `jarvis/packages/llm` (`LLMProvider`) |
| Ports and adapters, dependencies pointing inward | `jarvis/packages/shared/ports.py` |
| Typed data contracts as the single source of truth | `jarvis/packages/shared/contracts.py` |
| Event-driven module boundaries | Redis Streams, per `plan.md` §11 |
| ADR habit and acceptance-criteria milestones | `jarvis/plan.md` §14–15 |

Nothing here is maintained. Read `jarvis/`.
