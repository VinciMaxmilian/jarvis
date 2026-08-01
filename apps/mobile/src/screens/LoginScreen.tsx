/**
 * Login no Cloudflare Access, dentro de um WebView.
 *
 * ## O que o plano dizia e o que a plataforma permite
 *
 * O plano (§3) descreve: abrir o WebView, interceptar o cookie `CF_Authorization`
 * em `onNavigationStateChange`, guardar e seguir. A primeira metade vale; a
 * segunda depende de uma condição que normalmente é falsa — o cookie do Access é
 * **HttpOnly**, e `document.cookie` não o enxerga. Um app que só saiba esse
 * caminho fica preso na tela de login mesmo com o login concluído.
 *
 * Então a tela tem dois caminhos e prefere o primeiro:
 *
 * 1. **Capturar o JWT.** Um script injetado a cada navegação tenta ler o cookie.
 *    Quando dá certo (implantação sem HttpOnly), o token vai para o SecureStore e
 *    todas as requisições passam a mandar credencial explícita — inclusive o
 *    WebSocket, que é onde o cookie implícito costuma falhar.
 * 2. **Confiar no jar nativo.** Não deu para ler? Com `sharedCookiesEnabled` o
 *    cookie que o WebView gravou é o mesmo que a camada de rede do app usa. A
 *    prova é empírica: `probeSession()` bate numa rota protegida. Se ela responde
 *    200, a sessão existe — não importa que ninguém tenha visto o token.
 *
 * `onNavigationStateChange` é o gatilho dos dois: quando a navegação volta para a
 * origem do Jarvis (saiu do IdP, saiu de `/cdn-cgi/access/`), o login terminou.
 *
 * O botão "Já entrei" existe porque nem todo fluxo termina em navegação
 * observável — alguns IdPs fecham em `history.replaceState`, que não gera
 * evento. Um toque manual custa menos que ficar preso.
 */

import { useCallback, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { WebView } from 'react-native-webview';
import type {
  WebViewMessageEvent,
  WebViewNavigation,
} from 'react-native-webview/lib/WebViewTypes';

import { probeSession } from '../api/client';
import { LOGIN_URL } from '../config';
import { ACCESS_COOKIE, useAuthStore } from '../store/useAuthStore';
import { alpha, colors, fonts, radius, spacing } from '../theme/colors';

/**
 * Roda ao fim de cada navegação. Sem barra invertida em lugar nenhum: o script
 * vive dentro de um template literal do TypeScript, e cada escape aqui viraria
 * duas camadas para conferir. `'; '` é o separador exato que os navegadores usam
 * em `document.cookie`.
 */
const COOKIE_SNIFFER = `
(function () {
  try {
    var parts = String(document.cookie || '').split('; ');
    var token = null;
    for (var i = 0; i < parts.length; i++) {
      if (parts[i].indexOf('${ACCESS_COOKIE}=') === 0) {
        token = parts[i].slice('${ACCESS_COOKIE}='.length);
        break;
      }
    }
    window.ReactNativeWebView.postMessage(JSON.stringify({
      type: 'cookie',
      token: token,
      url: String(location.href)
    }));
  } catch (e) {}
})();
true;
`;

/** Host de uma URL sem depender do `URL` do runtime, que no RN é parcial. */
function hostOf(url: string): string {
  const match = /^[a-z][a-z0-9+.-]*:\/\/([^/?#]+)/i.exec(url);
  return match ? match[1].toLowerCase() : '';
}

const APP_HOST = hostOf(LOGIN_URL);

/** Estamos de volta na origem do Jarvis, fora do fluxo do Access? */
function isBackAtApp(url: string): boolean {
  if (hostOf(url) !== APP_HOST) return false;
  // `/cdn-cgi/access/...` é o próprio Access rodando na nossa origem: mesmo host,
  // login ainda em andamento.
  return !url.includes('/cdn-cgi/access/');
}

export default function LoginScreen() {
  const signIn = useAuthStore((state) => state.signIn);
  const lastError = useAuthStore((state) => state.lastError);

  const [checking, setChecking] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  /** Token visto pelo sniffer, se algum. */
  const tokenRef = useRef<string | null>(null);
  /** Uma verificação por vez — a navegação dispara em rajada. */
  const checkingRef = useRef(false);

  const finish = useCallback(
    async (manual: boolean) => {
      if (checkingRef.current) return;
      checkingRef.current = true;
      setChecking(true);
      setNote(null);

      try {
        const probe = await probeSession();
        if (probe === 'ok') {
          await signIn({ token: tokenRef.current });
          return;
        }
        if (probe === 'unreachable') {
          setNote('Não consegui falar com o servidor. Verifique a rede e tente de novo.');
          return;
        }
        // `denied` durante a navegação automática é o caso normal (a página de
        // login carregou); só vale avisar quando o usuário pediu explicitamente.
        if (manual) {
          setNote('Ainda não autenticado. Conclua o login na página acima.');
        }
      } finally {
        checkingRef.current = false;
        setChecking(false);
      }
    },
    [signIn],
  );

  const handleNavigation = useCallback(
    (nav: WebViewNavigation) => {
      if (nav.loading) return;
      if (!isBackAtApp(nav.url)) return;
      void finish(false);
    },
    [finish],
  );

  const handleMessage = useCallback(
    (event: WebViewMessageEvent) => {
      let payload: { type?: string; token?: unknown; url?: unknown };
      try {
        payload = JSON.parse(event.nativeEvent.data) as typeof payload;
      } catch {
        return;
      }
      if (payload.type !== 'cookie') return;

      if (typeof payload.token === 'string' && payload.token.length > 0) {
        tokenRef.current = payload.token;
        // Token em mãos é o modo bom: não espera navegação nenhuma, valida e
        // entra.
        void finish(false);
      }
    },
    [finish],
  );

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'bottom']}>
      <View style={styles.header}>
        <Text style={styles.brand}>JARVIS</Text>
        <Text style={styles.host} numberOfLines={1}>
          {APP_HOST}
        </Text>
      </View>

      {(lastError || note) && (
        <View style={styles.banner}>
          <Text style={styles.bannerText}>{note ?? lastError}</Text>
        </View>
      )}

      <View style={styles.webWrap}>
        <WebView
          // Trocar a chave remonta o WebView — é o "recarregar" que também
          // descarta estado de página quebrada, coisa que `reload()` não faz.
          key={reloadKey}
          source={{ uri: LOGIN_URL }}
          onNavigationStateChange={handleNavigation}
          onMessage={handleMessage}
          injectedJavaScript={COOKIE_SNIFFER}
          // O ponto do fluxo inteiro: o cookie gravado aqui é o mesmo que o
          // axios e o WebSocket usarão depois.
          sharedCookiesEnabled
          thirdPartyCookiesEnabled
          // `incognito` apagaria o cookie ao desmontar — exatamente o que se quer
          // guardar. Explícito para que ninguém o ligue "por segurança".
          incognito={false}
          domStorageEnabled
          javaScriptEnabled
          startInLoadingState
          renderLoading={() => (
            <View style={styles.loading}>
              <ActivityIndicator color={colors.cyan} />
            </View>
          )}
          style={styles.web}
        />
      </View>

      <View style={styles.actions}>
        <Pressable
          style={({ pressed }) => [styles.action, pressed && styles.actionPressed]}
          onPress={() => setReloadKey((key) => key + 1)}
          accessibilityRole="button"
        >
          <Text style={styles.actionText}>RECARREGAR</Text>
        </Pressable>

        <Pressable
          style={({ pressed }) => [
            styles.action,
            styles.actionPrimary,
            pressed && styles.actionPressed,
          ]}
          onPress={() => void finish(true)}
          disabled={checking}
          accessibilityRole="button"
        >
          {checking ? (
            <ActivityIndicator size="small" color={colors.cyan} />
          ) : (
            <Text style={[styles.actionText, styles.actionTextPrimary]}>JÁ ENTREI</Text>
          )}
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  header: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    gap: spacing.md,
  },
  brand: {
    color: colors.cyan,
    fontFamily: fonts.mono,
    fontSize: 16,
    letterSpacing: 4,
  },
  host: {
    flexShrink: 1,
    color: colors.textMuted,
    fontFamily: fonts.mono,
    fontSize: 10,
  },
  banner: {
    marginHorizontal: spacing.lg,
    marginBottom: spacing.sm,
    padding: spacing.sm,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: alpha.amber(0.35),
    backgroundColor: alpha.amber(0.1),
  },
  bannerText: {
    color: colors.amber,
    fontSize: 12,
    lineHeight: 17,
  },
  webWrap: {
    flex: 1,
    marginHorizontal: spacing.sm,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.borderDim,
    overflow: 'hidden',
  },
  web: { flex: 1, backgroundColor: colors.surface },
  loading: {
    // `absoluteFillObject` existe em runtime mas saiu das tipagens da RN 0.86;
    // `absoluteFill` é o mesmo objeto e continua declarado.
    ...StyleSheet.absoluteFill,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.bg,
  },
  actions: {
    flexDirection: 'row',
    gap: spacing.sm,
    padding: spacing.md,
  },
  action: {
    flex: 1,
    height: 44,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.borderDim,
    backgroundColor: colors.panel,
  },
  actionPrimary: {
    borderColor: alpha.cyan(0.35),
    backgroundColor: alpha.cyan(0.14),
  },
  actionPressed: { opacity: 0.7 },
  actionText: {
    color: colors.textSecondary,
    fontFamily: fonts.mono,
    fontSize: 11,
    letterSpacing: 1,
  },
  actionTextPrimary: { color: colors.cyan },
});
