import { useState, useEffect } from 'react'
import { getApiBase } from '../config'

const DEFAULT_SYSTEM_PROMPT = `Você é o Jarvis, um sistema operacional cognitivo pessoal. Você ajuda o dono a alcançar objetivos delegando tarefas e usando ferramentas.

Regras:
- Sempre responda em português brasileiro, a menos que o dono peça outro idioma.
- Quando precisar de informações atuais, use a ferramenta web_search.
- Seja direto e objetivo.
- Se não sabe algo e não tem ferramentas para descobrir, diga.`

const GUARDRAILS = [
  { id: 'lang', label: 'Idioma padrão', value: 'Português (BR)', editable: false },
  { id: 'max_tool_rounds', label: 'Max tool call rounds', value: '5', editable: true },
  { id: 'max_tasks', label: 'Max tasks por goal', value: '5', editable: true },
  { id: 'retry_limit', label: 'Retry limit por task', value: '3', editable: true },
  { id: 'dry_run_new', label: 'Dry run em tools novas', value: 'Ativo', editable: false },
  { id: 'approval_gate', label: 'Gate de aprovação', value: 'Desativado (v3)', editable: false },
]

type ProviderOption = { id: string; default_model: string }

export default function RulesPage() {
  const [systemPrompt, setSystemPrompt] = useState(DEFAULT_SYSTEM_PROMPT)
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [temperature, setTemperature] = useState('0.7')
  const [saved, setSaved] = useState(false)
  // Catálogo vem de GET /api/settings/providers. Lista hardcoded aqui já ficou
  // velha uma vez (não tinha gemini nem ollama): somar provider no backend não
  // pode exigir editar o front.
  const [providers, setProviders] = useState<ProviderOption[]>([])

  useEffect(() => {
    const apiBase = getApiBase();
    
    fetch(`${apiBase}/api/settings/providers`)
      .then(r => r.json())
      .then(data => setProviders(data.providers ?? []))
      .catch(console.error)

    fetch(`${apiBase}/api/settings/`)
      .then(r => r.json())
      .then(data => {
        if (data.provider) setProvider(data.provider)
        if (data.model) setModel(data.model)
        if (data.temperature !== undefined) setTemperature(data.temperature.toString())
        if (data.system_prompt) setSystemPrompt(data.system_prompt)
      })
      .catch(console.error)
  }, [])

  // Trocar de provider troca o modelo junto. Manter `gemini-2.5-flash` ao mudar
  // para lmstudio só falharia na primeira geração, longe da causa.
  const handleProviderChange = (next: string) => {
    setProvider(next)
    const option = providers.find(p => p.id === next)
    if (option) setModel(option.default_model)
  }

  const handleSave = () => {
    const apiBase = getApiBase();
    fetch(`${apiBase}/api/settings/`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider,
        model,
        temperature: parseFloat(temperature),
        system_prompt: systemPrompt
      })
    })
    .then(() => {
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    })
    .catch(console.error)
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
        <span className="mono glow-text" style={{
          color: 'hsl(var(--neon-cyan))',
          fontSize: 12,
          letterSpacing: '0.1em',
        }}>PROTOCOLS & GUARDRAILS</span>
      </div>

      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: 20,
        display: 'flex',
        flexDirection: 'column',
        gap: 24,
      }}>
        {/* System Prompt */}
        <section>
          <h3 className="mono" style={{
            color: 'hsl(var(--neon-cyan))',
            fontSize: 11,
            letterSpacing: '0.1em',
            marginBottom: 12,
          }}>
            SYSTEM DIRECTIVE
          </h3>
          <div className="hud-panel" style={{ padding: 16 }}>
            <textarea
              value={systemPrompt}
              onChange={e => setSystemPrompt(e.target.value)}
              rows={8}
              style={{
                width: '100%',
                background: 'hsl(var(--hud-panel))',
                border: '1px solid hsl(var(--border-dim))',
                borderRadius: 'var(--radius)',
                color: 'hsl(var(--text-primary))',
                padding: '10px 12px',
                fontSize: 12,
                lineHeight: 1.7,
                fontFamily: "'JetBrains Mono', monospace",
                resize: 'vertical',
                outline: 'none',
              }}
              onFocus={e => {
                e.currentTarget.style.borderColor = 'hsl(var(--neon-cyan) / 0.4)'
              }}
              onBlur={e => {
                e.currentTarget.style.borderColor = 'hsl(var(--border-dim))'
              }}
            />
            <div style={{
              display: 'flex',
              justifyContent: 'flex-end',
              marginTop: 10,
            }}>
              <button
                onClick={handleSave}
                style={{
                  padding: '8px 16px',
                  borderRadius: 'var(--radius)',
                  border: '1px solid hsl(var(--neon-cyan) / 0.3)',
                  background: saved
                    ? 'hsl(var(--neon-green) / 0.15)'
                    : 'hsl(var(--neon-cyan) / 0.1)',
                  color: saved ? 'hsl(var(--neon-green))' : 'hsl(var(--neon-cyan))',
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: 'pointer',
                  letterSpacing: '0.05em',
                  textTransform: 'uppercase',
                  transition: 'all 0.2s',
                }}
              >
                {saved ? '✓ SAVED' : 'SAVE DIRECTIVE'}
              </button>
            </div>
          </div>
        </section>

        {/* Guardrails */}
        <section>
          <h3 className="mono" style={{
            color: 'hsl(var(--neon-cyan))',
            fontSize: 11,
            letterSpacing: '0.1em',
            marginBottom: 12,
          }}>
            GUARDRAILS
          </h3>
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
          }}>
            {GUARDRAILS.map(g => (
              <div
                key={g.id}
                className="hud-panel"
                style={{
                  padding: '12px 16px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                }}
              >
                <span style={{
                  fontSize: 12,
                  color: 'hsl(var(--text-primary))',
                }}>
                  {g.label}
                </span>
                <span className="mono" style={{
                  fontSize: 12,
                  color: g.editable ? 'hsl(var(--neon-cyan))' : 'hsl(var(--text-muted))',
                }}>
                  {g.value}
                </span>
              </div>
            ))}
          </div>
        </section>

        {/* Chief AI Config */}
        <section>
          <h3 className="mono" style={{
            color: 'hsl(var(--neon-cyan))',
            fontSize: 11,
            letterSpacing: '0.1em',
            marginBottom: 12,
          }}>
            CHIEF AI CONFIG
          </h3>
          <div className="hud-panel" style={{ padding: 16 }}>
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 16,
            }}>
              {/* Provider */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span className="mono" style={{ fontSize: 12, color: 'hsl(var(--text-secondary))' }}>PROVIDER</span>
                <select
                  value={provider}
                  onChange={e => handleProviderChange(e.target.value)}
                  style={{
                    background: 'hsl(var(--hud-bg))',
                    border: '1px solid hsl(var(--border-dim))',
                    color: 'hsl(var(--neon-green))',
                    padding: '4px 8px',
                    borderRadius: 'var(--radius)',
                    outline: 'none',
                    fontSize: 12,
                    fontFamily: 'inherit',
                  }}
                >
                  {/* Provider persistido que sumiu do catálogo continua visível,
                      senão o select mostraria outro valor sem o dono ter mexido. */}
                  {provider && !providers.some(p => p.id === provider) && (
                    <option value={provider}>{provider} (não registrado)</option>
                  )}
                  {providers.map(p => (
                    <option key={p.id} value={p.id}>{p.id}</option>
                  ))}
                </select>
              </div>

              {/* Model */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span className="mono" style={{ fontSize: 12, color: 'hsl(var(--text-secondary))' }}>MODEL</span>
                <input
                  type="text"
                  value={model}
                  onChange={e => setModel(e.target.value)}
                  style={{
                    background: 'hsl(var(--hud-bg))',
                    border: '1px solid hsl(var(--border-dim))',
                    color: 'hsl(var(--neon-purple))',
                    padding: '4px 8px',
                    borderRadius: 'var(--radius)',
                    outline: 'none',
                    fontSize: 12,
                    fontFamily: 'inherit',
                    width: 180,
                    textAlign: 'right',
                  }}
                />
              </div>

              {/* Temperature */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span className="mono" style={{ fontSize: 12, color: 'hsl(var(--text-secondary))' }}>TEMP</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.1"
                    value={temperature}
                    onChange={e => setTemperature(e.target.value)}
                    style={{ accentColor: 'hsl(var(--neon-amber))' }}
                  />
                  <span className="mono" style={{ color: 'hsl(var(--neon-amber))', fontSize: 12, minWidth: 24, textAlign: 'right' }}>
                    {temperature}
                  </span>
                </div>
              </div>
            </div>
            
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}>
              <button
                onClick={handleSave}
                style={{
                  padding: '8px 16px',
                  borderRadius: 'var(--radius)',
                  border: '1px solid hsl(var(--neon-cyan) / 0.3)',
                  background: 'hsl(var(--neon-cyan) / 0.1)',
                  color: 'hsl(var(--neon-cyan))',
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: 'pointer',
                  letterSpacing: '0.05em',
                  textTransform: 'uppercase',
                }}
              >
                APPLY CONFIG
              </button>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
