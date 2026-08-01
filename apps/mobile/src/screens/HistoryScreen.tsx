/**
 * Conversas passadas e o consumo que elas geraram.
 *
 * As duas coisas vivem na mesma tela porque respondem à mesma pergunta ("o que
 * eu já pedi a este sistema?") e vêm do mesmo router (`history.py`). Ficam em
 * requisições separadas, e uma falhando não apaga a outra: `/stats` faz
 * agregação sobre a tabela de mensagens e é a que tem chance real de demorar ou
 * falhar — não pode levar a lista de conversas junto.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import type { BottomTabScreenProps } from '@react-navigation/bottom-tabs';

import { describeError } from '../api/client';
import { getStats, listChats, type ChatPreview, type StatsResponse } from '../api/history';
import type { TabParamList } from '../navigation/types';
import { alpha, colors, fonts, radius, spacing } from '../theme/colors';

type Props = BottomTabScreenProps<TabParamList, 'History'>;

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return `${date.toLocaleDateString()} ${String(date.getHours()).padStart(2, '0')}:${String(
    date.getMinutes(),
  ).padStart(2, '0')}`;
}

function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export default function HistoryScreen({ navigation }: Props) {
  const [chats, setChats] = useState<ChatPreview[]>([]);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    // `allSettled` e não `all`: um `/stats` lento ou quebrado não pode esconder
    // a lista de conversas, que é o assunto principal da tela.
    const [chatsResult, statsResult] = await Promise.allSettled([listChats(), getStats()]);

    if (chatsResult.status === 'fulfilled') {
      setChats(chatsResult.value);
    } else {
      setError(describeError(chatsResult.reason));
    }
    setStats(statsResult.status === 'fulfilled' ? statsResult.value : null);
  }, []);

  useEffect(() => {
    void load().finally(() => setLoading(false));
  }, [load]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    void load().finally(() => setRefreshing(false));
  }, [load]);

  const openChat = useCallback(
    (conversationId: string) => {
      navigation.navigate('Chat', { conversationId });
    },
    [navigation],
  );

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.brand}>ARQUIVO</Text>
        <Text style={styles.count}>{chats.length} conversas</Text>
      </View>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.cyan} />
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.content}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={onRefresh}
              tintColor={colors.cyan}
              colors={[colors.cyan]}
            />
          }
        >
          {error && <Text style={styles.error}>{error}</Text>}

          {stats && (stats.models.length > 0 || stats.tools.length > 0) && (
            <View style={styles.statsCard}>
              <Text style={styles.sectionTitle}>CONSUMO</Text>
              {stats.models.map((model) => (
                <View key={model.model} style={styles.statRow}>
                  <Text style={styles.statName} numberOfLines={1}>
                    {model.model}
                  </Text>
                  <Text style={styles.statValue}>
                    {compact(model.input_tokens)} in · {compact(model.output_tokens)} out
                  </Text>
                </View>
              ))}
              {stats.tools.length > 0 && (
                <View style={styles.toolRow}>
                  {stats.tools.slice(0, 8).map((tool) => (
                    <View key={tool.tool} style={styles.toolChip}>
                      <Text style={styles.toolText} numberOfLines={1}>
                        {tool.tool} {tool.count}
                      </Text>
                    </View>
                  ))}
                </View>
              )}
            </View>
          )}

          {chats.length === 0 && !error ? (
            <Text style={styles.empty}>Nenhuma conversa registrada ainda.</Text>
          ) : (
            chats.map((chat) => (
              <Pressable
                key={chat.id}
                onPress={() => openChat(chat.id)}
                style={({ pressed }) => [styles.chatCard, pressed && styles.chatCardPressed]}
                accessibilityRole="button"
              >
                <Text style={styles.chatTitle} numberOfLines={1}>
                  {chat.title}
                </Text>
                <Text style={styles.chatPreview} numberOfLines={2}>
                  {chat.preview_text}
                </Text>
                <Text style={styles.chatMeta}>
                  {formatDate(chat.updated_at)} · {chat.message_count} msgs
                </Text>
              </Pressable>
            ))
          )}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  header: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.borderDim,
  },
  brand: {
    color: colors.cyan,
    fontFamily: fonts.mono,
    fontSize: 12,
    letterSpacing: 2,
  },
  count: {
    color: colors.textMuted,
    fontFamily: fonts.mono,
    fontSize: 10,
  },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  content: {
    padding: spacing.lg,
    paddingBottom: spacing.xxl,
  },
  error: {
    marginBottom: spacing.md,
    color: colors.red,
    fontFamily: fonts.mono,
    fontSize: 11,
  },
  empty: {
    marginTop: spacing.xxl,
    color: colors.textMuted,
    fontFamily: fonts.mono,
    fontSize: 11,
    textAlign: 'center',
  },

  statsCard: {
    padding: spacing.md,
    marginBottom: spacing.lg,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.borderDim,
    backgroundColor: colors.panel,
    gap: spacing.xs,
  },
  sectionTitle: {
    color: colors.textSecondary,
    fontFamily: fonts.mono,
    fontSize: 10,
    letterSpacing: 2,
    marginBottom: spacing.xs,
  },
  statRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: spacing.sm,
  },
  statName: {
    flex: 1,
    color: colors.textPrimary,
    fontFamily: fonts.mono,
    fontSize: 11,
  },
  statValue: {
    color: colors.textMuted,
    fontFamily: fonts.mono,
    fontSize: 10,
  },
  toolRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
    marginTop: spacing.sm,
  },
  toolChip: {
    maxWidth: 160,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: radius.pill,
    backgroundColor: alpha.cyan(0.1),
    borderWidth: 1,
    borderColor: alpha.cyan(0.25),
  },
  toolText: {
    color: colors.cyan,
    fontFamily: fonts.mono,
    fontSize: 9,
  },

  chatCard: {
    padding: spacing.md,
    marginBottom: spacing.md,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.borderDim,
    backgroundColor: colors.panel,
  },
  chatCardPressed: { backgroundColor: colors.elevated },
  chatTitle: {
    color: colors.textPrimary,
    fontSize: 14,
    fontWeight: '600',
  },
  chatPreview: {
    marginTop: 2,
    color: colors.textSecondary,
    fontSize: 12,
    lineHeight: 17,
  },
  chatMeta: {
    marginTop: spacing.sm,
    color: colors.textMuted,
    fontFamily: fonts.mono,
    fontSize: 9,
  },
});
