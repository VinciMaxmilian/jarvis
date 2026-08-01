/**
 * O grafo do código que vira o brain.
 *
 * A origem serve `/graph.json` como estático, junto do PWA e atrás do mesmo gate
 * do Access (`apps/web/nginx.conf`; o mesmo arquivo que
 * `apps/web/src/components/NeuralMap` consome). Não há endpoint de API para ele
 * — é arquivo, não rota.
 *
 * ## Por que reduzir antes de desenhar
 *
 * O arquivo tem ~1,5 MB e alguns milhares de nós. No desktop o canvas aguenta;
 * num celular, a repulsão N-corpos por quadro e o custo de atravessar a ponte
 * até o WebView transformam isso em segundos de travamento. A amostragem abaixo
 * corta para algumas centenas de nós — o suficiente para o desenho ainda parecer
 * o mesmo cérebro, com uma fração do custo.
 *
 * O critério da amostragem não é só grau. Um nó só consegue acender se tiver
 * `source_file` — é por esse campo que o `tool_call` casa com o nó
 * (`toolCallTargetPath` em `chat.ts`). Amostrar puramente por grau encheria o
 * cérebro de nós que nunca podem acender, e o recurso principal desta tela
 * ficaria visualmente morto. Por isso os nós com arquivo têm cota garantida.
 */

import axios from 'axios';

import { API_BASE_URL } from '../config';
import { useAuthStore } from '../store/useAuthStore';

export interface BrainNode {
  id: string;
  label: string;
  source_file: string;
  community: number;
}

export interface BrainLink {
  source: string;
  target: string;
  confidence?: string;
}

export interface BrainGraph {
  nodes: BrainNode[];
  links: BrainLink[];
}

const MAX_NODES = 260;
const MAX_LINKS = 900;
/** Fatia dos nós reservada a quem tem `source_file` (ou seja, pode acender). */
const FILE_NODE_QUOTA = 0.7;

interface RawNode {
  id?: unknown;
  label?: unknown;
  source_file?: unknown;
  community?: unknown;
}

interface RawLink {
  source?: unknown;
  target?: unknown;
  confidence?: unknown;
}

function downsample(raw: { nodes?: RawNode[]; links?: RawLink[] }): BrainGraph {
  const nodes: BrainNode[] = (raw.nodes ?? [])
    .filter((n): n is RawNode & { id: string } => typeof n.id === 'string' && n.id.length > 0)
    .map((n) => ({
      id: n.id,
      label: typeof n.label === 'string' ? n.label : n.id,
      source_file: typeof n.source_file === 'string' ? n.source_file : '',
      community: typeof n.community === 'number' ? n.community : 0,
    }));

  const known = new Set(nodes.map((n) => n.id));
  const links: BrainLink[] = (raw.links ?? [])
    .filter(
      (l): l is RawLink & { source: string; target: string } =>
        typeof l.source === 'string' &&
        typeof l.target === 'string' &&
        l.source !== l.target &&
        known.has(l.source) &&
        known.has(l.target),
    )
    .map((l) => ({
      source: l.source,
      target: l.target,
      confidence: typeof l.confidence === 'string' ? l.confidence : undefined,
    }));

  const degree = new Map<string, number>();
  for (const link of links) {
    degree.set(link.source, (degree.get(link.source) ?? 0) + 1);
    degree.set(link.target, (degree.get(link.target) ?? 0) + 1);
  }
  const byDegree = (a: BrainNode, b: BrainNode) =>
    (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0);

  const withFile = nodes.filter((n) => n.source_file).sort(byDegree);
  const withoutFile = nodes.filter((n) => !n.source_file).sort(byDegree);

  const fileQuota = Math.round(MAX_NODES * FILE_NODE_QUOTA);
  const chosen = [...withFile.slice(0, fileQuota)];
  // Cota não usada (poucos nós com arquivo) volta para o bolo geral em vez de
  // encolher o cérebro.
  chosen.push(...withoutFile.slice(0, MAX_NODES - chosen.length));

  const keep = new Set(chosen.map((n) => n.id));
  const keptLinks = links
    .filter((l) => keep.has(l.source) && keep.has(l.target))
    .sort((a, b) => {
      const sa = (degree.get(a.source) ?? 0) + (degree.get(a.target) ?? 0);
      const sb = (degree.get(b.source) ?? 0) + (degree.get(b.target) ?? 0);
      return sb - sa;
    })
    .slice(0, MAX_LINKS);

  return { nodes: chosen, links: keptLinks };
}

/**
 * Memo de processo. O grafo é gerado por uma ferramenta offline (`graphify`) e
 * não muda enquanto o app está aberto; rebaixar 1,5 MB a cada visita à aba seria
 * gastar dados do usuário por nada.
 *
 * A promessa é limpa em caso de falha para que a próxima tentativa não fique
 * presa ao erro de uma rede que já voltou.
 */
let cached: Promise<BrainGraph> | null = null;

export function fetchBrainGraph(): Promise<BrainGraph> {
  if (cached) return cached;
  cached = axios
    .get<{ nodes?: RawNode[]; links?: RawLink[] }>(`${API_BASE_URL}/graph.json`, {
      timeout: 30_000,
      headers: { Accept: 'application/json', ...useAuthStore.getState().authHeaders() },
      withCredentials: true,
    })
    .then((response) => downsample(response.data))
    .catch((error: unknown) => {
      cached = null;
      throw error;
    });
  return cached;
}
