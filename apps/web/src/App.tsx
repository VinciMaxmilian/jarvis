import { useState, lazy, Suspense } from 'react'
import Layout, { type PageId } from './components/Layout'
import ChatPage from './pages/ChatPage'
import { VoiceButton } from './components/VoiceButton'

// Só o chat entra no bundle inicial. As demais páginas — e o mapa neural com
// seus 1.5 MB de grafo — só são baixadas quando o usuário navega até elas.
const BrainPage = lazy(() => import('./pages/BrainPage'))
const MemoryPage = lazy(() => import('./pages/MemoryPage'))
const ToolsPage = lazy(() => import('./pages/ToolsPage'))
const HistoryPage = lazy(() => import('./pages/HistoryPage'))
const RulesPage = lazy(() => import('./pages/RulesPage'))

function PageFallback() {
  return (
    <div style={{
      height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center',
      color: 'var(--ink-3)', fontSize: 12, letterSpacing: '0.1em',
    }} className="mono">
      CARREGANDO…
    </div>
  )
}

export default function App() {
  const [currentPage, setCurrentPage] = useState<PageId>('chat')
  const [selectedChatId, setSelectedChatId] = useState<string | undefined>(undefined)

  return (
    <Layout currentPage={currentPage} onNavigate={setCurrentPage}>
      <Suspense fallback={<PageFallback />}>
        {currentPage === 'chat' && <ChatPage conversationId={selectedChatId} onNewChat={() => setSelectedChatId(crypto.randomUUID())} />}
        {currentPage === 'brain' && <BrainPage />}
        {currentPage === 'memory' && <MemoryPage />}
        {currentPage === 'tools' && <ToolsPage />}
        {currentPage === 'history' && (
          <HistoryPage onSelectChat={(id) => { setSelectedChatId(id); setCurrentPage('chat') }} />
        )}
        {currentPage === 'rules' && <RulesPage />}
      </Suspense>
      <VoiceButton />
    </Layout>
  )
}
