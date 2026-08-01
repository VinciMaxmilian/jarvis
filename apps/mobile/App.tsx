/**
 * Ponto de entrada: providers, gate de autenticação e navegação.
 *
 * ## O gate
 *
 * Login e abas não coexistem na pilha. Não é preferência estética: se a
 * `LoginScreen` continuasse montada atrás das abas, o WebView do Cloudflare
 * Access ficaria vivo e recarregando em segundo plano, e um "voltar" do Android
 * levaria de volta a uma tela de login já concluída. Trocar o conteúdo do
 * `Stack.Navigator` conforme o status **desmonta** o que não vale mais e faz a
 * transição ser a própria mudança de sessão.
 *
 * ## Por que o socket conecta aqui
 *
 * `useChatStore.connect()` é chamado neste nível, e não na `ChatScreen`, para
 * que a conexão sobreviva à troca de abas (ver o cabeçalho de `useChatStore`).
 * Aqui também é o único lugar que conhece a transição
 * autenticado → não autenticado, que é quando o socket precisa morrer antes de
 * tentar reconectar com credencial apagada.
 */

import { useEffect, useRef } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { NavigationContainer, DefaultTheme, type Theme } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { probeSession } from './src/api/client';
import type { RootStackParamList, TabParamList } from './src/navigation/types';
import BrainScreen from './src/screens/BrainScreen';
import ChatScreen from './src/screens/ChatScreen';
import GoalsScreen from './src/screens/GoalsScreen';
import HistoryScreen from './src/screens/HistoryScreen';
import LoginScreen from './src/screens/LoginScreen';
import SettingsScreen from './src/screens/SettingsScreen';
import { useAuthStore } from './src/store/useAuthStore';
import { useChatStore } from './src/store/useChatStore';
import { colors, fonts } from './src/theme/colors';

const Stack = createNativeStackNavigator<RootStackParamList>();
const Tab = createBottomTabNavigator<TabParamList>();

/**
 * Glifos geométricos em vez de uma biblioteca de ícones.
 *
 * `@expo/vector-icons` traria alguns megabytes de fontes para cinco símbolos. O
 * conjunto abaixo existe nas fontes de sistema do iOS e do Android e herda a cor
 * da aba automaticamente, que é tudo o que uma tab bar precisa.
 */
const TAB_GLYPH: Record<keyof TabParamList, string> = {
  Chat: '▣',
  Goals: '◎',
  Brain: '⬡',
  History: '≡',
  Settings: '⋯',
};

const navigationTheme: Theme = {
  ...DefaultTheme,
  colors: {
    ...DefaultTheme.colors,
    primary: colors.cyan,
    background: colors.bg,
    card: colors.surface,
    text: colors.textPrimary,
    border: colors.borderDim,
    notification: colors.amber,
  },
};

function Tabs() {
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        // Cada tela desenha o próprio cabeçalho (fundo translúcido, tipografia
        // de HUD); o header padrão duplicaria a barra e taparia o brain.
        headerShown: false,
        tabBarActiveTintColor: colors.cyan,
        tabBarInactiveTintColor: colors.textMuted,
        tabBarStyle: styles.tabBar,
        tabBarLabelStyle: styles.tabLabel,
        // No Android o teclado sobe por cima da tab bar; escondê-la devolve
        // altura à conversa enquanto se digita.
        tabBarHideOnKeyboard: true,
        tabBarIcon: ({ color }) => (
          <Text style={[styles.tabGlyph, { color }]}>{TAB_GLYPH[route.name]}</Text>
        ),
      })}
    >
      <Tab.Screen name="Chat" component={ChatScreen} options={{ title: 'Chat' }} />
      <Tab.Screen name="Goals" component={GoalsScreen} options={{ title: 'Metas' }} />
      <Tab.Screen name="Brain" component={BrainScreen} options={{ title: 'Brain' }} />
      <Tab.Screen name="History" component={HistoryScreen} options={{ title: 'Histórico' }} />
      <Tab.Screen name="Settings" component={SettingsScreen} options={{ title: 'Ajustes' }} />
    </Tab.Navigator>
  );
}

function Splash() {
  return (
    <View style={styles.splash}>
      <Text style={styles.splashBrand}>JARVIS</Text>
      <ActivityIndicator color={colors.cyan} />
    </View>
  );
}

export default function App() {
  const status = useAuthStore((state) => state.status);
  const restore = useAuthStore((state) => state.restore);
  const signOut = useAuthStore((state) => state.signOut);
  const connect = useChatStore((state) => state.connect);
  const disconnect = useChatStore((state) => state.disconnect);

  const probedRef = useRef(false);

  useEffect(() => {
    void restore();
  }, [restore]);

  // A sessão restaurada do SecureStore é uma hipótese: token pode ter sido
  // revogado, cookie do jar pode ter vencido. Uma requisição de verdade decide.
  // `denied` derruba; `unreachable` não — quem está sem rede não deve ser
  // deslogado por isso (ver `SessionProbe` em `api/client.ts`).
  useEffect(() => {
    if (status !== 'authenticated' || probedRef.current) return;
    probedRef.current = true;

    let alive = true;
    void probeSession().then((result) => {
      if (!alive) return;
      if (result === 'denied') {
        void signOut('Sua sessão do Cloudflare Access não vale mais.');
      }
    });
    return () => {
      alive = false;
    };
  }, [status, signOut]);

  useEffect(() => {
    if (status === 'authenticated') {
      connect();
      return;
    }
    disconnect();
  }, [status, connect, disconnect]);

  return (
    <SafeAreaProvider>
      <StatusBar style="dark" />
      <NavigationContainer theme={navigationTheme}>
        {status === 'restoring' ? (
          <Splash />
        ) : (
          <Stack.Navigator screenOptions={{ headerShown: false }}>
            {status === 'authenticated' ? (
              <Stack.Screen name="Tabs" component={Tabs} />
            ) : (
              <Stack.Screen name="Login" component={LoginScreen} />
            )}
          </Stack.Navigator>
        )}
      </NavigationContainer>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  splash: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 20,
    backgroundColor: colors.bg,
  },
  splashBrand: {
    color: colors.cyan,
    fontFamily: fonts.mono,
    fontSize: 18,
    letterSpacing: 6,
  },
  tabBar: {
    backgroundColor: colors.surface,
    borderTopColor: colors.borderDim,
  },
  tabLabel: {
    fontFamily: fonts.mono,
    fontSize: 9,
    letterSpacing: 0.5,
  },
  tabGlyph: {
    fontSize: 17,
    lineHeight: 20,
  },
});
