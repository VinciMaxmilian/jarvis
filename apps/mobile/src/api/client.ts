/**
 * Instância única de axios contra a origem do Jarvis.
 *
 * Duas coisas moram aqui e em nenhum outro lugar: injeção da credencial do
 * Cloudflare Access e a reação a `401`. Espalhar qualquer uma das duas por tela
 * garante que a próxima tela esqueça uma delas.
 */

import axios, { AxiosError, type AxiosInstance } from 'axios';

import { API_BASE_URL } from '../config';
import { useAuthStore } from '../store/useAuthStore';

export const api: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  // 20s cobre com folga qualquer rota REST daqui. O chat NÃO passa por este
  // cliente (é WebSocket), então não há geração de LLM esperando neste prazo —
  // se alguém um dia apontar o fallback HTTP para cá, precisa de timeout próprio.
  timeout: 20_000,
  // O Access devolve 401 com corpo JSON; deixar o axios lançar mantém o
  // tratamento num lugar só, no interceptor de resposta abaixo.
  headers: { Accept: 'application/json' },
  // Necessário para o modo `cookieJar`: sem isto o axios/XHR do RN não anexa o
  // cookie do jar nativo em requisição cross-origin.
  withCredentials: true,
});

api.interceptors.request.use((config) => {
  const headers = useAuthStore.getState().authHeaders();
  for (const [key, value] of Object.entries(headers)) {
    config.headers.set(key, value);
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      // Uma sessão do Access que expirou não se anuncia: ela simplesmente vira
      // 401 na próxima requisição, de qualquer tela. Derrubar aqui é o que faz o
      // app voltar ao login em vez de exibir listas vazias para sempre.
      void useAuthStore.getState().signOut('Sessão do Cloudflare Access expirou.');
    }
    return Promise.reject(error);
  },
);

/**
 * Resultado de sondar a sessão.
 *
 * São **três** estados, e não um booleano, porque os dois jeitos de "não" pedem
 * reações opostas: `denied` é sessão morta e manda para o login; `unreachable` é
 * rede fora, e mandar para o login quem está no elevador seria trocar uma sessão
 * boa por uma tela de senha que ele também não conseguiria concluir.
 */
export type SessionProbe = 'ok' | 'denied' | 'unreachable';

/**
 * A sessão vale? Descobre do único jeito que conta: usando-a.
 *
 * Escolha da rota: `GET /api/tools/`. É a mais barata do backend protegido —
 * lê o registro de tools em memória, não toca Postgres nem LLM
 * (`apps/api/routers/tools.py`) — e ainda assim está atrás do middleware do
 * Access. `/health` não serviria: é a única rota pública (`PUBLIC_PATHS` em
 * `apps/api/cf_access.py`) e responde 200 para quem não está autenticado, ou
 * seja, responderia sempre "sim".
 *
 * Não usa a instância `api` acima porque o interceptor de 401 dela chamaria
 * `signOut` — e aqui um 401 é uma resposta esperada, não um evento de sessão
 * perdida (durante o login ainda não há sessão para perder).
 */
export async function probeSession(): Promise<SessionProbe> {
  let response;
  try {
    response = await axios.get(`${API_BASE_URL}/api/tools/`, {
      timeout: 12_000,
      headers: { Accept: 'application/json', ...useAuthStore.getState().authHeaders() },
      withCredentials: true,
      validateStatus: () => true,
    });
  } catch {
    return 'unreachable';
  }
  if (response.status === 200) return 'ok';
  // 401/403 é o Access negando. 5xx é a origem doente com a sessão possivelmente
  // boa — tratar como `unreachable` evita deslogar por causa de um deploy ruim.
  return response.status >= 500 ? 'unreachable' : 'denied';
}

/** Mensagem curta e legível a partir de um erro do axios. */
export function describeError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const status = error.response?.status;
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === 'string') return status ? `${status}: ${detail}` : detail;
    if (status) return `HTTP ${status}`;
    return error.message || 'Falha de rede';
  }
  return error instanceof Error ? error.message : 'Erro desconhecido';
}
