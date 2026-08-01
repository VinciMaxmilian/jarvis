/**
 * A conversa ativa: mensagens, socket e o que o brain precisa saber.
 *
 * ## Por que o socket mora aqui e não na tela
 *
 * `ChatScreen` é uma aba. Numa navegação por abas a tela é desmontada e
 * remontada conforme o usuário circula, e um socket preso ao ciclo de vida dela
 * cairia (e reconectaria, e reautenticaria no Access) toda vez que alguém fosse
 * ver o histórico. Aqui o socket sobrevive à navegação e morre junto do app —
 * que é o tempo de vida que a conversa realmente tem.
 *
 * ## Os dois contadores (`activation` / `resetSeq`)
 *
 * O brain vive dentro de um WebView e não lê estado do React: ele recebe
 * chamadas por `injectJavaScript`. Comandos, não estado. Para transformar
 * "aconteceu um tool_call" em uma chamada exatamente-uma-vez, o que a store
 * publica é um contador monotônico:
 *
 * - `activation.seq` sobe a cada `tool_call` com caminho identificável; o
 *   `BrainCanvas` reage à *mudança* do número e injeta `activate(paths)`.
 * - `resetSeq` sobe quando começa outra conversa; o brain volta ao cinza.
 *
 * Guardar apenas uma lista de caminhos não serviria: dois `tool_call` seguidos
 * no mesmo arquivo produziriam listas iguais, o `useEffect` não dispararia, e o
 * segundo acender nunca aconteceria.
 */

import * as Crypto from 'expo-crypto';
import { create } from 'zustand';

import {
  ChatSocket,
  sendChatOverHttp,
  toolCallTargetPath,
  type ChatChunk,
} from '../api/chat';
import { describeError } from '../api/client';
import { listChatMessages } from '../api/history';

export type MessageRole = 'user' | 'assistant' | 'system';

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  /** Epoch ms — `Date` não sobrevive bem a comparação por identidade no React. */
  createdAt: number;
  /** A mensagem ainda está sendo escrita pelo modelo. */
  streaming?: boolean;
  /** Nomes das tools chamadas durante esta resposta, na ordem. */
  tools?: string[];
}

/** Por onde a última mensagem saiu — a tela avisa quando não é o socket. */
export type Transport = 'ws' | 'http';

interface ChatState {
  conversationId: string;
  messages: ChatMessage[];
  connected: boolean;
  streaming: boolean;
  transport: Transport;
  /** Falha da última tentativa de envio, para a tela mostrar e não engolir. */
  error: string | null;
  loadingHistory: boolean;

  activation: { seq: number; paths: string[] };
  resetSeq: number;

  connect: () => void;
  disconnect: () => void;
  send: (text: string) => Promise<void>;
  startNewConversation: () => void;
  loadConversation: (conversationId: string) => Promise<void>;
  clearError: () => void;
}

/**
 * Fora do estado do zustand de propósito: é um objeto mutável com socket
 * dentro, não um valor que a UI observa. Guardá-lo no estado obrigaria a
 * recriá-lo a cada `set` para manter a imutabilidade — e recriar um socket é
 * exatamente o que não se quer.
 */
let socket: ChatSocket | null = null;

function newId(): string {
  return Crypto.randomUUID();
}

/**
 * Aplica uma transformação à mensagem que está sendo escrita agora.
 *
 * Todas as reações a chunk mexem na última mensagem se — e somente se — ela
 * ainda estiver em streaming. Centralizar a condição evita o bug clássico de um
 * chunk atrasado sobrescrever uma mensagem já finalizada.
 */
function patchStreaming(
  messages: ChatMessage[],
  patch: (message: ChatMessage) => ChatMessage,
): ChatMessage[] {
  const last = messages[messages.length - 1];
  if (!last?.streaming) return messages;
  return [...messages.slice(0, -1), patch(last)];
}

export const useChatStore = create<ChatState>((set, get) => ({
  conversationId: newId(),
  messages: [],
  connected: false,
  streaming: false,
  transport: 'ws',
  error: null,
  loadingHistory: false,

  activation: { seq: 0, paths: [] },
  resetSeq: 0,

  connect: () => {
    if (socket) {
      socket.connect();
      return;
    }
    socket = new ChatSocket({
      onConnectionChange: (connected) => set({ connected }),
      onChunk: (chunk: ChatChunk) => {
        const state = get();

        if (chunk.type === 'text') {
          set({
            messages: patchStreaming(state.messages, (m) => ({
              ...m,
              content: m.content + chunk.text,
            })),
          });
          return;
        }

        if (chunk.type === 'tool_call') {
          const name = chunk.tool_call?.name ?? 'tool';
          const path = chunk.tool_call ? toolCallTargetPath(chunk.tool_call) : null;
          set({
            messages: patchStreaming(state.messages, (m) => ({
              ...m,
              tools: [...(m.tools ?? []), name],
            })),
            // Tool sem caminho identificável não acende nada — mas continua
            // aparecendo como chip na mensagem, que é onde ela é informação.
            activation: path
              ? { seq: state.activation.seq + 1, paths: [path] }
              : state.activation,
          });
          return;
        }

        if (chunk.type === 'done') {
          set({
            streaming: false,
            messages: patchStreaming(state.messages, (m) => ({ ...m, streaming: false })),
            // O servidor gera um id quando o cliente não manda um. Adotar o dele
            // é o que mantém a conversa contínua depois de um reconnect.
            conversationId: chunk.conversation_id ?? state.conversationId,
          });
          return;
        }

        if (chunk.type === 'error') {
          set({
            streaming: false,
            messages: [
              ...patchStreaming(state.messages, (m) => ({ ...m, streaming: false })),
              {
                id: newId(),
                role: 'system',
                content: chunk.error || 'Erro desconhecido no servidor.',
                createdAt: Date.now(),
              },
            ],
          });
        }
      },
    });
    socket.connect();
  },

  disconnect: () => {
    socket?.dispose();
    socket = null;
    set({ connected: false });
  },

  send: async (text: string) => {
    const content = text.trim();
    if (!content || get().streaming) return;

    const conversationId = get().conversationId;
    const userMessage: ChatMessage = {
      id: newId(),
      role: 'user',
      content,
      createdAt: Date.now(),
    };
    const placeholder: ChatMessage = {
      id: newId(),
      role: 'assistant',
      content: '',
      createdAt: Date.now(),
      streaming: true,
      tools: [],
    };

    set((state) => ({
      messages: [...state.messages, userMessage, placeholder],
      streaming: true,
      error: null,
    }));

    if (socket?.send(content, conversationId)) {
      set({ transport: 'ws' });
      return;
    }

    // Socket fora: resposta inteira de uma vez, sem streaming e sem brain. A
    // tela diz isso pelo `transport`, em vez de fingir que o canal é o mesmo.
    set({ transport: 'http' });
    try {
      const response = await sendChatOverHttp(content, conversationId);
      set((state) => ({
        streaming: false,
        conversationId: response.conversation_id || state.conversationId,
        messages: patchStreaming(state.messages, (m) => ({
          ...m,
          content: response.reply,
          streaming: false,
        })),
      }));
    } catch (error) {
      const detail = describeError(error);
      set((state) => ({
        streaming: false,
        error: detail,
        messages: [
          ...patchStreaming(state.messages, (m) => ({ ...m, streaming: false })),
          { id: newId(), role: 'system', content: detail, createdAt: Date.now() },
        ],
      }));
    }
  },

  startNewConversation: () => {
    set((state) => ({
      conversationId: newId(),
      messages: [],
      streaming: false,
      error: null,
      resetSeq: state.resetSeq + 1,
    }));
  },

  loadConversation: async (conversationId: string) => {
    if (get().conversationId === conversationId && get().messages.length > 0) return;

    set((state) => ({
      conversationId,
      messages: [],
      streaming: false,
      error: null,
      loadingHistory: true,
      // Conversa carregada do histórico começa com o cérebro cinza: o que ele
      // pinta é o que acontece AGORA, e os tool_calls antigos não foram vividos
      // nesta sessão.
      resetSeq: state.resetSeq + 1,
    }));

    try {
      const stored = await listChatMessages(conversationId);
      set({
        loadingHistory: false,
        messages: stored.map((message) => ({
          id: message.id,
          // O banco guarda também `tool`/`system`; qualquer coisa que não seja
          // do usuário é renderizada como resposta.
          role: message.role === 'user' ? 'user' : 'assistant',
          content: message.content,
          createdAt: Date.parse(message.created_at) || Date.now(),
          tools: (message.tool_calls ?? [])
            .map((call) => (call as { name?: unknown } | null)?.name)
            .filter((name): name is string => typeof name === 'string'),
        })),
      });
    } catch (error) {
      set({ loadingHistory: false, error: describeError(error) });
    }
  },

  clearError: () => set({ error: null }),
}));
