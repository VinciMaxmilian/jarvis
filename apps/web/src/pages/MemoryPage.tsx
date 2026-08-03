import { useState } from 'react'
import { getApiBase } from '../config'

export default function MemoryPage() {
  const apiBase = getApiBase()
  const [updating, setUpdating] = useState(false)
  
  const handleUpdate = async () => {
    setUpdating(true)
    try {
      const res = await fetch(`${apiBase}/api/memory/graphify/update`, {
        method: 'POST'
      })
      if (res.ok) {
        // It's processing in background. Give it a few seconds before we reload the iframe
        setTimeout(() => {
          // Force iframe reload by updating state or just trusting the user to wait
          setUpdating(false)
          // Simple reload trick
          const iframe = document.getElementById('graphify-iframe') as HTMLIFrameElement
          if (iframe) iframe.src = iframe.src
        }, 10000) // waits 10s
      } else {
        setUpdating(false)
        alert('O backend não está configurado para Graphify (MEMORY_VECTOR_BACKEND=graphify)')
      }
    } catch (e) {
      console.error(e)
      setUpdating(false)
    }
  }

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
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <span className="mono glow-text" style={{
            color: 'hsl(var(--neon-cyan))',
            fontSize: 12,
            letterSpacing: '0.1em',
          }}>MEMORY GRAPH (GRAPHIFY)</span>
          
          <button 
            onClick={handleUpdate}
            disabled={updating}
            style={{
              background: 'transparent',
              border: '1px solid hsl(var(--border-dim))',
              color: updating ? 'hsl(var(--text-muted))' : 'hsl(var(--neon-cyan))',
              padding: '4px 12px',
              fontSize: '10px',
              cursor: updating ? 'wait' : 'pointer',
              borderRadius: '4px',
              fontFamily: 'monospace'
            }}
          >
            {updating ? 'ATUALIZANDO EM BACKGROUND...' : 'ATUALIZAR GRAFO'}
          </button>
        </div>

        <span className="mono" style={{
          color: 'hsl(var(--text-muted))',
          fontSize: 10,
        }}>LONG TERM STORAGE</span>
      </div>

      {/* Graphify HTML embed */}
      <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
        <iframe 
          id="graphify-iframe"
          src={`${apiBase}/api/memory/graphify.html`}
          style={{
            width: '100%',
            height: '100%',
            border: 'none',
            background: '#1a1a1a'
          }}
          title="Graphify Memory"
        />
      </div>
    </div>
  )
}
