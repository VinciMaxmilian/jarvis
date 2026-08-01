/** Registro de tools — `apps/api/routers/tools.py`. */

import { api } from './client';

export interface ToolInfo {
  name: string;
  description: string;
  idempotent: boolean;
  requires_approval: boolean;
}

/** `GET /api/tools/` */
export async function listTools(): Promise<ToolInfo[]> {
  const { data } = await api.get<ToolInfo[]>('/api/tools/');
  return data;
}
