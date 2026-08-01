/**
 * Uma mensagem do chat.
 *
 * ## Por que texto puro, e não markdown
 *
 * O PWA renderiza markdown com `react-markdown` + KaTeX. Aqui não: aquilo é um
 * grafo de elementos DOM, e o equivalente móvel seria somar um parser e um
 * renderizador de nós nativos ao bundle — para um ganho que, na largura de um
 * celular e com a fonte que o HUD usa, é pequeno. `**negrito**` legível é uma
 * troca aceitável; um app 300 kB maior e mais lento para rolar não é.
 *
 * O fundo é semitransparente de propósito: o brain fica **atrás** desta lista, e
 * uma bolha opaca o esconderia justamente na região onde a conversa acontece.
 */

import { memo } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { alpha, colors, fonts, radius, spacing } from '../theme/colors';
import type { ChatMessage } from '../store/useChatStore';

function formatTime(epochMs: number): string {
  const date = new Date(epochMs);
  const hh = String(date.getHours()).padStart(2, '0');
  const mm = String(date.getMinutes()).padStart(2, '0');
  return `${hh}:${mm}`;
}

export const MessageBubble = memo(function MessageBubble({
  message,
}: {
  message: ChatMessage;
}) {
  const isUser = message.role === 'user';
  const isSystem = message.role === 'system';
  const tools = message.tools ?? [];

  return (
    <View style={[styles.row, isUser ? styles.rowUser : styles.rowOther]}>
      <View
        style={[
          styles.bubble,
          isUser ? styles.bubbleUser : isSystem ? styles.bubbleSystem : styles.bubbleAssistant,
        ]}
      >
        {tools.length > 0 && (
          <View style={styles.toolRow}>
            {tools.map((tool, index) => (
              // Índice na chave: a mesma tool pode ser chamada duas vezes na
              // mesma resposta, e a lista só cresce no fim — nunca reordena.
              <View key={`${tool}-${index}`} style={styles.toolChip}>
                <Text style={styles.toolText} numberOfLines={1}>
                  {tool}
                </Text>
              </View>
            ))}
          </View>
        )}

        {message.content.length > 0 ? (
          <Text selectable style={[styles.text, isSystem && styles.textSystem]}>
            {message.content}
          </Text>
        ) : message.streaming ? (
          // Resposta aceita mas ainda sem um token sequer. Sem isto a bolha
          // apareceria vazia e pareceria travamento.
          <Text style={styles.thinking}>...</Text>
        ) : null}

        <Text style={styles.time}>
          {formatTime(message.createdAt)}
          {message.streaming ? '  ·  gerando' : ''}
        </Text>
      </View>
    </View>
  );
});

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    marginBottom: spacing.md,
  },
  rowUser: { justifyContent: 'flex-end' },
  rowOther: { justifyContent: 'flex-start' },

  bubble: {
    maxWidth: '86%',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.lg,
    borderWidth: 1,
  },
  bubbleUser: {
    backgroundColor: alpha.cyan(0.2),
    borderColor: colors.cyan,
    borderBottomRightRadius: radius.sm,
    shadowColor: colors.shadowDark,
    shadowOffset: { width: 3, height: 3 },
    shadowOpacity: 0.5,
    shadowRadius: 4,
    elevation: 3,
  },
  bubbleAssistant: {
    backgroundColor: colors.panel,
    borderColor: '#ffffff',
    borderBottomLeftRadius: radius.sm,
    shadowColor: colors.shadowDark,
    shadowOffset: { width: 3, height: 3 },
    shadowOpacity: 0.5,
    shadowRadius: 4,
    elevation: 3,
  },
  bubbleSystem: {
    backgroundColor: alpha.red(0.12),
    borderColor: alpha.red(0.35),
    borderBottomLeftRadius: radius.sm,
  },

  text: {
    color: colors.textPrimary,
    fontSize: 14,
    lineHeight: 21,
  },
  textSystem: {
    color: colors.red,
    fontFamily: fonts.mono,
    fontSize: 12,
  },
  thinking: {
    color: colors.textMuted,
    fontFamily: fonts.mono,
    fontSize: 16,
    letterSpacing: 3,
  },

  toolRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
    marginBottom: spacing.xs,
  },
  toolChip: {
    maxWidth: 180,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: radius.pill,
    backgroundColor: alpha.amber(0.12),
    borderWidth: 1,
    borderColor: alpha.amber(0.3),
  },
  toolText: {
    color: colors.amber,
    fontFamily: fonts.mono,
    fontSize: 10,
  },

  time: {
    marginTop: spacing.xs,
    color: colors.textMuted,
    fontFamily: fonts.mono,
    fontSize: 9,
    textAlign: 'right',
  },
});
