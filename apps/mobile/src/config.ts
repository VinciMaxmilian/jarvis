/**
 * De onde sai a URL da origem, e por que em três camadas.
 *
 * O app fala com UMA origem: o hostname público do túnel Cloudflare, que serve o
 * PWA e faz proxy de `/api/` para o FastAPI (ver `apps/web/nginx.conf`). Esse
 * valor precisa ser trocável em três situações diferentes, e cada uma tem um
 * mecanismo próprio:
 *
 * 1. `EXPO_PUBLIC_API_BASE_URL` no ambiente — para apontar o Metro para um
 *    backend local (`http://192.168.x.x:8000`) sem editar arquivo versionado.
 *    Só variáveis com o prefixo `EXPO_PUBLIC_` são embutidas no bundle.
 * 2. `expo.extra.apiBaseUrl` no `app.json` — o valor que vai no build.
 * 3. A constante abaixo — último recurso, para que um bundle sem configuração
 *    nenhuma ainda aponte para o lugar certo em vez de falhar em runtime.
 *
 * A ordem é deliberada: o mais específico (ambiente da máquina) ganha do mais
 * geral (constante compilada).
 */

import Constants from 'expo-constants';

/** Origem pública decidida para o Jarvis. */
const DEFAULT_BASE_URL = 'https://ia.atmosintelli.com.br';

function readExtra(key: string): string | undefined {
  // `expoConfig` é o campo atual; `manifest2`/`manifest` eram os antigos. Ler só
  // o atual basta no SDK 57, mas o cast evita depender do shape exato do extra.
  const extra = Constants.expoConfig?.extra as Record<string, unknown> | undefined;
  const value = extra?.[key];
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

function normalize(url: string): string {
  // Barra no fim duplicaria a barra dos paths (`//api/chat/`), o que o nginx
  // trata como caminho diferente e devolve 404 em vez de fazer proxy.
  return url.replace(/\/+$/, '');
}

/** `https://host` — sem barra final. */
export const API_BASE_URL: string = normalize(
  process.env.EXPO_PUBLIC_API_BASE_URL?.trim() || readExtra('apiBaseUrl') || DEFAULT_BASE_URL,
);

/**
 * A mesma origem em `ws://` / `wss://`, para `/api/chat/ws`.
 *
 * Derivada, e não configurada à parte: hostname de WebSocket separado seria uma
 * segunda coisa para manter em sincronia, e o dia em que as duas divergissem o
 * chat autenticaria no HTTP e tomaria 401 no socket — falha que não se parece
 * com sua causa.
 */
export const WS_BASE_URL: string = API_BASE_URL.replace(/^http/, 'ws');

/** URL que a `LoginScreen` abre no WebView para o fluxo do Cloudflare Access. */
export const LOGIN_URL: string = API_BASE_URL;
