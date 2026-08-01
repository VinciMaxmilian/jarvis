/** Histórico e estatísticas — `apps/api/routers/history.py`. */

import { api } from './client';

/** `ChatPreview` do router. */
export interface ChatPreview {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  preview_text: string;
}

/** `ChatMessageResponse` do router. */
export interface StoredChatMessage {
  id: string;
  role: string;
  content: string;
  created_at: string;
  tool_calls: unknown[] | null;
}

export interface ModelStats {
  model: string;
  input_tokens: number;
  output_tokens: number;
}

export interface ToolUsage {
  tool: string;
  count: number;
}

export interface StatsResponse {
  models: ModelStats[];
  tools: ToolUsage[];
}

/** `GET /api/history/chats` — 50 conversas mais recentes. */
export async function listChats(): Promise<ChatPreview[]> {
  const { data } = await api.get<ChatPreview[]>('/api/history/chats');
  return data;
}

/** `GET /api/history/chats/{conversation_id}/messages` — até 100 mensagens. */
export async function listChatMessages(conversationId: string): Promise<StoredChatMessage[]> {
  const { data } = await api.get<StoredChatMessage[]>(
    `/api/history/chats/${conversationId}/messages`,
  );
  return data;
}

/** `GET /api/history/stats` */
export async function getStats(): Promise<StatsResponse> {
  const { data } = await api.get<StatsResponse>('/api/history/stats');
  return data;
}
