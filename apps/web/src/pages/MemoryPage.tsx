import { NeuralMap } from '../components/NeuralMap/NeuralMap'
import { getApiBase } from '../config'
import { useTheme } from '../contexts/ThemeContext'

export default function MemoryPage() {
  const { theme } = useTheme()
  const apiBase = getApiBase()
  
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
        }}>MEMORY GRAPH</span>
        <span className="mono" style={{
          color: 'hsl(var(--text-muted))',
          fontSize: 10,
        }}>LONG TERM STORAGE</span>
      </div>

      {/* NeuralMap embed */}
      <div style={{ flex: 1, position: 'relative' }}>
        <NeuralMap url={`${apiBase}/api/memory/graph.json`} theme={theme} />
      </div>
    </div>
  )
}
