/**
 * Metas e tarefas — `apps/api/routers/goals.py`.
 *
 * Os tipos abaixo são a transcrição de `Goal` e `Task` de
 * `packages/shared/contracts.py` no que o FastAPI serializa (datas viram string
 * ISO, `UUID` vira string). Campos que a UI móvel não usa ficam de fora de
 * propósito: declarar o que não se lê só cria a impressão de que se lê.
 */

import { api } from './client';

/** `GoalStatus` de `packages/shared/contracts.py`. */
export type GoalStatus = 'draft' | 'active' | 'blocked' | 'done' | 'failed' | 'cancelled';

/** `TaskStatus` de `packages/shared/contracts.py`. */
export type TaskStatus =
  | 'pending'
  | 'running'
  | 'waiting_approval'
  | 'done'
  | 'failed'
  | 'cancelled';

export interface Goal {
  id: string;
  title: string;
  description: string;
  status: GoalStatus;
  priority: number;
  parent_goal_id: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface Task {
  id: string;
  goal_id: string;
  title: string;
  status: TaskStatus;
  capability: string | null;
  tool: string | null;
  error: string | null;
  attempts: number;
  max_attempts: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

/** `GET /api/goals/` — a barra final importa: sem ela o FastAPI redireciona. */
export async function listGoals(status?: GoalStatus): Promise<Goal[]> {
  const { data } = await api.get<Goal[]>('/api/goals/', {
    params: status ? { status } : undefined,
  });
  return data;
}

/** `GET /api/goals/{goal_id}/tasks` */
export async function listTasks(goalId: string): Promise<Task[]> {
  const { data } = await api.get<Task[]>(`/api/goals/${goalId}/tasks`);
  return data;
}

/** `POST /api/goals/` — `CreateGoalRequest`: title, description, priority. */
export async function createGoal(input: {
  title: string;
  description?: string;
  priority?: number;
}): Promise<Goal> {
  const { data } = await api.post<Goal>('/api/goals/', {
    title: input.title,
    description: input.description ?? '',
    priority: input.priority ?? 50,
  });
  return data;
}

/** `PATCH /api/goals/{goal_id}/status` — `UpdateGoalStatusRequest`. */
export async function updateGoalStatus(goalId: string, status: GoalStatus): Promise<Goal> {
  const { data } = await api.patch<Goal>(`/api/goals/${goalId}/status`, { status });
  return data;
}

/**
 * `POST /api/goals/{goal_id}/execute`.
 *
 * Timeout próprio: a rota decompõe o goal e executa as tarefas em sequência,
 * dentro da requisição. Os 20s do cliente padrão cortariam isso na metade — e
 * cortar do lado do cliente não cancela nada do lado do servidor, só apaga a
 * resposta.
 *
 * A rota `GET /{goal_id}/stream` (SSE) existe e daria progresso ao vivo, mas o
 * `fetch` do RN não faz streaming de resposta (mesma limitação descrita em
 * `chat.ts`) e não há aqui um segundo canal como o WebSocket do chat. Fica de
 * fora conscientemente: a UI mostra o estado final e o `pull-to-refresh` cobre o
 * meio do caminho.
 */
export async function executeGoal(goalId: string): Promise<Goal> {
  const { data } = await api.post<Goal>(`/api/goals/${goalId}/execute`, undefined, {
    timeout: 600_000,
  });
  return data;
}
