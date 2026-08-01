import { type ReactNode } from 'react'
import Sidebar from './Sidebar'

const MOBILE_TABS = [
  { id: 'chat', icon: '💬', label: 'Chat' },
  { id: 'brain', icon: '🧠', label: 'Brain' },
  { id: 'memory', icon: '💾', label: 'Memory' },
  { id: 'tools', icon: '🔧', label: 'Tools' },
  { id: 'history', icon: '📋', label: 'History' },
  { id: 'rules', icon: '⚙️', label: 'Rules' },
] as const

export type PageId = typeof MOBILE_TABS[number]['id']

interface LayoutProps {
  currentPage: PageId
  onNavigate: (page: PageId) => void
  children: ReactNode
}

export default function Layout({ currentPage, onNavigate, children }: LayoutProps) {
  return (
    <div style={{
      display: 'flex',
      height: '100dvh',
      width: '100vw',
      position: 'relative',
      zIndex: 1,
      overflow: 'hidden',
    }}>
      {/* Desktop Sidebar */}
      <div className="desktop-sidebar" style={{
        width: 240,
        minWidth: 240,
        height: '100dvh',
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--neu-surface)',
        boxShadow: '6px 0 14px -8px var(--neu-lo)',
        zIndex: 2,
      }}>
        <Sidebar currentPage={currentPage} onNavigate={onNavigate} />
      </div>

      {/* Main content */}
      <main style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        position: 'relative',
      }}>
        {/* Top bar — mobile */}
        <header className="mobile-nav" style={{
          padding: '12px 16px',
          background: 'var(--neu-surface)',
          boxShadow: '0 6px 14px -10px var(--neu-lo)',
          display: 'none',
          alignItems: 'center',
          justifyContent: 'space-between',
          zIndex: 2,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div className="neu-icon" style={{ width: 30, height: 30, fontSize: 14 }}>⚡</div>
            <span style={{
              fontSize: 14,
              fontWeight: 700,
              color: 'var(--ink)',
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
            }}>JARVIS</span>
          </div>
          <span className="mono" style={{ color: 'var(--ink-3)', fontSize: 10 }}>v1</span>
        </header>

        <div style={{ flex: 1, overflow: 'auto' }}>
          {children}
        </div>

        {/* Mobile bottom nav */}
        <nav className="mobile-nav" style={{
          display: 'none',
          background: 'var(--neu-surface)',
          boxShadow: '0 -6px 16px -10px var(--neu-lo)',
          padding: '8px 8px',
          paddingBottom: 'max(8px, env(safe-area-inset-bottom))',
          justifyContent: 'space-around',
          zIndex: 2,
        }}>
          {MOBILE_TABS.map(tab => {
            const on = currentPage === tab.id
            return (
              <button
                key={tab.id}
                onClick={() => onNavigate(tab.id)}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: 3,
                  padding: '7px 14px',
                  borderRadius: 14,
                  border: `1px solid ${on ? 'var(--neu-edge-lo)' : 'transparent'}`,
                  background: on ? 'var(--neu-surface)' : 'transparent',
                  boxShadow: on ? 'var(--neu-in-sm)' : 'none',
                  cursor: 'pointer',
                  transition: 'box-shadow 0.2s ease, color 0.2s ease',
                  color: on ? 'var(--accent)' : 'var(--ink-3)',
                }}
              >
                <span style={{ fontSize: 17 }}>{tab.icon}</span>
                <span style={{
                  fontSize: 10,
                  fontWeight: on ? 600 : 500,
                  letterSpacing: '0.03em',
                }}>
                  {tab.label}
                </span>
              </button>
            )
          })}
        </nav>
      </main>
    </div>
  )
}
