/**
 * Canal de chat.
 *
 * ## Por que WebSocket, e não `POST /api/chat/`
 *
 * As duas rotas existem (`apps/api/routers/chat.py`) e não são equivalentes.
 * Três motivos decidem, do mais forte para o mais fraco:
 *
 * 1. **O `POST` joga fora os `tool_call`.** `chat_post` acumula só
 *    `chunk.type == "text"` e descarta o resto. Os `tool_call` são exatamente o
 *    que acende o brain desta aba — pelo HTTP o cérebro nunca sairia do cinza.
 *    Isso sozinho já resolveria a escolha.
 * 2. **O `fetch` do React Native não faz streaming de resposta.** Não existe
 *    `response.body` como `ReadableStream` no runtime do RN; o corpo só chega
 *    inteiro, no fim. O `POST` portanto não é "streaming mais lento", é
 *    *nenhum* streaming: a tela ficaria parada durante toda a geração e depois
 *    receberia o texto de uma vez, com uma requisição HTTP aberta o tempo todo —
 *    justamente o que rádio de celular e proxy intermediário adoram matar.
 * 3. **O `WebSocket` do RN aceita headers customizados**, num terceiro argumento
 *    que o navegador não tem. É o que permite anexar `Cookie: CF_Authorization=…`
 *    e `Cf-Access-Jwt-Assertion: …` no handshake. No navegador o PWA depende do
 *    cookie ser mandado sozinho; aqui a credencial é explícita, o que remove a
 *    dúvida de qual jar o sistema usou.
 *
 * O `POST` fica como degradação declarada: se o socket não sobe (proxy que corta
 * Upgrade, rede hostil), `sendChatOverHttp` entrega a resposta completa de uma
 * vez. Sem streaming e sem brain — e a tela diz isso, em vez de fingir.
 */

import axios from 'axios';

import { API_BASE_URL, WS_BASE_URL } from '../config';
import { useAuthStore } from '../store/useAuthStore';

export interface ToolCallPayload {
  name: string;
  /** O backend serializa com `default=str`; já chegou como objeto e como string. */
  arguments: Record<string, unknown> | string;
}

export type ChatChunk =
  | { type: 'text'; text: string }
  | { type: 'tool_call'; tool_call: ToolCallPayload }
  | { type: 'error'; error: string }
  | { type: 'done'; conversation_id?: string };

export interface ChatSocketHandlers {
  onChunk: (chunk: ChatChunk) => void;
  onConnectionChange: (connected: boolean) => void;
}

/**
 * O construtor de `WebSocket` do React Native, com o terceiro argumento que a
 * definição DOM não conhece.
 *
 * O cast é local e nomeado em vez de um `as any` no ponto de uso: a extensão é
 * real e documentada, o que falta é o tipo global refleti-la. Assim o `headers`
 * continua sendo verificado.
 */
type WebSocketWithHeaders = new (
  url: string,
  protocols?: string | string[] | null,
  options?: { headers?: Record<string, string> },
) => WebSocket;

const RNWebSocket = WebSocket as unknown as WebSocketWithHeaders;

/** Fechamento por violação de política — o que o gate do Access usa ao negar. */
const WS_POLICY_VIOLATION = 1008;

const RECONNECT_DELAYS_MS = [1_000, 2_000, 4_000, 8_000, 15_000];

export class ChatSocket {
  private socket: WebSocket | null = null;
  private attempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private disposed = false;

  constructor(private readonly handlers: ChatSocketHandlers) {}

  get isOpen(): boolean {
    return this.socket?.readyState === 1; // WebSocket.OPEN
  }

  connect(): void {
    if (this.disposed || this.socket) return;

    const socket = new RNWebSocket(`${WS_BASE_URL}/api/chat/ws`, undefined, {
      headers: useAuthStore.getState().authHeaders(),
    });
    this.socket = socket;

    socket.onopen = () => {
      this.attempt = 0;
      this.handlers.onConnectionChange(true);
    };

    socket.onmessage = (event: WebSocketMessageEvent) => {
      if (typeof event.data !== 'string') return;
      let chunk: ChatChunk;
      try {
        chunk = JSON.parse(event.data) as ChatChunk;
      } catch {
        // Frame não-JSON não deveria existir neste protocolo. Ignorar é melhor
        // que derrubar o socket: a próxima mensagem provavelmente presta.
        return;
      }
      this.handlers.onChunk(chunk);
    };

    socket.onerror = () => {
      // `onerror` no RN não traz detalhe utilizável e é sempre seguido de
      // `onclose`. A reconexão mora lá, para não disparar duas vezes.
    };

    socket.onclose = (event: WebSocketCloseEvent) => {
      this.socket = null;
      this.handlers.onConnectionChange(false);
      if (this.disposed) return;

      if (event?.code === WS_POLICY_VIOLATION) {
        // O gate do Access fecha com 1008 ANTES do accept quando a asserção não
        // presta (`_deny` em `apps/api/cf_access.py`). Reconectar seria repetir a
        // mesma credencial recusada num laço; o que resolve é logar de novo.
        void useAuthStore.getState().signOut('Cloudflare Access recusou a conexão.');
        return;
      }

      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    const delay = RECONNECT_DELAYS_MS[Math.min(this.attempt, RECONNECT_DELAYS_MS.length - 1)];
    this.attempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  /** `true` se a mensagem saiu pelo socket; `false` pede o fallback HTTP. */
  send(message: string, conversationId: string): boolean {
    if (!this.socket || this.socket.readyState !== 1) return false;
    this.socket.send(JSON.stringify({ message, conversation_id: conversationId }));
    return true;
  }

  dispose(): void {
    this.disposed = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      // Zerar o handler antes de fechar: senão o `onclose` do próprio unmount
      // agenda uma reconexão para um componente que não existe mais.
      socket.onclose = null;
      socket.close();
    }
  }
}

export interface ChatHttpResponse {
  reply: string;
  conversation_id: string;
}

/**
 * Fallback sem streaming — `POST /api/chat/`.
 *
 * Timeout próprio e longo (5 min): aqui, ao contrário das rotas REST, há uma
 * geração de LLM inteira acontecendo dentro da requisição.
 */
export async function sendChatOverHttp(
  message: string,
  conversationId: string,
): Promise<ChatHttpResponse> {
  const response = await axios.post<ChatHttpResponse>(
    `${API_BASE_URL}/api/chat/`,
    { message, conversation_id: conversationId },
    {
      timeout: 300_000,
      headers: { Accept: 'application/json', ...useAuthStore.getState().authHeaders() },
      withCredentials: true,
    },
  );
  return response.data;
}

/**
 * Caminho de arquivo mencionado nos argumentos de uma tool, se houver.
 *
 * As chaves são as mesmas que o PWA já reconhece (`ChatPage.tsx`): as tools de
 * arquivo do Jarvis nomeiam o alvo com uma delas. Tool sem alvo de arquivo
 * devolve `null` e simplesmente não acende nada — o brain reage ao que sabe
 * localizar, não a toda chamada.
 */
export function toolCallTargetPath(toolCall: ToolCallPayload): string | null {
  let args: unknown = toolCall.arguments;
  if (typeof args === 'string') {
    try {
      args = JSON.parse(args);
    } catch {
      return null;
    }
  }
  if (!args || typeof args !== 'object') return null;

  const record = args as Record<string, unknown>;
  const keys = ['TargetFile', 'AbsolutePath', 'SearchPath', 'DirectoryPath', 'Target', 'path', 'file'];
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return null;
}
