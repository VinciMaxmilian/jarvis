import { useEffect, useState } from 'react'
import { getApiBase } from '../config'

export default function MemoryPage() {
  const [htmlContent, setHtmlContent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const apiBase = getApiBase()
    fetch(`${apiBase}/api/memory/memory.html`)
      .then(res => {
        if (!res.ok) throw new Error('Failed to load memory graph')
        return res.json()
      })
      .then(data => {
        if (data.html) {
          setHtmlContent(data.html)
        } else {
          throw new Error('Invalid response format')
        }
      })
      .catch(err => {
        console.error(err)
        setError(err.message)
      })
  }, [])
  
  if (error) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', color: 'var(--red)' }}>
        Error loading memory: {error}
      </div>
    )
  }

  if (!htmlContent) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', color: 'var(--ink-3)' }}>
        Loading memory graph...
      </div>
    )
  }

  return (
    <div style={{ width: '100%', height: '100%' }}>
      <iframe 
        srcDoc={htmlContent} 
        style={{ width: '100%', height: '100%', border: 'none' }} 
        title="Memory Visualization"
      />
    </div>
  )
}
