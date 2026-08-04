import { useState, useRef, useEffect, useCallback, lazy, Suspense } from 'react'
import { getApiBase } from '../config'
import Markdown from '../components/Markdown'
import { useImageStore } from '../stores/useImageStore'
import { Paperclip, X } from 'lucide-react'

interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: Date
  isStreaming?: boolean
}

interface WsChunk {
  type: 'text' | 'tool_call' | 'done' | 'error' | 'image_analysis_started'
  text?: string
  tool_call?: { name: string; arguments: Record<string, unknown> }
  error?: string
  conversation_id?: string
  image_url?: string
}

/** Escreve o texto recebido na bolha certa — e, se não houver, cria uma.
 *
 * A versão anterior procurava "a última mensagem, se `isStreaming`" e fazia
 * `return prev` quando não achava: texto descartado em silêncio, bolha vazia na
 * tela e nenhum rastro de erro. O backend gravava a resposta no Postgres e ela
 * simplesmente não aparecia.
 *
 * Três tentativas, nesta ordem, e a última não pode falhar:
 *   1. a bolha de id conhecido (caso normal);
 *   2. a última bolha do assistente ainda em streaming — cobre o ref perdido por
 *      HMR do Vite, que troca o módulo mas mantém o socket antigo vivo;
 *   3. uma bolha nova. Melhor mensagem fora de lugar que mensagem sumida.
 */
function aplicarTexto(
  prev: ChatMessage[],
  texto: string,
  alvoId: string | null
): ChatMessage[] {
  if (alvoId && prev.some(m => m.id === alvoId)) {
    return prev.map(m => (m.id === alvoId ? { ...m, content: texto } : m))
  }

  for (let i = prev.length - 1; i >= 0; i--) {
    if (prev[i].role === 'assistant' && prev[i].isStreaming) {
      const copia = [...prev]
      copia[i] = { ...copia[i], content: texto }
      return copia
    }
  }

  return [
    ...prev,
    {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: texto,
      timestamp: new Date(),
      isStreaming: true,
    },
  ]
}

function useChat(initialConversationId?: string) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const [conversationId, setConversationId] = useState(initialConversationId || crypto.randomUUID())
  const wsRef = useRef<WebSocket | null>(null)
  const streamBufferRef = useRef('')
  // Id da bolha que está recebendo esta resposta.
  //
  // Antes, cada chunk procurava "a última mensagem da lista, se isStreaming".
  // Isso descarta o texto EM SILÊNCIO (`return prev`) sempre que a lista muda
  // entre o envio e a chegada da resposta — e o `done` seguinte fecha a bolha
  // vazia, que é o sintoma observado: o backend gravou 4 respostas no Postgres e
  // só a primeira apareceu na tela. Endereçar por id não depende da posição nem
  // do que mais aconteceu com a lista no meio do caminho.
  const streamingIdRef = useRef<string | null>(null)
  const [activeNodes, setActiveNodes] = useState<string[]>([])

  useEffect(() => {
    if (initialConversationId && initialConversationId !== conversationId) {
      setConversationId(initialConversationId)
      setMessages([])
    }
  }, [initialConversationId])

  useEffect(() => {
    if (!initialConversationId) return
    let mounted = true
    const apiBase = getApiBase();
    fetch(`${apiBase}/api/history/chats/${initialConversationId}/messages`)
      .then(res => res.ok ? res.json() : [])
      .then(data => {
        if (!mounted) return
        const formatted = data.map((msg: any) => ({
          id: msg.id,
          role: msg.role === 'user' ? 'user' : 'assistant',
          content: msg.content,
          timestamp: new Date(msg.created_at)
        }))
        setMessages(formatted)
      })
      .catch(() => {})
    return () => { mounted = false }
  }, [initialConversationId])

  useEffect(() => {
    let timeoutId: number;
    let ws: WebSocket | null = null;
    let mounted = true;

    const connect = () => {
      if (!mounted) return;
      // Já existe socket vivo? Não abra outro. Em desenvolvimento o StrictMode
      // monta o efeito duas vezes e os logs da API mostravam DOIS
      // `WebSocket /api/chat/ws [accepted]` por carregamento, sem nenhum
      // `connection closed` — dois sockets, e `send` falando com apenas um.
      const atual = wsRef.current;
      if (
        atual &&
        (atual.readyState === WebSocket.OPEN ||
          atual.readyState === WebSocket.CONNECTING)
      ) {
        return;
      }
      const apiBase = getApiBase();
      let wsUrl = '';
      if (apiBase) {
        const wsBase = apiBase.replace(/^http/, 'ws');
        wsUrl = `${wsBase}/api/chat/ws`;
      } else {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        wsUrl = `${protocol}//${window.location.host}/api/chat/ws`;
      }
      ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        if (mounted) setIsConnected(true);
      };
      
      ws.onclose = () => {
        if (mounted) {
          setIsConnected(false);
          timeoutId = window.setTimeout(connect, 3000);
        }
      };
      
      ws.onerror = () => ws?.close();

      ws.onmessage = (event) => {
        if (!mounted) return;
        const chunk: WsChunk = JSON.parse(event.data);

        if (chunk.type === 'text' && chunk.text) {
          streamBufferRef.current += chunk.text;
          const currentText = streamBufferRef.current;
          const currentId = streamingIdRef.current;
          setMessages(prev =>
            aplicarTexto(prev, currentText, currentId)
          );
        } else if (chunk.type === 'tool_call' && chunk.tool_call) {
          let args = chunk.tool_call.arguments || {};
          if (typeof args === 'string') {
            try { args = JSON.parse(args); } catch(e) {}
          }
          let targetPath = "";
          // Extract file path from common tool arguments
          if (typeof args.TargetFile === 'string') targetPath = args.TargetFile;
          else if (typeof args.AbsolutePath === 'string') targetPath = args.AbsolutePath;
          else if (typeof args.SearchPath === 'string') targetPath = args.SearchPath;
          else if (typeof args.DirectoryPath === 'string') targetPath = args.DirectoryPath;
          else if (typeof args.Target === 'string') targetPath = args.Target;

          if (targetPath) {
            // Convert absolute path to relative or just use it, Engine does fuzzy matching
            setActiveNodes(prev => {
              const next = new Set(prev);
              next.add(targetPath);
              return Array.from(next);
            });
          }

          streamBufferRef.current += `\n⚡ ${chunk.tool_call.name}`;
          const currentText = streamBufferRef.current;
          const currentId = streamingIdRef.current;
          setMessages(prev =>
            aplicarTexto(prev, currentText, currentId)
          );
        } else if (chunk.type === 'image_analysis_started' && chunk.image_url) {
          useImageStore.getState().openModal(chunk.image_url);
        } else if (chunk.type === 'done') {
          // Fecha TUDO que estiver em streaming, não só o id conhecido: bolha
          // que ficasse aberta mostraria os três pontinhos para sempre.
          setMessages(prev =>
            prev.map(m => (m.isStreaming ? { ...m, isStreaming: false } : m))
          );
          streamingIdRef.current = null;
          setIsStreaming(false);
          streamBufferRef.current = '';
          
          // Clear active nodes after 15 seconds to simulate cooldown
          setTimeout(() => {
            if (mounted) setActiveNodes([]);
          }, 15000);
          
        } else if (chunk.type === 'error') {
          setMessages(prev => [
            ...prev,
            { id: crypto.randomUUID(), role: 'system', content: `⚠ ${chunk.error}`, timestamp: new Date() },
          ]);
          streamingIdRef.current = null;
          setIsStreaming(false);
          streamBufferRef.current = '';
          setActiveNodes([]);
        }
      };
    };

    connect();

    return () => {
      mounted = false;
      window.clearTimeout(timeoutId);
      if (ws) {
        ws.onclose = null;
        ws.close();
      }
      wsRef.current = null;
    };
  }, []);

  const send = useCallback((text: string, images?: string[], files?: {name: string, content: string}[]) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return

    let displayContent = text;
    if (images && images.length > 0) {
      displayContent += '\n\n' + images.map((img, i) => `![Anexo ${i+1}](${img})`).join('\n');
    }
    if (files && files.length > 0) {
      displayContent += '\n\n' + files.map(f => `📄 **Anexo:** ${f.name}`).join('\n');
    }

    setMessages(prev => [
      ...prev,
      { id: crypto.randomUUID(), role: 'user', content: displayContent, timestamp: new Date() },
    ])

    streamBufferRef.current = ''
    setActiveNodes([])
    // O id é gerado ANTES do append e guardado no ref: é ele que os chunks vão
    // procurar. Gerá-lo dentro do updater tornaria o alvo desconhecido para quem
    // recebe a resposta.
    const respostaId = crypto.randomUUID()
    streamingIdRef.current = respostaId
    setMessages(prev => [
      ...prev,
      { id: respostaId, role: 'assistant', content: '', timestamp: new Date(), isStreaming: true },
    ])
    setIsStreaming(true)

    wsRef.current.send(JSON.stringify({ 
      message: text, 
      conversation_id: conversationId,
      images: images || [],
      files: files || []
    }))
  }, [conversationId])

  return { messages, send, isConnected, isStreaming, activeNodes }
}

const NeuralMap = lazy(() =>
  import('../components/NeuralMap/NeuralMap').then(m => ({ default: m.NeuralMap }))
)

export default function ChatPage({ conversationId, onNewChat }: { conversationId?: string, onNewChat?: () => void }) {
  const { messages, send, isConnected, isStreaming, activeNodes } = useChat(conversationId)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [showBackdrop, setShowBackdrop] = useState(false)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // O mapa de fundo é decoração: puxar 1.5 MB de grafo e montar o canvas antes
  // do chat estar utilizável só atrasa o primeiro paint.
  useEffect(() => {
    const idle = window.requestIdleCallback ?? ((cb: () => void) => window.setTimeout(cb, 800))
    const id = idle(() => setShowBackdrop(true))
    return () => {
      if (window.cancelIdleCallback) window.cancelIdleCallback(id as number)
      else window.clearTimeout(id as number)
    }
  }, [])

  useEffect(() => {
    const handleSaveImage = (e: Event) => {
      const customEvent = e as CustomEvent;
      const filters = customEvent.detail?.filters;
      if (filters) {
        send(`Please save the currently analyzed image with these filters applied: brightness ${filters.brightness}%, contrast ${filters.contrast}%, saturation ${filters.saturation}%. Use the save_modified_image tool.`);
      }
    };
    window.addEventListener('jarvis:save_image', handleSaveImage);
    return () => window.removeEventListener('jarvis:save_image', handleSaveImage);
  }, [send])

  return (
    <div style={{
      position: 'relative',
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
    }}>
      {/* Background Neural Map */}
      {showBackdrop && (
        <div style={{
          position: 'absolute',
          inset: 0,
          zIndex: 0,
          pointerEvents: 'none'
        }}>
          <Suspense fallback={null}>
            <NeuralMap backgroundMode={true} activeNodes={activeNodes} />
          </Suspense>
        </div>
      )}

      {/* Foreground Content */}
      <div style={{
        position: 'relative',
        zIndex: 1,
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        background: 'transparent'
      }}>
        {/* Header */}
        <div style={{
          padding: '14px 20px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'var(--neu-surface)',
          boxShadow: '0 6px 14px -12px var(--neu-lo)',
        }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span className="mono" style={{
            color: 'var(--ink-2)',
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: '0.12em',
          }}>COMMS CHANNEL</span>
          {onNewChat && (
            <button
              onClick={onNewChat}
              title="Nova Conversa"
              style={{
                background: 'transparent',
                border: 'none',
                cursor: 'pointer',
                color: 'var(--ink-3)',
                fontSize: 14,
                padding: '4px 8px',
                borderRadius: '6px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--neu-inset)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              ➕
            </button>
          )}
        </div>
        <div className="status-badge" style={{
          color: isConnected ? 'hsl(var(--neon-green))' : 'hsl(var(--neon-red))',
        }}>
          <div className={isConnected ? 'animate-pulse-ring' : ''} style={{
            width: 6, height: 6, borderRadius: '50%',
            background: 'currentColor',
          }} />
          <span className="mono">{isConnected ? 'LINKED' : 'OFFLINE'}</span>
        </div>
      </div>

      {/* Messages */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: '16px 20px',
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
      }}>
        {messages.length === 0 && (
          <div style={{
            flex: 1, display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center', gap: 12, opacity: 0.5,
          }}>
            <div style={{ fontSize: 40 }}>⚡</div>
            <p className="mono" style={{
              color: 'hsl(var(--text-muted))', textAlign: 'center',
              maxWidth: 300, lineHeight: 1.8, fontSize: 12,
            }}>
              JARVIS ONLINE. AWAITING DIRECTIVE.
            </p>
          </div>
        )}

        {messages.map(msg => (
          <div
            key={msg.id}
            className="animate-fade-in"
            style={{
              display: 'flex',
              justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
            }}
          >
            <div
              className={msg.role === 'user' ? '' : 'neu-raised'}
              style={{
                maxWidth: '80%',
                padding: '12px 16px',
                borderRadius: msg.role === 'user'
                  ? 'var(--radius) var(--radius) 6px var(--radius)'
                  : 'var(--radius) var(--radius) var(--radius) 6px',
                background: msg.role === 'user'
                  ? 'linear-gradient(145deg, var(--accent-soft), var(--accent))'
                  : undefined,
                boxShadow: msg.role === 'user'
                  ? 'var(--neu-sm), 0 8px 18px -8px var(--accent-glow)'
                  : undefined,
                border: msg.role === 'user' ? '1px solid transparent' : undefined,
                color: msg.role === 'user'
                  ? 'var(--accent-ink)'
                  : msg.role === 'system'
                    ? 'hsl(var(--neon-red))'
                    : 'var(--ink)',
                fontSize: 13,
                lineHeight: 1.7,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}
            >
              <Markdown>{msg.content}</Markdown>
              {msg.isStreaming && !msg.content && (
                <div style={{ display: 'flex', gap: 4, padding: '4px 0' }}>
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <ChatInput isConnected={isConnected} isStreaming={isStreaming} onSend={send} />
      </div>
    </div>
  )
}

interface Attachment {
  file: File;
  name: string;
  type: string;
  content: string;
}

function ChatInput({ isConnected, isStreaming, onSend }: { isConnected: boolean, isStreaming: boolean, onSend: (text: string, images?: string[], files?: {name: string, content: string}[]) => void }) {
  const [input, setInput] = useState('')
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files) return;
    const newAttachments: Attachment[] = [];
    for (const file of Array.from(e.target.files)) {
      if (file.size > 5 * 1024 * 1024) {
         alert(`Arquivo ${file.name} muito grande (max 5MB)`);
         continue;
      }
      
      const content = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (ev) => resolve(ev.target?.result as string);
        reader.onerror = reject;
        if (file.type.startsWith('image/')) {
          reader.readAsDataURL(file);
        } else {
          reader.readAsText(file);
        }
      });
      
      newAttachments.push({
        file,
        name: file.name,
        type: file.type,
        content
      });
    }
    setAttachments(prev => [...prev, ...newAttachments]);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }

  const removeAttachment = (index: number) => {
    setAttachments(prev => prev.filter((_, i) => i !== index));
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if ((!input.trim() && attachments.length === 0) || isStreaming) return
    
    const images = attachments.filter(a => a.type.startsWith('image/')).map(a => a.content);
    const files = attachments.filter(a => !a.type.startsWith('image/')).map(a => ({ name: a.name, content: a.content }));
    
    onSend(input.trim(), images, files)
    setInput('')
    setAttachments([])
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {attachments.length > 0 && (
        <div style={{ display: 'flex', gap: 8, padding: '8px 20px', background: 'var(--neu-bg)', flexWrap: 'wrap' }}>
          {attachments.map((att, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'var(--neu-surface)', padding: '4px 10px', borderRadius: 4, fontSize: '0.8rem', border: '1px solid var(--color-accent-300)' }}>
               <span>{att.name}</span>
               <X size={14} style={{ cursor: 'pointer' }} onClick={() => removeAttachment(i)} />
            </div>
          ))}
        </div>
      )}
      <form
        onSubmit={handleSubmit}
        style={{
          padding: '14px 20px',
          background: 'var(--neu-surface)',
          boxShadow: '0 -6px 14px -12px var(--neu-lo)',
          display: 'flex',
          gap: 10,
        }}
      >
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--color-text)' }}
          disabled={!isConnected || isStreaming}
        >
          <Paperclip size={20} />
        </button>
        <input 
          type="file" 
          multiple 
          ref={fileInputRef} 
          style={{ display: 'none' }} 
          onChange={handleFileChange}
          accept="image/*,text/*,.csv,.json,.md"
        />
        <input
          className="neu-input"
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder={isConnected ? 'Enter directive...' : 'Reconnecting...'}
          disabled={!isConnected || isStreaming}
          style={{ flex: 1 }}
        />
        <button
          className="neu-btn neu-btn-primary"
          type="submit"
          disabled={!isConnected || isStreaming}
        >
          Send
        </button>
      </form>
    </div>
  )
}
