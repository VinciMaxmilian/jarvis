import { NeuralMap } from '../components/NeuralMap/NeuralMap'

export default function BrainPage() {
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
        }}>NEURAL MAP</span>
        <span className="mono" style={{
          color: 'hsl(var(--text-muted))',
          fontSize: 10,
        }}>REACT NATIVE ENGINE</span>
      </div>

      {/* Brain embed */}
      <div style={{ flex: 1, position: 'relative' }}>
        <NeuralMap />
      </div>
    </div>
  )
}
