/**
 * A conversa, com o cérebro atrás dela.
 *
 * ## O arranjo em camadas
 *
 * O brain é um WebView que ocupa a tela inteira, **abaixo** da conversa e com
 * `pointerEvents: 'none'` (ver `BrainCanvas`). A lista e a barra de digitação
 * flutuam por cima com fundos semitransparentes. Nenhum toque chega ao cérebro
 * nesta aba de propósito: aqui ele é cenário, e um arrasto para rolar a conversa
 * não pode virar rotação de câmera. Quem quiser manipulá-lo vai à aba BRAIN.
 *
 * ## Quem manda no socket
 *
 * Não é esta tela. `useChatStore.connect()` é chamado uma vez no `App.tsx`,
 * quando a sessão passa a valer. Esta tela só lê estado e chama `send`. É o que
 * permite trocar de aba no meio de uma geração e voltar com o texto já escrito.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useBottomTabBarHeight } from '@react-navigation/bottom-tabs';
import { SafeAreaView } from 'react-native-safe-area-context';

import { BrainCanvas } from '../components/Brain/BrainCanvas';
import { InputBar } from '../components/InputBar';
import { MessageBubble } from '../components/MessageBubble';
import type { TabParamList } from '../navigation/types';
import { useChatStore, type ChatMessage } from '../store/useChatStore';
import { alpha, colors, fonts, radius, spacing } from '../theme/colors';
import type { BottomTabScreenProps } from '@react-navigation/bottom-tabs';

type Props = BottomTabScreenProps<TabParamList, 'Chat'>;

export default function ChatScreen({ route, navigation }: Props) {
  const messages = useChatStore((state) => state.messages);
  const connected = useChatStore((state) => state.connected);
  const streaming = useChatStore((state) => state.streaming);
  const transport = useChatStore((state) => state.transport);
  const loadingHistory = useChatStore((state) => state.loadingHistory);
  const activation = useChatStore((state) => state.activation);
  const resetSeq = useChatStore((state) => state.resetSeq);
  const send = useChatStore((state) => state.send);
  const startNewConversation = useChatStore((state) => state.startNewConversation);
  const loadConversation = useChatStore((state) => state.loadConversation);

  const [draft, setDraft] = useState('');
  const [brainError, setBrainError] = useState<string | null>(null);
  const listRef = useRef<FlatList<ChatMessage>>(null);
  const tabBarHeight = useBottomTabBarHeight();

  // O Histórico navega para cá com um id. Consumir o parâmetro (zerá-lo depois
  // de usar) evita que voltar à aba recarregue a mesma conversa por cima do que
  // já foi digitado.
  const requestedId = route.params?.conversationId;
  useEffect(() => {
    if (!requestedId) return;
    void loadConversation(requestedId);
    navigation.setParams({ conversationId: undefined });
  }, [requestedId, loadConversation, navigation]);

  const handleSend = useCallback(() => {
    const text = draft.trim();
    if (!text) return;
    setDraft('');
    void send(text);
  }, [draft, send]);

  const scrollToEnd = useCallback(() => {
    listRef.current?.scrollToEnd({ animated: true });
  }, []);

  const renderItem = useCallback(
    ({ item }: { item: ChatMessage }) => <MessageBubble message={item} />,
    [],
  );

  return (
    <View style={styles.root}>
      <BrainCanvas
        mode="chat"
        activation={activation}
        resetSeq={resetSeq}
        style={styles.brain}
        onGraphError={setBrainError}
      />

      <SafeAreaView style={styles.fill} edges={['top']}>
        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <Text style={styles.brand}>COMMS</Text>
            <View style={[styles.led, { backgroundColor: connected ? colors.green : colors.red }]} />
            <Text style={[styles.status, { color: connected ? colors.green : colors.red }]}>
              {connected ? 'LINKED' : transport === 'http' ? 'HTTP' : 'OFFLINE'}
            </Text>
          </View>

          <Pressable
            onPress={startNewConversation}
            style={({ pressed }) => [styles.newButton, pressed && styles.newButtonPressed]}
            accessibilityRole="button"
            accessibilityLabel="Nova conversa"
          >
            <Text style={styles.newButtonText}>NOVA</Text>
          </Pressable>
        </View>

        {transport === 'http' && (
          <Text style={styles.notice}>
            Socket indisponível: resposta chega inteira, sem streaming e sem brain.
          </Text>
        )}
        {brainError && <Text style={styles.notice}>Brain sem grafo: {brainError}</Text>}

        <KeyboardAvoidingView
          style={styles.fill}
          // `padding` só no iOS: no Android o `adjustResize` do sistema já
          // encolhe a janela, e somar os dois deixa um vão do tamanho do teclado.
          behavior={Platform.OS === 'ios' ? 'padding' : undefined}
          keyboardVerticalOffset={tabBarHeight}
        >
          <FlatList
            ref={listRef}
            data={messages}
            renderItem={renderItem}
            keyExtractor={(item) => item.id}
            contentContainerStyle={styles.listContent}
            onContentSizeChange={scrollToEnd}
            keyboardDismissMode="interactive"
            keyboardShouldPersistTaps="handled"
            ListEmptyComponent={
              <View style={styles.empty}>
                <Text style={styles.emptyTitle}>JARVIS ONLINE</Text>
                <Text style={styles.emptyText}>
                  {loadingHistory
                    ? 'Carregando conversa...'
                    : 'O cérebro está cinza. Ele vai colorindo conforme as tools tocam o código.'}
                </Text>
              </View>
            }
          />

          <InputBar
            value={draft}
            onChangeText={setDraft}
            onSend={handleSend}
            // Sem socket ainda dá para enviar: cai no fallback HTTP. O que
            // bloqueia é uma geração em curso.
            enabled={!streaming}
            busy={streaming}
            disabledHint="Gerando resposta..."
          />
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  fill: { flex: 1 },
  brain: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
  },

  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.borderDim,
    backgroundColor: alpha.surface(0.72),
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  brand: {
    color: colors.cyan,
    fontFamily: fonts.mono,
    fontSize: 12,
    letterSpacing: 2,
  },
  led: { width: 7, height: 7, borderRadius: radius.pill },
  status: { fontFamily: fonts.mono, fontSize: 10 },

  newButton: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.borderDim,
    backgroundColor: alpha.panel(0.8),
  },
  newButtonPressed: { opacity: 0.6 },
  newButtonText: {
    color: colors.textSecondary,
    fontFamily: fonts.mono,
    fontSize: 10,
    letterSpacing: 1,
  },

  notice: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.xs,
    color: colors.amber,
    fontFamily: fonts.mono,
    fontSize: 10,
    backgroundColor: alpha.amber(0.08),
  },

  listContent: {
    flexGrow: 1,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg,
    paddingBottom: spacing.sm,
  },
  empty: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    paddingHorizontal: spacing.xxl,
  },
  emptyTitle: {
    color: colors.cyan,
    fontFamily: fonts.mono,
    fontSize: 13,
    letterSpacing: 3,
  },
  emptyText: {
    color: colors.textMuted,
    fontSize: 12,
    lineHeight: 18,
    textAlign: 'center',
  },
});
