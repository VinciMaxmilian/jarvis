/**
 * Paleta do HUD, espelhando os tokens de `apps/web/src/index.css`.
 *
 * As cores ficam em `hsl(...)` / `hsla(...)` **com vírgula** de propósito: é a
 * única sintaxe que o normalizador de cor do React Native entende (a forma
 * moderna sem vírgula, `hsl(222 47% 5%)`, que o CSS do PWA usa, é rejeitada em
 * runtime e vira crash de estilo). Manter os mesmos números H/S/L do web deixa
 * as duas interfaces comparáveis lado a lado sem tabela de conversão.
 */

import { Platform } from 'react-native';

export const colors = {
  // Superfícies
  bg: 'hsl(0, 0%, 93%)',
  surface: 'hsl(0, 0%, 93%)',
  panel: 'hsl(0, 0%, 93%)',
  elevated: 'hsl(0, 0%, 96%)',

  // Acentos neon
  cyan: 'hsl(210, 100%, 50%)',
  blue: 'hsl(210, 80%, 60%)',
  purple: 'hsl(210, 60%, 40%)',
  amber: 'hsl(38, 95%, 55%)',
  red: 'hsl(0, 85%, 55%)',
  green: 'hsl(150, 85%, 40%)',

  // Texto
  textPrimary: 'hsl(0, 0%, 15%)',
  textSecondary: 'hsl(0, 0%, 40%)',
  textMuted: 'hsl(0, 0%, 55%)',

  // Bordas e Sombras
  borderDim: 'hsl(0, 0%, 85%)',
  borderGlow: 'hsl(210, 100%, 50%)',
  shadowLight: '#ffffff',
  shadowDark: '#d1d5db',
} as const;

/** Versões translúcidas usadas em fundos de badge, realces e overlays. */
export const alpha = {
  cyan: (a: number) => `hsla(210, 100%, 50%, ${a})`,
  blue: (a: number) => `hsla(210, 80%, 60%, ${a})`,
  purple: (a: number) => `hsla(210, 60%, 40%, ${a})`,
  amber: (a: number) => `hsla(38, 95%, 55%, ${a})`,
  red: (a: number) => `hsla(0, 85%, 55%, ${a})`,
  green: (a: number) => `hsla(150, 85%, 40%, ${a})`,
  bg: (a: number) => `hsla(0, 0%, 93%, ${a})`,
  surface: (a: number) => `hsla(0, 0%, 93%, ${a})`,
  panel: (a: number) => `hsla(0, 0%, 93%, ${a})`,
} as const;

/**
 * Cor de cada estado de `GoalStatus` / `TaskStatus`
 * (`packages/shared/contracts.py`). O mapa é total sobre os dois enums; valor
 * desconhecido cai em `textMuted` em vez de sumir da tela.
 */
export const statusColor: Record<string, string> = {
  draft: colors.textMuted,
  pending: colors.amber,
  active: colors.cyan,
  running: colors.cyan,
  blocked: colors.amber,
  waiting_approval: colors.amber,
  done: colors.green,
  failed: colors.red,
  cancelled: colors.red,
};

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  xxl: 32,
} as const;

export const radius = {
  sm: 4,
  md: 8,
  lg: 12,
  pill: 999,
} as const;

/**
 * `monospace` no Android e `Menlo` no iOS: não existe uma família que os dois
 * resolvam pelo mesmo nome, e cair no default (proporcional) apaga o alinhamento
 * de coluna de que a estética de HUD depende.
 */
export const fonts = {
  mono: Platform.select({ ios: 'Menlo', android: 'monospace', default: 'monospace' }),
} as const;
