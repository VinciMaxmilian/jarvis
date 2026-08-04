export interface GraphNode {
  id: string;
  label: string;
  source_file?: string;
  file_type?: string;
  community: number;
  god?: boolean;
  x: number; y: number; z: number;
  vx: number; vy: number; vz: number;
  deg: number;
  sx: number; sy: number; sc: number; dz: number;
  r: number; c: string;
  ci: number;   // índice na paleta — evita re-hash de cor por frame
  act: boolean; // "arquivo ativo": recalculado só quando activeFiles muda
  vis: boolean; // passou pelo culling deste frame
  lobe: { p: string, x: number, y: number, z: number, n: string };
}

export interface GraphLink {
  source: string;
  target: string;
  confidence?: string;
  relation?: string;
  s: GraphNode;
  t: GraphNode;
}

export type Theme = 'light' | 'dark';

/* ================================================================ *
 * PALETA
 *
 * O canvas não consegue ler `var(--x)`: `ctx.fillStyle` precisa de uma
 * cor concreta. Então o Engine não conhece mais nenhuma cor literal —
 * ele recebe uma `PaletaGrafo` já resolvida. Quem resolve é
 * `paletaDoTema()`, que lê as CSS custom properties do documento em
 * runtime e cai nos literais de `FALLBACK` quando o token não existe.
 *
 * Consequência: enquanto os tokens Industry não estiverem no CSS, o
 * desenho fica pixel-a-pixel igual ao de hoje; quando entrarem, o
 * canvas acompanha o tema sem o Engine importar uma linha de CSS.
 * ================================================================ */

export interface PaletaGrafo {
  /** Rampa categórica por comunidade. Sempre `#rrggbb` — `hex2rgb` depende disso. */
  comunidades: string[];
  /** Gradiente radial de fundo: centro → meio → borda. Cores CSS completas. */
  fundo: [string, string, string];

  /* Daqui pra baixo: tripla `"r, g, b"`. O laço de desenho monta o
   * `rgba()` com o alfa que ele já calcula por frame — o alfa é peso
   * visual, não cor, e por isso continua no código de desenho. */
  /** Anéis orbitais de fundo e varredura. */
  anel: string;
  /** Aresta normal + halo do nó selecionado. */
  aresta: string;
  /** Aresta `confidence === "INFERRED"` (tracejada). */
  arestaInferida: string;
  /** Aresta `confidence === "AMBIGUOUS"` (tracejada). */
  arestaAmbigua: string;
  /** Aresta apagada do modo fundo. */
  arestaApagada: string;
  /** Miolo claro do nó. */
  nucleoNo: string;
  /** Miolo do nó quando dessaturado (modo fundo, nó inativo). */
  nucleoCinza: string;
  /** Arco pulsante do god node. */
  anelGod: string;
  /** Rótulo de lobo quando dessaturado (modo fundo). */
  rotuloAreaCinza: string;

  /* Cores CSS completas — o alfa aqui é fixo e faz parte da cor. */
  /** Tarja atrás do rótulo do nó. */
  rotuloFundo: string;
  /** Texto do rótulo em destaque (selecionado / hover / ativo). */
  rotuloTexto: string;
}

const hex2rgb = (h: string): [number, number, number] => [
  parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16),
];

const rgb2hex = ([r, g, b]: [number, number, number]): string =>
  '#' + ((1 << 24) | (r << 16) | (g << 8) | b).toString(16).slice(1);

/* Fallback: exatamente as cores que o Engine usava embutidas. A clara é
 * a mesma família de matizes da escura, só que rebaixada em luminosidade
 * para sobreviver ao fundo neumórfico. */
const PAL_DARK = ["#00e5ff","#ffb020","#4d9dff","#00ffc8","#b06bff","#ff7a3d","#7dff6f","#ff5c8a"];
const PAL_LIGHT = ["#0088a8","#a86a00","#2f66cc","#00806a","#6f3fc0","#c2480f","#3f8f28","#c01a54"];

const FALLBACK: Record<Theme, PaletaGrafo> = {
  light: {
    comunidades: PAL_LIGHT,
    fundo: ["#f4f6fa", "#e8ebf2", "#dde1ea"],
    anel: "18, 70, 110",
    aresta: "40, 90, 140",
    arestaInferida: "170, 110, 0",
    arestaAmbigua: "200, 30, 70",
    arestaApagada: "120, 130, 145",
    nucleoNo: "255, 255, 255",
    nucleoCinza: "160, 160, 160",
    anelGod: "190, 130, 0",
    rotuloAreaCinza: "140, 140, 140",
    rotuloFundo: "rgba(255,255,255,.86)",
    rotuloTexto: "#1b2028",
  },
  dark: {
    comunidades: PAL_DARK,
    fundo: ["#061722", "#030b13", "#02060c"],
    anel: "55, 224, 255",
    aresta: "55, 224, 255",
    arestaInferida: "255, 176, 32",
    arestaAmbigua: "255, 84, 112",
    arestaApagada: "120, 120, 120",
    nucleoNo: "235, 253, 255",
    nucleoCinza: "160, 160, 160",
    anelGod: "255, 176, 32",
    rotuloAreaCinza: "140, 140, 140",
    rotuloFundo: "rgba(2,8,14,.72)",
    rotuloTexto: "#eafcff",
  },
};

/* ---------------------------------------------------------------- *
 * Resolução de cor CSS → rgb
 * ---------------------------------------------------------------- */

let sonda: CanvasRenderingContext2D | null | undefined;
function sondaCtx(): CanvasRenderingContext2D | null {
  if (sonda !== undefined) return sonda;
  if (typeof document === 'undefined') { sonda = null; return sonda; }
  const cv = document.createElement('canvas');
  cv.width = 1; cv.height = 1;
  sonda = cv.getContext('2d', { willReadFrequently: true });
  return sonda;
}

function pintar(c: CanvasRenderingContext2D, sentinela: string, valor: string): [number, number, number] {
  c.fillStyle = sentinela;
  c.fillStyle = valor;          // valor inválido não altera fillStyle
  c.clearRect(0, 0, 1, 1);
  c.fillRect(0, 0, 1, 1);
  const d = c.getImageData(0, 0, 1, 1).data;
  return [d[0], d[1], d[2]];
}

const cacheRgb = new Map<string, [number, number, number] | null>();

/**
 * Converte qualquer cor que o browser aceite — hex, `rgb()`, `hsl()`,
 * `oklch()`, `color-mix()` — para `[r,g,b]`. Rasteriza 1 pixel porque é
 * o único caminho que não depende de a serialização computada ser sRGB
 * (os tokens do Industry são OKLCH). Duas sentinelas diferentes detectam
 * valor inválido: se `fillStyle` não mudou, as leituras divergem.
 * Só roda na troca de tema, e ainda assim com cache.
 */
function cssParaRgb(valor: string): [number, number, number] | null {
  const v = valor.trim();
  if (!v) return null;
  const emCache = cacheRgb.get(v);
  if (emCache !== undefined) return emCache;

  const c = sondaCtx();
  let res: [number, number, number] | null = null;
  if (c) {
    const a = pintar(c, '#000000', v);
    const b = pintar(c, '#ffffff', v);
    if (a[0] === b[0] && a[1] === b[1] && a[2] === b[2]) res = a;
  }
  cacheRgb.set(v, res);
  return res;
}

/** Primeiro token da lista que resolver, já como `"r, g, b"`. */
function tokenRgb(d: CSSStyleDeclaration, nomes: string[], padrao: string): string {
  for (const nome of nomes) {
    const rgb = cssParaRgb(d.getPropertyValue(nome));
    if (rgb) return rgb.join(', ');
  }
  return padrao;
}

/** Idem, mas normalizado para `#rrggbb` (o que `hex2rgb` sabe ler). */
function tokenHex(d: CSSStyleDeclaration, nomes: string[], padrao: string): string {
  for (const nome of nomes) {
    const rgb = cssParaRgb(d.getPropertyValue(nome));
    if (rgb) return rgb2hex(rgb);
  }
  return padrao;
}

const misturarHex = (a: string, b: string, t: number): string => {
  const x = hex2rgb(a), y = hex2rgb(b);
  return rgb2hex([
    Math.round(x[0] + (y[0] - x[0]) * t),
    Math.round(x[1] + (y[1] - x[1]) * t),
    Math.round(x[2] + (y[2] - x[2]) * t),
  ]);
};

function raizPadrao(raiz?: HTMLElement): HTMLElement | null {
  if (raiz) return raiz;
  return typeof document !== 'undefined' ? document.documentElement : null;
}

/**
 * Qual variante o documento está pedindo. Ordem: `data-theme` explícito,
 * classe `dark`/`light`, e por último a luminância real de `--color-bg`
 * (ou `--neu-bg`) — esse último degrau faz o canvas acertar mesmo que o
 * design system troque o nome do tema.
 */
export function temaEfetivo(raiz?: HTMLElement): Theme {
  const el = raizPadrao(raiz);
  if (!el) return 'light';

  const marca = (el.getAttribute('data-theme') || '').toLowerCase();
  if (/dark|command|escuro|noite/.test(marca)) return 'dark';
  if (/light|industry|claro/.test(marca)) return 'light';

  if (el.classList.contains('dark')) return 'dark';
  if (el.classList.contains('light')) return 'light';

  const d = getComputedStyle(el);
  const rgb = cssParaRgb(d.getPropertyValue('--color-bg'))
    ?? cssParaRgb(d.getPropertyValue('--neu-bg'));
  if (rgb) return (rgb[0] * 0.299 + rgb[1] * 0.587 + rgb[2] * 0.114) < 128 ? 'dark' : 'light';

  return 'light';
}

/**
 * Monta a paleta a partir dos tokens do tema. Cada campo tem uma cadeia
 * de candidatos: token semântico → passo de rampa → literal de
 * `FALLBACK`. Nada aqui quebra se o CSS ainda não tiver os tokens.
 *
 * Os papéis sem token equivalente no DS (inferida = âmbar, ambígua =
 * vermelho, anel do god node) aceitam um override opcional `--graph-*`
 * e só então caem no literal — o Industry não define cor semântica de
 * aviso/erro, e inventar uma a partir do acento apagaria a distinção.
 */
export function paletaDoTema(tema: Theme, raiz?: HTMLElement): PaletaGrafo {
  const fb = FALLBACK[tema];
  const el = raizPadrao(raiz);
  if (!el) return fb;
  const d = getComputedStyle(el);

  const claro = tema === 'light';
  // O DS avisa que o acento puro tem ~3:1: no escuro usa-se o passo claro.
  const passoAcento = claro ? '--color-accent-700' : '--color-accent-400';

  // Comunidades: o Industry não tem rampa categórica (a dele é
  // monocromática). Manter os matizes atuais é o que preserva a leitura
  // do grafo; `--graph-comunidade-N` fica como porta de entrada.
  const comunidades = fb.comunidades.map((hex, i) =>
    tokenHex(d, [`--graph-comunidade-${i + 1}`], hex));

  const centro = tokenHex(d, ['--color-surface'], fb.fundo[0]);
  const borda = tokenHex(d, ['--color-bg'], fb.fundo[2]);
  const meio = (centro === fb.fundo[0] && borda === fb.fundo[2])
    ? fb.fundo[1]                       // sem tokens: gradiente original intacto
    : misturarHex(centro, borda, 0.5);

  const fundoRgb = cssParaRgb(d.getPropertyValue('--color-bg'));
  const rotuloFundo = fundoRgb
    ? `rgba(${fundoRgb.join(',')},${claro ? '.86' : '.72'})`
    : fb.rotuloFundo;

  return {
    comunidades,
    fundo: [centro, meio, borda],
    anel: tokenRgb(d, ['--graph-anel', passoAcento, '--color-accent'], fb.anel),
    aresta: tokenRgb(d, ['--graph-aresta', '--color-accent'], fb.aresta),
    arestaInferida: tokenRgb(d, ['--graph-aresta-inferida'], fb.arestaInferida),
    arestaAmbigua: tokenRgb(d, ['--graph-aresta-ambigua'], fb.arestaAmbigua),
    arestaApagada: tokenRgb(d, ['--color-neutral-500', '--color-divider'], fb.arestaApagada),
    // 100 é o passo mais claro da rampa nos dois temas — é o que faz o
    // miolo do nó brilhar tanto no claro quanto no escuro.
    nucleoNo: tokenRgb(d, ['--graph-nucleo', '--color-neutral-100'], fb.nucleoNo),
    nucleoCinza: tokenRgb(d, ['--color-neutral-400'], fb.nucleoCinza),
    anelGod: tokenRgb(d, ['--graph-god'], fb.anelGod),
    rotuloAreaCinza: tokenRgb(d, ['--color-neutral-500', '--color-divider'], fb.rotuloAreaCinza),
    rotuloFundo,
    rotuloTexto: tokenHex(d, ['--color-text'], fb.rotuloTexto),
  };
}

export const LOBES = [
  { p: "apps/web", x: -800, y: 0, z: -800, n: "Frontend (Web)" },
  { p: "apps/api", x: 0, y: 0, z: -800, n: "Backend (API)" },
  { p: "packages/shared", x: 800, y: 0, z: -800, n: "Shared" },
  { p: "packages/llm", x: -800, y: 0, z: 0, n: "Intelligence (LLM)" },
  { p: "packages/agents", x: 0, y: 0, z: 0, n: "Agents" },
  { p: "packages/memory", x: 800, y: 0, z: 0, n: "Memory" },
  { p: "packages/registry", x: -800, y: 0, z: 800, n: "Registry" },
  { p: "packages/scheduler", x: 0, y: 0, z: 800, n: "Scheduler" },
  { p: "tests/", x: 800, y: 0, z: 800, n: "Tests" },
  { p: "infrastructure", x: -1600, y: 0, z: 0, n: "Infrastructure" },
];

/* graph.json tem 1.5 MB. Uma única busca+parse compartilhada por todas as
 * montagens (ChatPage usa o mapa como fundo, BrainPage em primeiro plano). */
const graphPromises = new Map<string, Promise<any>>();
export function loadGraph(url = '/graph.json'): Promise<any> {
  if (!graphPromises.has(url)) {
    const promise = fetch(url).then(r => r.json()).catch(err => {
      graphPromises.delete(url);
      throw err;
    });
    graphPromises.set(url, promise);
  }
  return graphPromises.get(url)!;
}

/* Quantização em raiz quadrada: os alfas úteis se concentram embaixo (0.04 no
 * modo fundo, 0.16 no normal). Em escala linear tudo isso cairia no mesmo
 * degrau e as arestas apagadas apareceriam muito mais fortes do que deviam. */
const QUANT_A = 12;  // níveis de alfa
const QUANT_W = 4;   // níveis de espessura
const BUCKETS = 4 * QUANT_A * QUANT_W;
const encodeA = (al: number) => Math.min(QUANT_A - 1, Math.max(0, Math.floor(Math.sqrt(al) * QUANT_A)));
const decodeA = (q: number) => ((q + 0.5) / QUANT_A) ** 2;
const W_LEVELS = [0.5, 1, 1.75, 2.6];
const encodeW = (w: number) => {
  for (let i = 0; i < QUANT_W - 1; i++) {
    if (w < (W_LEVELS[i] + W_LEVELS[i + 1]) / 2) return i;
  }
  return QUANT_W - 1;
};
const decodeW = (q: number) => W_LEVELS[q];

export class NeuralEngine {
  private cv: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  public nodes: GraphNode[] = [];
  private links: GraphLink[] = [];
  private byId = new Map<string, GraphNode>();
  private nbr = new Map<string, { n: GraphNode, l: GraphLink }[]>();

  private W = 0; private H = 0; private DPR = 1;
  private yaw = 0.4; private pitch = -0.22; private zoom = 1; private dist = 780;
  private spin = true; private showAreas = true; private showEdges = true;
  private alpha = 1;
  private panX = 0; private panY = 0; private panZ = 0;
  private tgX = 0; private tgY = 0; private tgZ = 0;

  private drag = false; private lx = 0; private ly = 0; private moved = 0;
  private t = 0;
  private raf = 0;
  private lastTs = 0;
  private running = false;
  private pal: PaletaGrafo;
  private reduceMotion = false;

  // buffers reaproveitados — nada disso pode alocar dentro do laço de render
  private order: GraphNode[] = [];
  private bucket: GraphLink[][] = [];
  private bucketUsed: number[] = [];
  private sprites = new Map<string, HTMLCanvasElement>();
  private textW = new Map<string, number>();
  private bgGrad: CanvasGradient | null = null;
  private focus: Set<string> | null = null;
  private focusKey = '';

  private ro: ResizeObserver | null = null;
  private io: IntersectionObserver | null = null;
  private ac = new AbortController();
  private visible_ = true;
  private grayLevel: number[] = [];
  private palRgb: string[] = [];

  public hiddenPaths = new Set<string>();
  public activeFiles = new Set<string>();
  public hover: GraphNode | null = null;
  public sel: GraphNode | null = null;
  public matched: Set<string> | null = null;
  private lobes: any[] = [];

  private _backgroundMode = false;
  public get backgroundMode() { return this._backgroundMode; }
  public set backgroundMode(val: boolean) {
    if (this._backgroundMode === val) return;
    this._backgroundMode = val;
    if (val) {
      this.pitch = -1.2;
      this.zoom = 0.7;
    } else {
      this.pitch = -0.22;
      this.zoom = 1;
    }
    this.resize();
  }

  public onHover?: (n: GraphNode | null, x: number, y: number) => void;
  public onClick?: (n: GraphNode | null) => void;

  public highlightNodes(files: string[]) {
    this.activeFiles = new Set(files);
    this.recomputeActive();
    this.wake();
  }

  /** Aceita a paleta pronta ou o nome do tema (resolvido na hora). */
  constructor(canvas: HTMLCanvasElement, rawData: any, paleta: Theme | PaletaGrafo = 'light') {
    this.cv = canvas;
    const context = canvas.getContext('2d', { alpha: true, desynchronized: true });
    if (!context) throw new Error("Could not get 2D context");
    this.ctx = context;

    this.pal = typeof paleta === 'string' ? paletaDoTema(paleta) : paleta;
    this.reduceMotion = typeof matchMedia === 'function'
      && matchMedia('(prefers-reduced-motion: reduce)').matches;

    for (let i = 0; i < BUCKETS; i++) this.bucket.push([]);
    this.derivarCache();

    this.initData(rawData);
    this.setupEvents();

    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(canvas);
    this.resize();

    document.addEventListener('visibilitychange', () => {
      if (document.hidden) this.pause();
      else if (this.visible_) this.start();
    }, { signal: this.ac.signal });

    this.io = new IntersectionObserver(entries => {
      this.visible_ = entries[0].isIntersecting;
      if (this.visible_ && !document.hidden) this.start(); else this.pause();
    }, { threshold: 0 });
    this.io.observe(canvas);

    this.warmup();
    this.start();
  }

  public dispose() {
    this.pause();
    this.ro?.disconnect();
    this.io?.disconnect();
    this.ac.abort();
    this.sprites.clear();
    this.textW.clear();
    this.nodes = [];
    this.links = [];
    this.byId.clear();
    this.nbr.clear();
  }

  private start() {
    if (this.running) return;
    this.running = true;
    this.lastTs = 0;
    this.raf = requestAnimationFrame(this.loop);
  }

  private pause() {
    this.running = false;
    cancelAnimationFrame(this.raf);
  }

  public setOptions(opt: { spin?: boolean, showAreas?: boolean, showEdges?: boolean }) {
    if (opt.spin !== undefined) this.spin = opt.spin;
    if (opt.showAreas !== undefined) { this.showAreas = opt.showAreas; this.alpha = Math.max(this.alpha, 0.5); }
    if (opt.showEdges !== undefined) this.showEdges = opt.showEdges;
    this.wake();
  }

  /** Caches derivados da paleta — nada disso pode ser recalculado por frame. */
  private derivarCache() {
    this.grayLevel = this.pal.comunidades.map(h => {
      const [r, g, b] = hex2rgb(h);
      return Math.round(r * 0.299 + g * 0.587 + b * 0.114);
    });
    this.palRgb = this.pal.comunidades.map(h => hex2rgb(h).join(','));
  }

  /**
   * Ponto único de troca de cor. Invalida o gradiente de fundo e os
   * sprites de brilho (que são assados com a cor da comunidade) e
   * reacende a animação para o próximo frame já sair no tema novo.
   */
  public aplicarPaleta(paleta: PaletaGrafo) {
    this.pal = paleta;
    this.derivarCache();
    const com = this.pal.comunidades;
    for (const n of this.nodes) n.c = com[n.ci];   // FileExplorer lê `n.c`
    this.bgGrad = null;
    this.sprites.clear();
    this.wake();
  }

  /** Atalho: resolve a paleta do tema a partir do CSS e aplica. */
  public setTheme(theme: Theme) {
    this.aplicarPaleta(paletaDoTema(theme));
  }

  public selectNode(n: GraphNode | null) {
    this.sel = n;
    if (!n) { this.tgX = 0; this.tgY = 0; this.tgZ = 0; }
    else { this.tgX = n.x; this.tgY = n.y; this.tgZ = n.z; }
    this.onClick?.(n);
  }

  public wake() {
    this.alpha = Math.max(this.alpha, 0.35);
  }

  public realign() {
    this.alpha = 1;
    for (const n of this.nodes) {
      n.vx += (Math.random() - 0.5) * 8;
      n.vy += (Math.random() - 0.5) * 8;
      n.vz += (Math.random() - 0.5) * 8;
    }
  }

  public search(query: string) {
    query = query.trim().toLowerCase();
    if (!query) { this.matched = null; return; }
    this.matched = new Set(this.nodes.filter(n =>
      n.label.toLowerCase().includes(query) ||
      (n.source_file || "").toLowerCase().includes(query)
    ).map(n => n.id));
  }

  private initData(GRAPH: any) {
    this.lobes = GRAPH.lobes || LOBES;
    const getLobe = (path: string) => this.lobes.find(l => path.includes(l.p)) || { p: "", x: 0, y: 0, z: 0, n: "Core" };
    const pal = this.pal.comunidades;

    this.nodes = (GRAPH.nodes || []).map((n: any) => {
      const ci = (n.community | 0) % pal.length;
      return {
        ...n, x: 0, y: 0, z: 0, vx: 0, vy: 0, vz: 0, deg: 0, sx: 0, sy: 0, sc: 1, dz: 0,
        ci, c: pal[ci], act: false, vis: true, lobe: getLobe(n.source_file || ""),
      };
    });
    this.byId = new Map(this.nodes.map(n => [n.id, n]));
    this.links = (GRAPH.links || []).map((l: any) => ({
      ...l, s: this.byId.get(l.source)!, t: this.byId.get(l.target)!,
    })).filter((l: any) => l.s && l.t && l.s !== l.t);

    for (const l of this.links) { l.s.deg++; l.t.deg++; }

    for (const n of this.nodes) this.nbr.set(n.id, []);
    for (const l of this.links) {
      this.nbr.get(l.s.id)!.push({ n: l.t, l });
      this.nbr.get(l.t.id)!.push({ n: l.s, l });
    }

    [...this.nodes].sort((a, b) => b.deg - a.deg).slice(0, 10).forEach(n => n.god = true);
    for (const n of this.nodes) n.r = 2.6 + Math.sqrt(n.deg) * 2.35;

    const N = this.nodes.length, GA = Math.PI * (3 - Math.sqrt(5));
    this.nodes.forEach((n, i) => {
      const y = 1 - (i / (N - 1)) * 2, r = Math.sqrt(Math.max(0, 1 - y * y)), th = GA * i;
      const R = 150 + Math.random() * 20;
      n.x = Math.cos(th) * r * R + n.lobe.x;
      n.y = y * R + n.lobe.y;
      n.z = Math.sin(th) * r * R + n.lobe.z;
    });

    this.order = this.nodes.slice();
  }

  /* activeFiles muda no máximo uma vez por mensagem; antes isso era um laço
   * aninhado de strings por nó E por aresta, a cada frame. */
  private recomputeActive() {
    if (this.activeFiles.size === 0) {
      for (const n of this.nodes) n.act = false;
      return;
    }
    const paths = [...this.activeFiles];
    for (const n of this.nodes) {
      const sf = n.source_file || "";
      let hit = false;
      if (sf) {
        const s = sf.toLowerCase().replace(/\\/g, '/');
        for (const raw of paths) {
          const p = raw.toLowerCase().replace(/\\/g, '/');
          if (p.includes(s) || s.includes(p)) { hit = true; break; }
        }
      }
      n.act = hit;
    }
    // Acende também os nós vizinhos diretamente conectados
    const toActivate = new Set<GraphNode>();
    for (const n of this.nodes) {
      if (n.act) {
        toActivate.add(n);
        for (const edge of this.nbr.get(n.id) || []) {
          toActivate.add(edge.n);
        }
      }
    }
    for (const n of toActivate) {
      n.act = true;
    }
  }

  private resize() {
    // O modo fundo é decorativo e fica atrás do conteúdo: 1 device pixel basta.
    const cap = this._backgroundMode ? 1 : 1.75;
    this.DPR = Math.min(window.devicePixelRatio || 1, cap);
    this.W = this.cv.clientWidth || this.W;
    this.H = this.cv.clientHeight || this.H;
    this.cv.width = Math.round(this.W * this.DPR);
    this.cv.height = Math.round(this.H * this.DPR);
    this.ctx.setTransform(this.DPR, 0, 0, this.DPR, 0, 0);
    this.bgGrad = null;
  }

  private setupEvents() {
    const sig = { signal: this.ac.signal };
    this.cv.addEventListener("pointerdown", e => {
      this.drag = true; this.moved = 0; this.lx = e.clientX; this.ly = e.clientY;
      this.cv.setPointerCapture(e.pointerId);
    }, sig);
    this.cv.addEventListener("pointerup", e => {
      this.drag = false;
      if (this.moved < 5) this.selectNode(this.pick(e.clientX, e.clientY));
    }, sig);
    this.cv.addEventListener("pointermove", e => {
      if (this.drag) {
        const dx = e.clientX - this.lx, dy = e.clientY - this.ly;
        this.moved += Math.abs(dx) + Math.abs(dy);
        this.yaw += dx * 0.006; this.pitch += dy * 0.006;
        this.pitch = Math.max(-1.45, Math.min(1.45, this.pitch));
        this.lx = e.clientX; this.ly = e.clientY;
      } else {
        const n = this.pick(e.clientX, e.clientY);
        if (n !== this.hover) {
          this.hover = n;
          this.onHover?.(n, e.clientX, e.clientY);
        }
      }
    }, sig);
    this.cv.addEventListener("wheel", e => {
      e.preventDefault();
      this.zoom = Math.max(0.25, Math.min(4.5, this.zoom * (e.deltaY > 0 ? 0.9 : 1.1)));
    }, { passive: false, signal: this.ac.signal });
  }

  private isVisible(n: GraphNode) {
    return !this.hiddenPaths.has(n.source_file || "unknown");
  }

  private pick(mx: number, my: number): GraphNode | null {
    let best: GraphNode | null = null, bd = 26;
    const rect = this.cv.getBoundingClientRect();
    const cx = mx - rect.left, cy = my - rect.top;
    for (const n of this.nodes) {
      if (!n.vis) continue;
      if (this.matched && !this.matched.has(n.id)) continue;
      const dx = n.sx - cx, dy = n.sy - cy;
      if (Math.abs(dx) > 40 || Math.abs(dy) > 40) continue; // rejeição barata antes do hypot
      const d = Math.hypot(dx, dy) - n.r * n.sc;
      if (d < bd) { bd = d; best = n; }
    }
    return best;
  }

  /** Um Math.random por nó em vez de dois por par testado. */
  private step() {
    if (this.alpha < 0.005) return;
    const REP = 1200, SPR = 0.02, LEN = 60;
    const nodes = this.nodes, N = nodes.length;
    const K = N > 900 ? 12 : 20;

    for (let i = 0; i < N; i++) {
      const a = nodes[i];
      const off = (Math.random() * N) | 0;
      for (let k = 0; k < K; k++) {
        const b = nodes[(i + off + k * 37) % N];
        if (a === b) continue;
        let dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z;
        let d2 = dx * dx + dy * dy + dz * dz;
        if (d2 > 25000) continue;
        if (d2 < 1) { d2 = 1; dx = Math.random() - 0.5; dy = Math.random() - 0.5; dz = Math.random() - 0.5; }
        const f = (REP / d2) / Math.sqrt(d2);
        a.vx += dx * f; a.vy += dy * f; a.vz += dz * f;
        b.vx -= dx * f; b.vy -= dy * f; b.vz -= dz * f;
      }
    }

    for (const l of this.links) {
      const a = l.s, b = l.t;
      const dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z;
      const d = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
      const f = (d - LEN) * SPR / d;
      a.vx += dx * f; a.vy += dy * f; a.vz += dz * f;
      b.vx -= dx * f; b.vy -= dy * f; b.vz -= dz * f;
    }

    const areas = this.showAreas;
    for (const n of nodes) {
      if (areas) {
        n.vx += (n.lobe.x - n.x) * 0.015;
        n.vy += (n.lobe.y - n.y) * 0.015;
        n.vz += (n.lobe.z - n.z) * 0.015;
      } else {
        n.vx -= n.x * 0.002; n.vy -= n.y * 0.002; n.vz -= n.z * 0.002;
      }
      n.vx *= 0.82; n.vy *= 0.82; n.vz *= 0.82;
      n.x += n.vx * this.alpha; n.y += n.vy * this.alpha; n.z += n.vz * this.alpha;
    }
    this.alpha *= 0.98;
  }

  /** 200 passos de física antes do primeiro frame travavam a thread. */
  private warmup() {
    const N = this.nodes.length;
    const steps = N > 900 ? 70 : 140;
    for (let i = 0; i < steps; i++) this.step();
    this.alpha = Math.max(this.alpha, 0.25); // o resto converge nos frames vivos
  }

  private project(n: { x: number, y: number, z: number, sx: number, sy: number, sc: number, dz: number }) {
    const x = n.x - this.panX, y = n.y - this.panY, z = n.z - this.panZ;
    const cy = Math.cos(this.yaw), sy = Math.sin(this.yaw);
    const x1 = x * cy - z * sy, z1 = x * sy + z * cy;
    const cp = Math.cos(this.pitch), sp = Math.sin(this.pitch);
    const y2 = y * cp - z1 * sp, z2 = y * sp + z1 * cp;
    const sc = (this.dist * this.zoom) / Math.max(120, this.dist + z2);
    n.sx = this.W / 2 + x1 * sc; n.sy = this.H / 2 + y2 * sc; n.sc = sc; n.dz = z2;
  }

  private focusSet(): Set<string> | null {
    const f = this.sel || this.hover;
    const key = f ? f.id : '';
    if (key === this.focusKey) return this.focus;
    this.focusKey = key;
    if (!f) { this.focus = null; return null; }
    const s = new Set([f.id]);
    this.nbr.get(f.id)?.forEach(e => s.add(e.n.id));
    this.focus = s;
    return s;
  }

  /* Sprite de brilho pré-renderizado: substitui 1282 createRadialGradient/frame
   * por 1282 drawImage. As paradas do gradiente escalam linearmente com o alfa,
   * então basta assar em alfa=1 e modular com globalAlpha. */
  private glow(ci: number, gray: boolean): HTMLCanvasElement {
    const key = (gray ? 'g' : 'c') + ci;
    let s = this.sprites.get(key);
    if (s) return s;
    const S = 128, cv = document.createElement('canvas');
    cv.width = S; cv.height = S;
    const c = cv.getContext('2d')!;
    let rgb = hex2rgb(this.pal.comunidades[ci]);
    if (gray) {
      const g = Math.round(rgb[0] * 0.299 + rgb[1] * 0.587 + rgb[2] * 0.114);
      rgb = [g, g, g];
    }
    const [r, g2, b] = rgb;
    const grd = c.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, S / 2);
    grd.addColorStop(0, `rgba(${r},${g2},${b},0.5)`);
    grd.addColorStop(0.42, `rgba(${r},${g2},${b},0.11)`);
    grd.addColorStop(1, `rgba(${r},${g2},${b},0)`);
    c.fillStyle = grd;
    c.fillRect(0, 0, S, S);
    this.sprites.set(key, cv);
    return cv;
  }

  private areaSprite(ci: number, gray: boolean): HTMLCanvasElement {
    const key = (gray ? 'ag' : 'ac') + ci;
    let s = this.sprites.get(key);
    if (s) return s;
    const S = 256, cv = document.createElement('canvas');
    cv.width = S; cv.height = S;
    const c = cv.getContext('2d')!;
    let rgb = hex2rgb(this.pal.comunidades[ci]);
    if (gray) {
      const g = Math.round(rgb[0] * 0.299 + rgb[1] * 0.587 + rgb[2] * 0.114);
      rgb = [g, g, g];
    }
    const [r, g2, b] = rgb;
    const grd = c.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, S / 2);
    grd.addColorStop(0, `rgba(${r},${g2},${b},${gray ? 0.06 : 0.1})`);
    grd.addColorStop(0.5, `rgba(${r},${g2},${b},${gray ? 0.02 : 0.03})`);
    grd.addColorStop(1, `rgba(${r},${g2},${b},0)`);
    c.fillStyle = grd;
    c.fillRect(0, 0, S, S);
    this.sprites.set(key, cv);
    return cv;
  }

  private measure(label: string): number {
    let w = this.textW.get(label);
    if (w === undefined) {
      w = this.ctx.measureText(label).width;
      if (this.textW.size > 4000) this.textW.clear();
      this.textW.set(label, w);
    }
    return w;
  }

  private targetFps(): number {
    if (this.drag) return 60;
    if (this._backgroundMode) return 20;   // decorativo, atrás do chat
    return this.reduceMotion ? 15 : 40;
  }

  private loop = (ts: number) => {
    if (!this.running) return;
    this.raf = requestAnimationFrame(this.loop);
    const interval = 1000 / this.targetFps();
    if (this.lastTs && ts - this.lastTs < interval - 1) return;
    const dt = this.lastTs ? Math.min(0.1, (ts - this.lastTs) / 1000) : 0.016;
    this.lastTs = ts;
    this.draw(dt);
  };

  private draw(dt: number) {
    this.t += dt;
    if (this.spin && !this.drag && !this.reduceMotion) this.yaw += 0.1 * dt;
    this.panX += (this.tgX - this.panX) * 0.08;
    this.panY += (this.tgY - this.panY) * 0.08;
    this.panZ += (this.tgZ - this.panZ) * 0.08;

    this.step();

    const W = this.W, H = this.H, ctx = this.ctx, pal = this.pal;
    const bg = this._backgroundMode;

    // Culling: fora da tela (com margem) não entra em nenhum laço de desenho.
    const MX = W * 0.25 + 80, MY = H * 0.25 + 80;
    const order = this.order;
    let cnt = 0;
    for (const n of this.nodes) {
      this.project(n);
      n.vis = this.isVisible(n)
        && n.sx > -MX && n.sx < W + MX
        && n.sy > -MY && n.sy < H + MY;
      if (n.vis) order[cnt++] = n;
    }
    order.length = cnt;
    order.sort((a, b) => b.dz - a.dz);

    ctx.clearRect(0, 0, W, H);

    if (!bg) {
      if (!this.bgGrad) {
        const g = ctx.createRadialGradient(W / 2, H * 0.48, 0, W / 2, H * 0.48, Math.max(W, H) * 0.62);
        g.addColorStop(0, pal.fundo[0]); g.addColorStop(0.55, pal.fundo[1]); g.addColorStop(1, pal.fundo[2]);
        this.bgGrad = g;
      }
      ctx.fillStyle = this.bgGrad;
      ctx.fillRect(0, 0, W, H);
    }

    ctx.save();
    ctx.translate(W / 2, H * 0.48);
    ctx.lineWidth = 1;
    for (let i = 0; i < 3; i++) {
      const rr = (230 + i * 95) * this.zoom;
      ctx.beginPath();
      ctx.ellipse(0, 0, rr, rr * 0.30, Math.sin(this.t * 0.13 + i) * 0.09, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(${pal.anel},${0.08 - i * 0.02})`;
      ctx.stroke();
    }
    ctx.beginPath();
    ctx.arc(0, 0, 332 * this.zoom, -this.t * 0.17 + 3, -this.t * 0.17 + 3.7);
    ctx.strokeStyle = `rgba(${pal.anel},.2)`;
    ctx.stroke();
    ctx.restore();

    if (this.showAreas) this.drawAreas();

    const fset = this.focusSet();
    if (this.showEdges) this.drawEdges(fset);
    this.drawNodes(order, fset);
    if (!bg) this.drawLabels(order, fset);
  }

  private drawAreas() {
    const ctx = this.ctx, gray = this._backgroundMode;
    const probe = { x: 0, y: 0, z: 0, sx: 0, sy: 0, sc: 0, dz: 0 };
    const list: { sx: number, sy: number, sc: number, dz: number, i: number, n: string }[] = [];

    for (let i = 0; i < this.lobes.length; i++) {
      const l = this.lobes[i];
      // Só ignora se for (0,0,0) estrito E não tiver o nome de um dos núcleos principais conhecidos
      if (l.x === 0 && l.y === 0 && l.z === 0 && !["Agents", "Intelligence (LLM)", "Shared"].includes(l.n) && this.lobes === LOBES) continue;
      
      probe.x = l.x; probe.y = l.y; probe.z = l.z;
      this.project(probe);
      if (probe.sc <= 0.05) continue;
      const r = 320 * probe.sc;
      if (probe.sx + r < 0 || probe.sx - r > this.W || probe.sy + r < 0 || probe.sy - r > this.H) continue;
      list.push({ sx: probe.sx, sy: probe.sy, sc: probe.sc, dz: probe.dz, i, n: l.n });
    }
    list.sort((a, b) => b.dz - a.dz);

    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (const l of list) {
      const r = 320 * l.sc;
      const ci = l.i % this.pal.comunidades.length;
      ctx.drawImage(this.areaSprite(ci, gray), l.sx - r, l.sy - r, r * 2, r * 2);
      ctx.font = `bold ${Math.max(12, 18 * l.sc)}px Consolas,Menlo,monospace`;
      ctx.fillStyle = gray ? `rgba(${this.pal.rotuloAreaCinza},0.4)` : `rgba(${this.palRgb[ci]},0.85)`;
      ctx.fillText(l.n, l.sx, l.sy - r * 0.1);
    }
  }

  /* Antes: 2740 beginPath/stroke por frame. Agora as arestas são agrupadas por
   * (tipo, alfa quantizado, espessura quantizada) e saem em ~10-30 strokes. */
  private drawEdges(fset: Set<string> | null) {
    const ctx = this.ctx, pal = this.pal, bg = this._backgroundMode;
    const buckets = this.bucket, used = this.bucketUsed;
    used.length = 0;

    for (const l of this.links) {
      const a = l.s, b = l.t;
      if (!a.vis && !b.vis) continue;

      const activeLink = a.act || b.act;
      let al: number, lineWidth: number;
      let kind: number;

      if (bg) {
        if (activeLink) { al = 0.8; lineWidth = 2.5; }
        else { al = 0.04; lineWidth = 0.75; }
      } else {
        const inF = fset ? (fset.has(a.id) && fset.has(b.id)) : true;
        const dim = (fset && !inF) || (this.matched && !(this.matched.has(a.id) || this.matched.has(b.id)));
        const depth = (a.dz + b.dz) / 2;
        al = 0.16 + 0.3 * (1 - Math.min(1, Math.max(0, (depth + 420) / 840)));
        if (fset && inF) al = 0.92;
        if (dim) al *= 0.13;
        if (activeLink) al = Math.max(al, 0.8);
        lineWidth = (fset && inF ? 1.5 : 0.75) * Math.min(1.5, (a.sc + b.sc) / 2);
      }
      if (al < 0.012) continue;

      if (bg && !activeLink) kind = 3;
      else if (l.confidence === "AMBIGUOUS") kind = 2;
      else if (l.confidence === "INFERRED") kind = 1;
      else kind = 0;

      const idx = kind * (QUANT_A * QUANT_W) + encodeA(al) * QUANT_W + encodeW(lineWidth);
      const arr = buckets[idx];
      if (arr.length === 0) used.push(idx);
      arr.push(l);
    }

    ctx.lineCap = "round";
    for (const idx of used) {
      const arr = buckets[idx];
      const kind = (idx / (QUANT_A * QUANT_W)) | 0;
      const rem = idx % (QUANT_A * QUANT_W);
      const al = decodeA((rem / QUANT_W) | 0);
      const w = decodeW(rem % QUANT_W);

      const rgb = kind === 2 ? pal.arestaAmbigua : kind === 1 ? pal.arestaInferida : kind === 3 ? pal.arestaApagada : pal.aresta;
      ctx.strokeStyle = `rgba(${rgb},${kind === 1 ? al * 0.8 : al})`;
      ctx.lineWidth = w;
      if (kind === 1 || kind === 2) ctx.setLineDash([3, 4]); else ctx.setLineDash([]);

      ctx.beginPath();
      for (const l of arr) {
        ctx.moveTo(l.s.sx, l.s.sy);
        ctx.lineTo(l.t.sx, l.t.sy);
      }
      ctx.stroke();
      arr.length = 0;
    }
    ctx.setLineDash([]);
  }

  private drawNodes(order: GraphNode[], fset: Set<string> | null) {
    const ctx = this.ctx, pal = this.pal, bg = this._backgroundMode;

    for (const n of order) {
      const active = n.act;
      let r = n.r * n.sc * (n.god ? 1.22 : 1) * (n === this.sel ? 1.35 : 1);
      let a: number;

      if (bg) {
        a = active ? 1.0 : 0.06;
        if (active) r *= 1.8;
      } else {
        const inF = fset ? fset.has(n.id) : true;
        const dim = (fset && !inF) || (this.matched && !this.matched.has(n.id));
        a = dim ? 0.13 : (0.42 + 0.58 * Math.min(1, Math.max(0, (420 - n.dz) / 840)));
        if (active) a = Math.max(a, 0.9);
      }
      if (a < 0.02) continue;

      const gray = bg && !active;
      const R = r * 5.5;
      ctx.globalAlpha = a;
      ctx.drawImage(this.glow(n.ci, gray), n.sx - R, n.sy - R, R * 2, R * 2);
      ctx.globalAlpha = 1;

      if (gray) {
        const g = this.grayLevel[n.ci];
        ctx.fillStyle = `rgba(${g},${g},${g},${Math.min(1, a * 1.25)})`;
      } else {
        ctx.fillStyle = pal.comunidades[n.ci];
        ctx.globalAlpha = Math.min(1, a * 1.25);
      }
      ctx.beginPath();
      ctx.arc(n.sx, n.sy, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;

      ctx.fillStyle = gray
        ? `rgba(${pal.nucleoCinza},${a * 0.5})`
        : `rgba(${pal.nucleoNo},${a * 0.85})`;
      ctx.beginPath();
      ctx.arc(n.sx, n.sy, r * 0.42, 0, Math.PI * 2);
      ctx.fill();

      // Cada arco precisa de um moveTo próprio: sem ele o canvas liga o fim de
      // um subcaminho ao início do próximo com um segmento reto.
      if (n.god && a > 0.2 && !bg) {
        ctx.strokeStyle = `rgba(${pal.anelGod},${0.32 + 0.2 * Math.sin(this.t * 1.7 + n.deg)})`;
        ctx.lineWidth = 1;
        const A0 = this.t * 0.9 + n.deg, RR = r * 2.1;
        ctx.beginPath();
        ctx.moveTo(n.sx + Math.cos(A0) * RR, n.sy + Math.sin(A0) * RR);
        ctx.arc(n.sx, n.sy, RR, A0, A0 + 2.1);
        const A1 = A0 + Math.PI;
        ctx.moveTo(n.sx + Math.cos(A1) * RR, n.sy + Math.sin(A1) * RR);
        ctx.arc(n.sx, n.sy, RR, A1, A1 + 2.1);
        ctx.stroke();
      }

      if (n === this.sel || active) {
        ctx.strokeStyle = active ? pal.comunidades[n.ci] : `rgba(${pal.aresta},.85)`;
        ctx.lineWidth = active ? 2.5 : 1;
        const RR = r + (active ? 8 : 13);
        ctx.beginPath();
        for (let k = 0; k < 4; k++) {
          const A = this.t * (active ? 2.5 : 0.55) + k * Math.PI / 2;
          ctx.moveTo(n.sx + Math.cos(A) * RR, n.sy + Math.sin(A) * RR);
          ctx.arc(n.sx, n.sy, RR, A, A + 0.62);
        }
        ctx.stroke();
      }
    }
  }

  private drawLabels(order: GraphNode[], fset: Set<string> | null) {
    const ctx = this.ctx, pal = this.pal;
    ctx.font = "9.5px Consolas,Menlo,monospace";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";

    let budget = 80; // teto de rótulos por frame: fillText é caro
    for (const n of order) {
      if (budget <= 0) break;
      const inF = fset ? fset.has(n.id) : false;
      const show = n === this.sel || n === this.hover || inF
        || (this.matched && this.matched.has(n.id))
        || (!fset && !this.matched && n.god && n.dz < 160)
        || n.act;
      if (!show) continue;
      budget--;

      const r = n.r * n.sc, tx = n.sx + r + 8, ty = n.sy;
      const w = this.measure(n.label);
      ctx.fillStyle = pal.rotuloFundo;
      ctx.fillRect(tx - 3, ty - 7, w + 6, 14);
      ctx.fillStyle = (n === this.sel || n === this.hover || n.act) ? pal.rotuloTexto : pal.comunidades[n.ci];
      ctx.fillText(n.label, tx, ty);
    }
  }
}
