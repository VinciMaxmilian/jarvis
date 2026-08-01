/**
 * As rotas, num arquivo que não importa nenhuma tela.
 *
 * Os param lists moram aqui — e não no `App.tsx`, onde os navegadores são
 * construídos — porque `App.tsx` importa as telas e as telas precisam dos tipos
 * das rotas. Declarar os tipos junto dos navegadores fecharia esse ciclo; um
 * módulo só de tipos o abre.
 */

import type { NavigatorScreenParams } from '@react-navigation/native';

export type TabParamList = {
  /** `conversationId` chega quando o Histórico manda abrir uma conversa. */
  Chat: { conversationId?: string } | undefined;
  Goals: undefined;
  Brain: undefined;
  History: undefined;
  Settings: undefined;
};

export type RootStackParamList = {
  Login: undefined;
  Tabs: NavigatorScreenParams<TabParamList> | undefined;
};
