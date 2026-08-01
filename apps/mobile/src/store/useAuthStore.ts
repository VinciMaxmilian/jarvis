/**
 * Sessão do Cloudflare Access.
 *
 * ## Os dois jeitos de o app estar autenticado, e por que existem os dois
 *
 * O Access emite um JWT RS256 e o entrega no cookie `CF_Authorization`. Esse
 * cookie é **HttpOnly**: `document.cookie` dentro do WebView não o enxerga. Isso
 * elimina o caminho que o plano descrevia ("ler o cookie do WebView e guardar")
 * como *único* mecanismo — ele funciona só se a implantação afrouxar o HttpOnly,
 * e não dá para depender disso.
 *
 * Então há dois modos, nesta ordem de preferência:
 *
 * - **`token`** — o JWT em mãos, guardado no `SecureStore`. Só acontece quando o
 *   cookie é legível. Vale muito quando acontece: permite mandar
 *   `Cookie: CF_Authorization=…` e `Cf-Access-Jwt-Assertion: …` **explicitamente**
 *   em cada requisição, inclusive no WebSocket, sem depender de qual jar o
 *   sistema resolveu usar.
 * - **`cookieJar`** — não temos o JWT, mas o WebView do login o gravou no jar
 *   nativo que a camada de rede do app compartilha (`sharedCookiesEnabled` no
 *   iOS; `CookieManager` do WebView, que o OkHttp lê, no Android). As
 *   requisições saem sem header de auth e o cookie viaja sozinho.
 *
 * Nos dois casos a prova de que a sessão vale é a mesma: uma requisição de
 * verdade a uma rota protegida (`probeSession` em `src/api/client.ts`). Prazo de
 * validade lido do token é só um atalho para não tentar o que já se sabe morto.
 */

import * as SecureStore from 'expo-secure-store';
import { create } from 'zustand';

/** Nome exato do cookie do Access (`ACCESS_COOKIE` em `apps/api/cf_access.py`). */
export const ACCESS_COOKIE = 'CF_Authorization';

/** Header primário do Access (`ACCESS_HEADER` em `apps/api/cf_access.py`). */
export const ACCESS_HEADER = 'Cf-Access-Jwt-Assertion';

const TOKEN_KEY = 'jarvis.cf_authorization';
const MODE_KEY = 'jarvis.session_mode';

export type SessionMode = 'token' | 'cookieJar';
export type AuthStatus = 'restoring' | 'authenticated' | 'unauthenticated';

/**
 * Decodifica base64url sem depender de `atob`.
 *
 * O `atob` global do React Native existe desde a 0.74, mas (a) não aceita o
 * alfabeto base64**url** que o JWT usa e (b) tê-lo é detalhe de versão do
 * runtime. Trinta linhas aqui valem mais que um `if` sobre a versão da
 * plataforma, e isto roda uma vez por boot.
 */
function base64UrlDecode(input: string): string {
  const table = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  const normalized = input.replace(/-/g, '+').replace(/_/g, '/');
  let out = '';
  let buffer = 0;
  let bits = 0;

  for (const char of normalized) {
    if (char === '=') break;
    const value = table.indexOf(char);
    if (value === -1) continue;
    buffer = (buffer << 6) | value;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out += String.fromCharCode((buffer >> bits) & 0xff);
    }
  }
  return out;
}

/** `exp` do JWT em segundos epoch, ou `null` se o token for ilegível. */
export function jwtExpiry(token: string): number | null {
  const parts = token.split('.');
  if (parts.length !== 3) return null;
  try {
    const claims = JSON.parse(base64UrlDecode(parts[1])) as { exp?: unknown };
    return typeof claims.exp === 'number' ? claims.exp : null;
  } catch {
    return null;
  }
}

/**
 * Token vencido — ou tão perto de vencer que não vale tentar.
 *
 * Token ilegível conta como **não** vencido: quem decide se ele presta é a
 * origem, e recusar aqui um token que talvez funcione trocaria uma sessão viva
 * por uma tela de login.
 */
export function isTokenExpired(token: string, skewSeconds = 60): boolean {
  const exp = jwtExpiry(token);
  if (exp === null) return false;
  return Date.now() / 1000 >= exp - skewSeconds;
}

interface AuthState {
  status: AuthStatus;
  /** JWT do Access, quando foi possível capturá-lo. */
  token: string | null;
  mode: SessionMode | null;
  /** Motivo da última queda de sessão, para a `LoginScreen` explicar o retorno. */
  lastError: string | null;

  restore: () => Promise<void>;
  signIn: (args: { token: string | null }) => Promise<void>;
  signOut: (reason?: string) => Promise<void>;
  /** Headers de auth a anexar; vazio no modo `cookieJar`. */
  authHeaders: () => Record<string, string>;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  status: 'restoring',
  token: null,
  mode: null,
  lastError: null,

  restore: async () => {
    try {
      const [token, mode] = await Promise.all([
        SecureStore.getItemAsync(TOKEN_KEY),
        SecureStore.getItemAsync(MODE_KEY),
      ]);

      if (token && !isTokenExpired(token)) {
        set({ status: 'authenticated', token, mode: 'token', lastError: null });
        return;
      }
      if (token) {
        // Vencido: apagar agora evita reapresentá-lo a cada boot.
        await SecureStore.deleteItemAsync(TOKEN_KEY);
      }
      if (mode === 'cookieJar') {
        // Sem token para inspecionar. Otimismo deliberado: quem confirma é o
        // `probeSession` no boot, que já derruba para `unauthenticated` se o
        // cookie do jar não valer mais.
        set({ status: 'authenticated', token: null, mode: 'cookieJar', lastError: null });
        return;
      }
      set({ status: 'unauthenticated', token: null, mode: null });
    } catch {
      // Keychain/Keystore indisponível é indistinguível de "nunca logou" do
      // ponto de vista de quem usa: os dois levam à tela de login.
      set({ status: 'unauthenticated', token: null, mode: null });
    }
  },

  signIn: async ({ token }) => {
    const mode: SessionMode = token ? 'token' : 'cookieJar';
    try {
      if (token) {
        await SecureStore.setItemAsync(TOKEN_KEY, token);
      } else {
        await SecureStore.deleteItemAsync(TOKEN_KEY);
      }
      await SecureStore.setItemAsync(MODE_KEY, mode);
    } catch {
      // Falhar em persistir não anula o login: a sessão desta execução continua
      // válida, só não sobrevive ao fechamento do app.
    }
    set({ status: 'authenticated', token, mode, lastError: null });
  },

  signOut: async (reason?: string) => {
    try {
      await Promise.all([
        SecureStore.deleteItemAsync(TOKEN_KEY),
        SecureStore.deleteItemAsync(MODE_KEY),
      ]);
    } catch {
      // Idem: o estado em memória é o que governa a navegação.
    }
    set({ status: 'unauthenticated', token: null, mode: null, lastError: reason ?? null });
  },

  // Retorno anotado: sem a anotação o TypeScript infere a união dos dois
  // `return` (`{}` vira `{ Cookie?: undefined; … }`), que não satisfaz
  // `Record<string, string>` mesmo estando correta em runtime.
  authHeaders: (): Record<string, string> => {
    const { token } = get();
    if (!token) return {};
    // Os dois de uma vez, e não um ou outro. O header é o que a ORIGEM verifica
    // (`apps/api/cf_access.py` o trata como fonte primária); o cookie é o que a
    // BORDA do Access exige para deixar a requisição passar. Mandar só um faz a
    // requisição morrer em um dos dois pontos.
    return {
      [ACCESS_HEADER]: token,
      Cookie: `${ACCESS_COOKIE}=${token}`,
    };
  },
}));
