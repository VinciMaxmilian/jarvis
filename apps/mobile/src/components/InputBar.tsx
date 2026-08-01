/**
 * Barra de digitação do chat.
 *
 * Controlada por fora (`value`/`onChangeText`) e não por estado interno: quem
 * decide se a mensagem pode sair é a tela, que sabe do socket e do streaming.
 * Um estado próprio aqui duplicaria a fonte da verdade e criaria o caso em que a
 * barra mostra um texto que a tela já enviou.
 *
 * `multiline` com altura limitada: mensagem de várias linhas é comum, mas deixar
 * o campo crescer sem teto empurraria a conversa para fora da tela num teclado
 * de celular.
 */

import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { alpha, colors, fonts, radius, spacing } from '../theme/colors';

export interface InputBarProps {
  value: string;
  onChangeText: (text: string) => void;
  onSend: () => void;
  /** `false` desabilita o envio e troca o placeholder pela explicação. */
  enabled: boolean;
  busy: boolean;
  placeholder?: string;
  disabledHint?: string;
}

export function InputBar({
  value,
  onChangeText,
  onSend,
  enabled,
  busy,
  placeholder = 'Mensagem para o Jarvis...',
  disabledHint = 'Reconectando...',
}: InputBarProps) {
  const canSend = enabled && !busy && value.trim().length > 0;

  return (
    <View style={styles.container}>
      <TextInput
        style={styles.input}
        value={value}
        onChangeText={onChangeText}
        placeholder={enabled ? placeholder : disabledHint}
        placeholderTextColor={colors.textMuted}
        editable={enabled && !busy}
        multiline
        // `default` e não `send`: com `multiline` o Enter é quebra de linha, e
        // rotular a tecla de "enviar" prometeria um comportamento que não existe.
        returnKeyType="default"
        keyboardAppearance="dark"
        selectionColor={colors.cyan}
        maxLength={8000}
      />

      <Pressable
        onPress={onSend}
        disabled={!canSend}
        style={({ pressed }) => [
          styles.button,
          !canSend && styles.buttonDisabled,
          pressed && canSend && styles.buttonPressed,
        ]}
        // Alvo de toque mínimo confortável, independente do tamanho pintado.
        hitSlop={6}
        accessibilityRole="button"
        accessibilityLabel="Enviar mensagem"
      >
        {busy ? (
          <ActivityIndicator size="small" color={colors.cyan} />
        ) : (
          <Text style={[styles.buttonText, !canSend && styles.buttonTextDisabled]}>ENVIAR</Text>
        )}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: spacing.sm,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    paddingBottom: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.borderDim,
    backgroundColor: colors.surface,
  },
  input: {
    flex: 1,
    minHeight: 42,
    maxHeight: 132,
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
    paddingBottom: spacing.sm,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: '#ffffff',
    backgroundColor: colors.panel,
    color: colors.textPrimary,
    fontSize: 14,
    shadowColor: colors.shadowDark,
    shadowOffset: { width: 2, height: 2 },
    shadowOpacity: 0.4,
    shadowRadius: 4,
    elevation: 2,
  },
  button: {
    minWidth: 78,
    height: 42,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.cyan,
    backgroundColor: alpha.cyan(0.1),
    shadowColor: colors.shadowDark,
    shadowOffset: { width: 2, height: 2 },
    shadowOpacity: 0.4,
    shadowRadius: 4,
    elevation: 2,
  },
  buttonPressed: {
    backgroundColor: alpha.cyan(0.28),
  },
  buttonDisabled: {
    borderColor: colors.borderDim,
    backgroundColor: alpha.panel(0.9),
  },
  buttonText: {
    color: colors.cyan,
    fontFamily: fonts.mono,
    fontSize: 11,
    letterSpacing: 1,
  },
  buttonTextDisabled: {
    color: colors.textMuted,
  },
});
