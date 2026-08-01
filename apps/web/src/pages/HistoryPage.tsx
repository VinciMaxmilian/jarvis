import { useState, useEffect } from 'react'
import { getApiBase } from '../config'

interface GoalSummary {
  id: string
  title: string
  description: string
  status: string
  priority: number
  created_at: string
}

interface TaskSummary {
  id: string
  title: string
  status: string
  tool: string | null
  attempts: number
  created_at: string
  finished_at: string | null
}

interface ChatPreview {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
  preview_text: string
}

interface ModelStats {
  model: string
  input_tokens: number
  output_tokens: number
}

interface ToolUsage {
  tool: string
  count: number
}

interface StatsResponse {
  models: ModelStats[]
  tools: ToolUsage[]
}

const STATUS_MAP: Record<string, string> = {
  draft: 'status-pending',
  active: 'status-active',
  blocked: 'status-pending',
  done: 'status-done',
  failed: 'status-failed',
  cancelled: 'status-failed',
  pending: 'status-pending',
  running: 'status-active',
  waiting_approval: 'status-pending',
}

export default function HistoryPage({ onSelectChat }: { onSelectChat?: (id: string) => void }) {
  const [activeTab, setActiveTab] = useState<'goals' | 'chats' | 'stats'>('goals')

  // Goals State
  const [goals, setGoals] = useState<GoalSummary[]>([])
  const [expandedGoal, setExpandedGoal] = useState<string | null>(null)
  const [tasks, setTasks] = useState<Record<string, TaskSummary[]>>({})

  // Chats State
  const [chats, setChats] = useState<ChatPreview[]>([])

  // Stats State
  const [stats, setStats] = useState<StatsResponse | null>(null)

  useEffect(() => {
    let mounted = true;

    const apiBase = getApiBase();

    if (activeTab === 'goals' && goals.length === 0) {
      fetch(`${apiBase}/api/goals/`)
        .then(r => r.ok ? r.json() : [])
        .then(data => { if (mounted) setGoals(data); })
        .catch(() => {})
    } else if (activeTab === 'chats' && chats.length === 0) {
      fetch(`${apiBase}/api/history/chats`)
        .then(r => r.ok ? r.json() : [])
        .then(data => { if (mounted) setChats(data); })
        .catch(() => {})
    } else if (activeTab === 'stats' && stats === null) {
      fetch(`${apiBase}/api/history/stats`)
        .then(r => r.ok ? r.json() : null)
        .then(data => { if (mounted) setStats(data); })
        .catch(() => {})
    }

    return () => { mounted = false; };
  }, [activeTab, goals.length, chats.length, stats])

  const loadTasks = async (goalId: string) => {
    if (tasks[goalId]) {
      setExpandedGoal(expandedGoal === goalId ? null : goalId)
      return
    }
    try {
      const apiBase = getApiBase();
      const r = await fetch(`${apiBase}/api/goals/${goalId}/tasks`)
      if (r.ok) {
        const t = await r.json()
        setTasks(prev => ({ ...prev, [goalId]: t }))
      }
    } catch {}
    setExpandedGoal(expandedGoal === goalId ? null : goalId)
  }

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
    }}>
      {/* Header with Tabs */}
      <div style={{
        padding: '12px 20px',
        borderBottom: '1px solid hsl(var(--border-dim))',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
        <div style={{ display: 'flex', gap: 16 }}>
          {(['goals', 'chats', 'stats'] as const).map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className="mono"
              style={{
                background: 'none',
                border: 'none',
                color: activeTab === tab ? 'hsl(var(--neon-cyan))' : 'hsl(var(--text-muted))',
                fontSize: 12,
                letterSpacing: '0.1em',
                cursor: 'pointer',
                textTransform: 'uppercase',
                textShadow: activeTab === tab ? '0 0 8px hsl(var(--neon-cyan) / 0.4)' : 'none',
                padding: '4px 0',
                borderBottom: activeTab === tab ? '2px solid hsl(var(--neon-cyan))' : '2px solid transparent',
              }}
            >
              {tab === 'goals' ? 'MISSÕES' : tab === 'chats' ? 'CHATS' : 'ESTATÍSTICAS'}
            </button>
          ))}
        </div>
      </div>

      {/* Content Area */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: 20,
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
      }}>
        {/* TAB: GOALS */}
        {activeTab === 'goals' && (
          <>
            {goals.length === 0 && (
              <div style={{
                flex: 1, display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center', gap: 12, opacity: 0.5,
              }}>
                <div style={{ fontSize: 40 }}>📋</div>
                <p className="mono" style={{ color: 'hsl(var(--text-muted))', textAlign: 'center', fontSize: 12 }}>
                  NO MISSIONS RECORDED
                </p>
              </div>
            )}
            {goals.map(goal => (
              <div key={goal.id} className="animate-fade-in">
                <button
                  onClick={() => loadTasks(goal.id)}
                  className="hud-panel"
                  style={{
                    width: '100%', padding: '14px 16px', cursor: 'pointer', textAlign: 'left',
                    border: expandedGoal === goal.id ? '1px solid hsl(var(--neon-cyan) / 0.3)' : undefined,
                    background: expandedGoal === goal.id ? 'hsl(var(--neon-cyan) / 0.03)' : undefined,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                    <span style={{ fontSize: 13, fontWeight: 500, color: 'hsl(var(--text-primary))' }}>
                      {goal.title}
                    </span>
                    <span className={`status-badge ${STATUS_MAP[goal.status] || ''}`}>
                      {goal.status}
                    </span>
                  </div>
                  {goal.description && (
                    <p style={{ fontSize: 12, color: 'hsl(var(--text-secondary))', lineHeight: 1.5, marginBottom: 6 }}>
                      {goal.description}
                    </p>
                  )}
                  <span className="mono" style={{ fontSize: 10, color: 'hsl(var(--text-muted))' }}>
                    {new Date(goal.created_at).toLocaleString('pt-BR')}
                  </span>
                </button>

                {expandedGoal === goal.id && tasks[goal.id] && (
                  <div style={{
                    marginLeft: 20, borderLeft: '2px solid hsl(var(--neon-cyan) / 0.2)',
                    paddingLeft: 16, marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8,
                  }}>
                    {tasks[goal.id].map(task => (
                      <div key={task.id} className="animate-slide-in hud-panel" style={{ padding: '10px 12px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                          <span style={{ fontSize: 12, color: 'hsl(var(--text-primary))' }}>{task.title}</span>
                          <span className={`status-badge ${STATUS_MAP[task.status] || ''}`}>{task.status}</span>
                        </div>
                        {task.tool && (
                          <span className="mono" style={{ fontSize: 10, color: 'hsl(var(--neon-purple))', marginTop: 4, display: 'block' }}>
                            ⚡ {task.tool}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </>
        )}

        {/* TAB: CHATS */}
        {activeTab === 'chats' && (
          <>
            {chats.length === 0 && (
              <div style={{
                flex: 1, display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center', gap: 12, opacity: 0.5,
              }}>
                <div style={{ fontSize: 40 }}>💬</div>
                <p className="mono" style={{ color: 'hsl(var(--text-muted))', textAlign: 'center', fontSize: 12 }}>
                  NO CHAT HISTORY
                </p>
              </div>
            )}
            {chats.map(chat => (
              <button 
                key={chat.id} 
                className="hud-panel animate-fade-in" 
                style={{ padding: '14px 16px', textAlign: 'left', cursor: 'pointer', background: 'transparent', border: '1px solid hsl(var(--border-dim))' }}
                onClick={() => onSelectChat?.(chat.id)}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                  <span style={{ fontSize: 13, fontWeight: 500, color: 'hsl(var(--neon-cyan))' }}>
                    {chat.title}
                  </span>
                  <span className="mono" style={{ fontSize: 10, color: 'hsl(var(--text-muted))' }}>
                    {new Date(chat.updated_at).toLocaleString('pt-BR')}
                  </span>
                </div>
                <p style={{
                  fontSize: 12, color: 'hsl(var(--text-secondary))', lineHeight: 1.5,
                  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                  background: 'hsl(var(--hud-bg))', padding: '8px 12px', borderRadius: 4,
                  border: '1px solid hsl(var(--border-dim))'
                }}>
                  {chat.preview_text}
                </p>
                <div style={{ marginTop: 8, display: 'flex', justifyContent: 'flex-end' }}>
                  <span className="mono" style={{ fontSize: 10, color: 'hsl(var(--neon-purple))' }}>
                    {chat.message_count} MESSAGES
                  </span>
                </div>
              </button>
            ))}
          </>
        )}

        {/* TAB: STATS */}
        {activeTab === 'stats' && stats && (
          <div className="animate-fade-in" style={{ display: 'grid', gap: 20 }}>
            {/* Model Usage */}
            <section className="hud-panel" style={{ padding: 16 }}>
              <h3 className="mono glow-text" style={{ color: 'hsl(var(--neon-cyan))', fontSize: 11, marginBottom: 16 }}>
                MODEL USAGE (TOKENS)
              </h3>
              {stats.models.length === 0 ? (
                <span className="mono" style={{ fontSize: 11, color: 'hsl(var(--text-muted))' }}>No data</span>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {stats.models.map(m => (
                    <div key={m.model} style={{
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      background: 'hsl(var(--hud-bg))', padding: '8px 12px', borderRadius: 4,
                      border: '1px solid hsl(var(--border-dim))'
                    }}>
                      <span className="mono" style={{ fontSize: 12, color: 'hsl(var(--text-primary))' }}>{m.model}</span>
                      <div style={{ display: 'flex', gap: 16 }}>
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end' }}>
                          <span style={{ fontSize: 10, color: 'hsl(var(--text-muted))' }}>IN</span>
                          <span className="mono" style={{ fontSize: 11, color: 'hsl(var(--neon-blue))' }}>{m.input_tokens.toLocaleString()}</span>
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end' }}>
                          <span style={{ fontSize: 10, color: 'hsl(var(--text-muted))' }}>OUT</span>
                          <span className="mono" style={{ fontSize: 11, color: 'hsl(var(--neon-green))' }}>{m.output_tokens.toLocaleString()}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>

            {/* Tools Usage */}
            <section className="hud-panel" style={{ padding: 16 }}>
              <h3 className="mono glow-text" style={{ color: 'hsl(var(--neon-purple))', fontSize: 11, marginBottom: 16 }}>
                TOOL CALLS (LIFETIME)
              </h3>
              {stats.tools.length === 0 ? (
                <span className="mono" style={{ fontSize: 11, color: 'hsl(var(--text-muted))' }}>No tools used yet</span>
              ) : (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {stats.tools.map(t => (
                    <div key={t.tool} style={{
                      display: 'flex', alignItems: 'center', gap: 8,
                      background: 'hsl(var(--hud-bg))', padding: '6px 12px', borderRadius: 999,
                      border: '1px solid hsl(var(--neon-purple) / 0.3)'
                    }}>
                      <span className="mono" style={{ fontSize: 11, color: 'hsl(var(--text-primary))' }}>⚡ {t.tool}</span>
                      <span className="mono" style={{
                        fontSize: 10, background: 'hsl(var(--neon-purple) / 0.15)',
                        color: 'hsl(var(--neon-purple))', padding: '2px 6px', borderRadius: 999
                      }}>
                        {t.count}x
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  )
}
