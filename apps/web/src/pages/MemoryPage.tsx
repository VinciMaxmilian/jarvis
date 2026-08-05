import { useEffect, useRef, useState } from 'react'
import { NeuralMap } from '../components/NeuralMap/NeuralMap'
import { getApiBase } from '../config'

/* De quanto em quanto tempo perguntar se a memória mudou. 4s é rápido o
 * bastante para o grafo acompanhar uma conversa (um `knowledge_save` aparece
 * antes de o dono terminar de ler a resposta) e devagar o bastante para não
 * pesar: a resposta são dois campos, e o handler não monta o grafo. */
const INTERVALO_MS = 4000

export default function MemoryPage() {
  const apiBase = getApiBase()
  const [updating, setUpdating] = useState(false)
  /* loadGraph() memoiza por URL, e o NeuralMap só recria o Engine quando a URL
   * muda — o contador é o que força um refetch depois de reindexar. */
  const [versao, setVersao] = useState(0)

  /* --------------------------------------------------------------------- *
   * Recarrega sozinho quando o agente grava ou vetoriza algo.
   *
   * Antes, o grafo só mudava se o dono clicasse em atualizar: gravar um fato
   * pelo chat não movia nada aqui, e a aba mostrava um retrato antigo sem
   * dizer que era antigo. Agora um endpoint barato (/api/memory/version)
   * devolve contagem + updated_at mais recente, e só quando essa assinatura
   * muda é que o `versao` sobe e o NeuralMap refaz o grafo caro.
   *
   * Pausa com a aba em segundo plano: o dono não está vendo, e um polling que
   * roda com a janela minimizada é bateria e CPU gastas para ninguém.
   * --------------------------------------------------------------------- */
  const assinaturaRef = useRef<string | null>(null)

  useEffect(() => {
    let vivo = true

    const checar = async () => {
      if (document.visibilityState !== 'visible') return
      try {
        const res = await fetch(`${apiBase}/api/memory/version`)
        if (!res.ok || !vivo) return
        const { count, hash } = await res.json()
        const assinatura = `${count}:${hash}`
        /* A primeira leitura só registra a linha de base — subir `versao` aqui
         * refaria o grafo que acabou de ser montado, à toa. */
        if (assinaturaRef.current === null) {
          assinaturaRef.current = assinatura
          return
        }
        if (assinaturaRef.current !== assinatura) {
          assinaturaRef.current = assinatura
          setVersao(v => v + 1)
        }
      } catch {
        /* Rede caiu ou API reiniciando: o próximo tique tenta de novo. Sem
         * ruído no console — isto roda a cada 4s e um erro por tique viraria
         * spam que esconde erro de verdade. */
      }
    }

    checar()
    const id = window.setInterval(checar, INTERVALO_MS)
    document.addEventListener('visibilitychange', checar)
    return () => {
      vivo = false
      window.clearInterval(id)
      document.removeEventListener('visibilitychange', checar)
    }
  }, [apiBase])

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
