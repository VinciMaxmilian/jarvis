import { useEffect, useState } from 'react'
import { getApiBase } from '../config'

/* ------------------------------------------------------------------------- *
 * Painel dos cinco níveis de memória (`plan.md` §10), ao lado do grafo.
 *
 * Por que existe. A aba Memory desenhava só o grafo de vetores — ou seja,
 * `knowledge` e `long` misturados num mesmo desenho, e nada de `short`,
 * `working` ou `experience`. Quem abria a tela concluía que a memória do Jarvis
 * era um RAG. Os outros três níveis gravavam em disco e alimentavam o
 * planejamento sem nenhuma superfície de leitura.
 *
 * Um card genérico para os cinco de propósito: o backend já entrega os itens no
 * mesmo formato (`id`/`title`/`detail`/`at`/`badge`), então somar um nível é
 * somar uma entrada no payload, não um componente aqui.
 * ------------------------------------------------------------------------- */

type Item = {
  id: string
  title: string
  detail: string
  at: string | null
  badge?: string | null
  promoted?: boolean
}

type Level = {
  id: string
  name: string
  subtitle: string
  lifetime: string
  count: number
  items: Item[]
  backend?: string
  empty_hint?: string
  error?: string
}

/* Uma cor por nível, e sempre a mesma: o dono aprende a achar `experience` pela
 * cor antes de ler o rótulo. Só tokens do tema — hex solto aqui quebraria no
 * tema claro, onde a rampa inteira muda de luminosidade. `amber` no `working`
 * não é escolha estética: no DS ele já significa "em andamento". */
const COR: Record<string, string> = {
  short: 'hsl(var(--neon-cyan))',
  working: 'hsl(var(--neon-amber))',
  long: 'hsl(var(--neon-blue))',
  knowledge: 'hsl(var(--neon-green))',
  experience: 'hsl(var(--neon-purple))',
}

const cor = (id: string) => COR[id] ?? 'hsl(var(--neon-cyan))'

/** `2026-08-06T12:33:00Z` → `06/08 12:33`. Data completa não cabe no card. */
function quando(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getDate())}/${p(d.getMonth() + 1)} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export function MemoryLevels({ intervaloMs = 4000 }: { intervaloMs?: number }) {
  const apiBase = getApiBase()
  const [levels, setLevels] = useState<Level[]>([])
  const [aberto, setAberto] = useState<string | null>(null)
  const [erro, setErro] = useState<string | null>(null)

  /* Mesmo polling do grafo, e pela mesma razão: `working` e `experience` mudam
   * quando o orchestrator executa uma task — fora de qualquer requisição desta
   * aba —, então não há evento de UI para escutar. Pausa fora de foco: painel
   * que ninguém está vendo não vale um round-trip a cada 4s. */
  useEffect(() => {
    let vivo = true

    const carregar = async () => {
      if (document.visibilityState !== 'visible') return
      try {
        const res = await fetch(`${apiBase}/api/memory/levels`)
        if (!res.ok || !vivo) return
        const data = await res.json()
        setLevels(data.levels ?? [])
        setErro(null)
      } catch {
        /* API reiniciando: o próximo tique tenta de novo. A lista anterior fica
         * na tela — apagá-la a cada falha de rede piscaria o painel inteiro. */
        if (vivo) setErro('sem contato com a API')
      }
    }

    carregar()
    const id = window.setInterval(carregar, intervaloMs)
    document.addEventListener('visibilitychange', carregar)
    return () => {
      vivo = false
      window.clearInterval(id)
      document.removeEventListener('visibilitychange', carregar)
    }
  }, [apiBase, intervaloMs])

  return (
    <div
      className="mono"
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        overflowY: 'auto',
        borderLeft: '1px solid hsl(var(--border-dim))',
        fontSize: 11,
      }}
    >
      <div
        style={{
          padding: '12px 14px',
          borderBottom: '1px solid hsl(var(--border-dim))',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          position: 'sticky',
          top: 0,
          background: 'hsl(var(--hud-panel))',
          zIndex: 1,
        }}
      >
        <span className="glow-text" style={{ color: 'hsl(var(--neon-cyan))', letterSpacing: '0.1em' }}>
          5 NÍVEIS
        </span>
        <span style={{ color: 'hsl(var(--text-muted))', fontSize: 10 }}>
          {erro ?? 'ao vivo'}
        </span>
      </div>

      {levels.map(level => {
        const expandido = aberto === level.id
        const vazio = level.items.length === 0
        return (
          <div key={level.id} style={{ borderBottom: '1px solid hsl(var(--border-dim))' }}>
            <button
              onClick={() => setAberto(expandido ? null : level.id)}
              style={{
                width: '100%',
                background: 'transparent',
                border: 'none',
                borderLeft: `2px solid ${cor(level.id)}`,
                padding: '10px 14px',
                cursor: 'pointer',
                textAlign: 'left',
                fontFamily: 'monospace',
                fontSize: 11,
                color: 'inherit',
                display: 'flex',
                flexDirection: 'column',
                gap: 4,
              }}
            >
              <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ color: cor(level.id), letterSpacing: '0.08em' }}>
                  {level.name.toUpperCase()}
                </span>
                <span
                  style={{
                    color: 'hsl(var(--text-muted))',
                    border: '1px solid hsl(var(--border-dim))',
                    borderRadius: 3,
                    padding: '0 5px',
                    fontSize: 10,
                  }}
                >
                  {level.count}
                </span>
                <span style={{ marginLeft: 'auto', color: 'hsl(var(--text-muted))', fontSize: 10 }}>
                  {expandido ? '−' : '+'}
                </span>
              </span>
              <span style={{ color: 'hsl(var(--text-muted))', fontSize: 10, lineHeight: 1.4 }}>
                {level.subtitle}
              </span>
              <span style={{ color: 'hsl(var(--text-muted))', fontSize: 9, opacity: 0.75 }}>
                vida útil: {level.lifetime}
                {level.backend ? ` · ${level.backend}` : ''}
              </span>
            </button>

            {expandido && (
              <div style={{ padding: '0 14px 12px 16px', display: 'flex', flexDirection: 'column', gap: 8 }}>
                {level.error && (
                  <span style={{ color: 'hsl(var(--neon-red))', fontSize: 10 }}>
                    erro ao ler o nível: {level.error}
                  </span>
                )}
                {vazio && !level.error && (
                  <span style={{ color: 'hsl(var(--text-muted))', fontSize: 10, lineHeight: 1.5 }}>
                    {level.empty_hint ?? 'Vazio.'}
                  </span>
                )}
                {level.items.map(item => (
                  <div
                    key={item.id}
                    style={{
                      borderLeft: '1px solid hsl(var(--border-dim))',
                      paddingLeft: 8,
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 2,
                    }}
                  >
                    <span style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
                      <span style={{ color: cor(level.id), fontSize: 10 }}>{item.title}</span>
                      {item.badge && (
                        <span style={{ color: 'hsl(var(--text-muted))', fontSize: 9 }}>
                          {item.badge}
                        </span>
                      )}
                      {item.promoted && (
                        <span
                          style={{ color: 'hsl(var(--neon-cyan))', fontSize: 9 }}
                          title="Já passou do limiar: é padrão, e entra no contexto de planejamento."
                        >
                          padrão
                        </span>
                      )}
                      <span style={{ marginLeft: 'auto', color: 'hsl(var(--text-muted))', fontSize: 9 }}>
                        {quando(item.at)}
                      </span>
                    </span>
                    <span style={{ color: 'hsl(var(--text-secondary))', fontSize: 10, lineHeight: 1.45 }}>
                      {item.detail}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}

      {levels.length === 0 && !erro && (
        <span style={{ padding: 14, color: 'hsl(var(--text-muted))', fontSize: 10 }}>
          carregando níveis…
        </span>
      )}
    </div>
  )
}
