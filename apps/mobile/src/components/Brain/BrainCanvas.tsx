/**
 * A ponte entre o React Native e o motor do brain (`brainHtml.ts`).
 *
 * Este componente não desenha nada: ele hospeda o WebView, entrega o grafo uma
 * vez e traduz mudanças de prop em **comandos** injetados. A distinção importa —
 * o motor lá dentro tem estado próprio (posições da física, `lit` acumulado de
 * cada nó) que precisa sobreviver a re-render do React. Reenviar estado a cada
 * render zeraria a simulação e o cérebro nunca assentaria.
 *
 * Por isso a interface é de contadores (`activation.seq`, `resetSeq`, vindos de
 * `useChatStore`): efeito dispara na *mudança do número*, e cada mudança vira
 * exatamente uma chamada.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { StyleSheet, View, type ViewStyle } from 'react-native';
import { WebView } from 'react-native-webview';
import type { WebViewMessageEvent } from 'react-native-webview/lib/WebViewTypes';

import { fetchBrainGraph } from '../../api/graph';
import { BRAIN_HTML } from './brainHtml';

export interface BrainCanvasProps {
  /** `chat` = cinza de fundo, sem toque. `full` = colorido e manipulável. */
  mode: 'chat' | 'full';
  /** Contador + caminhos do último `tool_call`. */
  activation?: { seq: number; paths: string[] } | null;
  /** Sobe quando a conversa troca: devolve todo o cérebro ao cinza. */
  resetSeq?: number;
  style?: ViewStyle;
  /** Chamado quando o `/graph.json` não pôde ser lido. */
  onGraphError?: (message: string) => void;
}

/**
 * Serializa para um literal que pode ser colado dentro de código JS.
 *
 * `JSON.stringify` quase basta: JSON é subconjunto da sintaxe de objeto do
 * JavaScript. As duas exceções são U+2028 e U+2029, que são válidos numa string
 * JSON e **quebra de linha** no parser JS — colados crus dentro de uma expressão
 * geram erro de sintaxe. Rótulos de nó vêm de arquivos arbitrários do
 * repositório, então isto não é hipotético.
 */
function toJsLiteral(value: unknown): string {
  return JSON.stringify(value)
    .replace(/\u2028/g, '\\u2028')
    .replace(/\u2029/g, '\\u2029');
}

export function BrainCanvas({
  mode,
  activation,
  resetSeq = 0,
  style,
  onGraphError,
}: BrainCanvasProps) {
  const webRef = useRef<WebView>(null);
  const [ready, setReady] = useState(false);

  const run = useCallback((code: string) => {
    // `window.__brain` só existe depois que o script do documento roda. O guarda
    // aqui cobre a corrida entre o `onMessage` de 'ready' e um efeito que
    // dispare no mesmo tick.
    webRef.current?.injectJavaScript(`if (window.__brain) { ${code} } true;`);
  }, []);

  const handleMessage = useCallback(
    (event: WebViewMessageEvent) => {
      let payload: { type?: string };
      try {
        payload = JSON.parse(event.nativeEvent.data) as { type?: string };
      } catch {
        return;
      }
      if (payload.type !== 'ready') return;
      setReady(true);
    },
    [],
  );

  // O grafo entra uma vez, quando o motor avisa que existe. Buscar antes do
  // 'ready' seria adiantar rede para jogar o resultado fora.
  useEffect(() => {
    if (!ready) return;
    let alive = true;
    fetchBrainGraph()
      .then((graph) => {
        if (!alive) return;
        run(`window.__brain.setGraph(${toJsLiteral(graph)});`);
      })
      .catch((error: unknown) => {
        if (!alive) return;
        onGraphError?.(error instanceof Error ? error.message : 'Falha ao carregar o grafo.');
      });
    return () => {
      alive = false;
    };
  }, [ready, run, onGraphError]);

  useEffect(() => {
    if (!ready) return;
    run(`window.__brain.setMode(${toJsLiteral(mode)});`);
  }, [ready, mode, run]);

  useEffect(() => {
    if (!ready || !activation || activation.seq === 0 || activation.paths.length === 0) return;
    run(`window.__brain.activate(${toJsLiteral(activation.paths)});`);
    // `seq` na lista de dependências e `paths` fora: dois tool_calls no mesmo
    // arquivo têm `paths` idêntico e precisam acender duas vezes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, activation?.seq, run]);

  useEffect(() => {
    if (!ready || resetSeq === 0) return;
    run('window.__brain.reset();');
  }, [ready, resetSeq, run]);

  return (
    <View style={[styles.container, style]} pointerEvents={mode === 'full' ? 'auto' : 'none'}>
      <WebView
        ref={webRef}
        source={{ html: BRAIN_HTML }}
        originWhitelist={['*']}
        onMessage={handleMessage}
        style={styles.web}
        // O documento tem fundo próprio; sem isto o iOS pinta branco por um
        // quadro antes do primeiro `draw`, o que aparece como um flash.
        containerStyle={styles.web}
        // Nada aqui rola, navega ou abre janela. Desligar é tanto correção
        // (arrastar o cérebro não pode arrastar a página) quanto superfície a
        // menos.
        scrollEnabled={false}
        bounces={false}
        overScrollMode="never"
        setSupportMultipleWindows={false}
        javaScriptEnabled
        domStorageEnabled={false}
        // Canvas animado em camada de software no Android cai para uns poucos
        // quadros por segundo.
        androidLayerType="hardware"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#02060c',
  },
  web: {
    flex: 1,
    backgroundColor: 'transparent',
  },
});
