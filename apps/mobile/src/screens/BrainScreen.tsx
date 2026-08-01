/**
 * O cérebro como assunto, não como cenário.
 *
 * Mesmo motor da aba de chat (`brainHtml.ts`), outro modo: colorido desde o
 * início, câmera de frente e toque habilitado — arrastar gira, pinçar aproxima.
 * A instância é separada da do chat de propósito: compartilhar uma só exigiria
 * mover o WebView entre árvores de navegação, o que no React Native o desmonta e
 * recomeça a física do zero, que é justamente o que se quer evitar.
 *
 * O grafo em si é buscado uma vez por processo (`fetchBrainGraph` memoiza), então
 * a segunda instância custa render, não rede.
 */

import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { BrainCanvas } from '../components/Brain/BrainCanvas';
import { colors, fonts, spacing } from '../theme/colors';

export default function BrainScreen() {
  const [error, setError] = useState<string | null>(null);

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.brand}>NEURAL MAP</Text>
        <Text style={styles.hint}>arraste gira · pinça aproxima</Text>
      </View>

      {error && <Text style={styles.error}>{error}</Text>}

      <BrainCanvas mode="full" onGraphError={setError} style={styles.canvas} />
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
  hint: {
    color: colors.textMuted,
    fontFamily: fonts.mono,
    fontSize: 9,
  },
  error: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.xs,
    color: colors.red,
    fontFamily: fonts.mono,
    fontSize: 10,
  },
  canvas: { flex: 1 },
});
