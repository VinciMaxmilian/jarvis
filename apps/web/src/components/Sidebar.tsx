import type { PageId } from './Layout'

const NAV_ITEMS: { id: PageId; icon: string; label: string }[] = [
  { id: 'chat', icon: '💬', label: 'COMMS' },
  { id: 'brain', icon: '🧠', label: 'BRAIN' },
  { id: 'memory', icon: '💾', label: 'MEMORY' },
  { id: 'tools', icon: '🔧', label: 'TOOLS' },
  { id: 'history', icon: '📋', label: 'HISTORY' },
  { id: 'rules', icon: '⚙️', label: 'RULES' },
]

interface SidebarProps {
  currentPage: PageId
  onNavigate: (page: PageId) => void
}

export default function Sidebar({ currentPage, onNavigate }: SidebarProps) {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      padding: '16px 12px',
    }}>
      {/* Logo */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '8px 12px',
        marginBottom: 24,
      }}>
        <div className="neu-icon" style={{ width: 38, height: 38, fontSize: 18 }}>⚡</div>
        <div>
          <div style={{
            fontSize: 16,
            fontWeight: 700,
            color: 'var(--ink)',
            letterSpacing: '0.1em',
          }}>
            JARVIS
          </div>
          <div className="mono" style={{
            fontSize: 10,
            color: 'var(--ink-3)',
            letterSpacing: '0.05em',
          }}>
            COGNITIVE OS v1
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
        {NAV_ITEMS.map(item => (
          <button
            key={item.id}
            onClick={() => onNavigate(item.id)}
            className={`nav-item ${currentPage === item.id ? 'active' : ''}`}
          >
            <span className="nav-icon" style={{ fontSize: 16 }}>{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      {/* Status footer */}
      <div className="neu-inset" style={{
        padding: '12px 14px',
        marginTop: 'auto',
      }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 8,
        }}>
          <span className="mono" style={{ color: 'var(--ink-3)', fontSize: 10, letterSpacing: '0.08em' }}>
            SYSTEM STATUS
          </span>
          <div className="animate-pulse-ring" style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: 'hsl(var(--neon-green))',
          }} />
        </div>
        <div className="mono" style={{
          color: 'var(--ink-2)',
          fontSize: 11,
          lineHeight: 1.8,
        }}>
          <div>API <span style={{ color: 'hsl(var(--neon-green))' }}>● ONLINE</span></div>
          <div>PG  <span style={{ color: 'hsl(var(--neon-green))' }}>● ONLINE</span></div>
        </div>
      </div>
    </div>
  )
}
