import { useState, useEffect } from 'react'
import { getApiBase } from '../config'

interface ToolInfo {
  name: string
  description: string
  idempotent: boolean
  requires_approval: boolean
}

export default function ToolsPage() {
  const [tools, setTools] = useState<ToolInfo[]>([])

  useEffect(() => {
    const apiBase = getApiBase();
    fetch(`${apiBase}/api/tools`)
      .then(r => r.ok ? r.json() : [])
      .then(setTools)
      .catch(() => setTools([]))
  }, [])

  // Hardcoded v0 tools as fallback
  const displayTools = tools.length > 0 ? tools : [
    {
      name: 'web_search',
      description: 'Busca informações na web usando Tavily. Retorna resultados relevantes com título, URL e conteúdo resumido.',
      idempotent: true,
      requires_approval: false,
    },
  ]

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
    }}>
      {/* Header */}
      <div style={{
        padding: '12px 20px',
        borderBottom: '1px solid hsl(var(--border-dim))',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
        <span className="mono glow-text" style={{
          color: 'hsl(var(--neon-cyan))',
          fontSize: 12,
          letterSpacing: '0.1em',
        }}>TOOL REGISTRY</span>
        <span className="status-badge status-active">{displayTools.length} active</span>
      </div>

      {/* Tool grid */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: 20,
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
        gap: 16,
        alignContent: 'start',
      }}>
        {displayTools.map(tool => (
          <div key={tool.name} className="hud-panel glow-cyan" style={{
            padding: 16,
            display: 'flex',
            flexDirection: 'column',
            gap: 10,
          }}>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}>
              <span className="mono" style={{
                color: 'hsl(var(--neon-cyan))',
                fontSize: 13,
                fontWeight: 600,
              }}>
                {tool.name}
              </span>
              <span className="status-badge status-active">active</span>
            </div>

            <p style={{
              color: 'hsl(var(--text-secondary))',
              fontSize: 12,
              lineHeight: 1.6,
            }}>
              {tool.description}
            </p>

            <div style={{
              display: 'flex',
              gap: 8,
              marginTop: 'auto',
            }}>
              {tool.idempotent && (
                <span className="mono" style={{
                  fontSize: 10,
                  padding: '2px 6px',
                  borderRadius: 4,
                  background: 'hsl(var(--neon-green) / 0.1)',
                  color: 'hsl(var(--neon-green))',
                  border: '1px solid hsl(var(--neon-green) / 0.2)',
                }}>
                  IDEMPOTENT
                </span>
              )}
              {tool.requires_approval && (
                <span className="mono" style={{
                  fontSize: 10,
                  padding: '2px 6px',
                  borderRadius: 4,
                  background: 'hsl(var(--neon-amber) / 0.1)',
                  color: 'hsl(var(--neon-amber))',
                  border: '1px solid hsl(var(--neon-amber) / 0.2)',
                }}>
                  APPROVAL REQ
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
