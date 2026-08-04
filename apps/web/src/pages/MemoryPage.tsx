import { useState } from 'react'
import { NeuralMap } from '../components/NeuralMap/NeuralMap'
import { getApiBase } from '../config'

export default function MemoryPage() {
  const apiBase = getApiBase()
  const [updating, setUpdating] = useState(false)
  /* loadGraph() memoiza por URL, e o NeuralMap só recria o Engine quando a URL
   * muda — o contador é o que força um refetch depois de reindexar. */
  const [versao, setVersao] = useState(0)

  const handleUpdate = async () => {
    setUpdating(true)
    try {
      // Só faz sentido com MEMORY_VECTOR_BACKEND=graphify; nos outros backends
      // o 400 é esperado e o refetch abaixo já traz o estado atual do store.
      const res = await fetch(`${apiBase}/api/memory/graphify/update`, { method: 'POST' })
      const espera = res.ok ? 8000 : 0
      window.setTimeout(() => {
        setVersao(v => v + 1)
        setUpdating(false)
      }, espera)
    } catch (e) {
      console.error(e)
      setVersao(v => v + 1)
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
          }}>MEMORY MAP</span>

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
              fontFamily: 'monospace',
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

      {/* Mesmo motor da aba Brain, alimentado pelos vetores da memória */}
      <div style={{ flex: 1, position: 'relative' }}>
        <NeuralMap url={`${apiBase}/api/memory/graph.json?v=${versao}`} />
      </div>
    </div>
  )
}
