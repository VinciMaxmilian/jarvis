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

/* ---------------------------------------------------------------- *
 * Paletas — a clara é a mesma família de matizes, só que rebaixada
 * em luminosidade para sobreviver ao fundo neumórfico.
 * ---------------------------------------------------------------- */
const PAL_DARK = ["#00e5ff","#ffb020","#4d9dff","#00ffc8","#b06bff","#ff7a3d","#7dff6f","#ff5c8a"];
const PAL_LIGHT = ["#0088a8","#a86a00","#2f66cc","#00806a","#6f3fc0","#c2480f","#3f8f28","#c01a54"];

const hex2rgb = (h: string): [number, number, number] => [
  parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16),
];

const THEME = {
  light: {
    pal: PAL_LIGHT,
    bg: ["#f4f6fa", "#e8ebf2", "#dde1ea"],
    ring: "18, 70, 110",
    edge: "40, 90, 140",
    inferred: "170, 110, 0",
    ambiguous: "200, 30, 70",
    muted: "120, 130, 145",
    core: "255, 255, 255",
    labelBg: "rgba(255,255,255,.86)",
    labelFg: "#1b2028",
    godRing: "190, 130, 0",
  },
  dark: {
    pal: PAL_DARK,
    bg: ["#061722", "#030b13", "#02060c"],
    ring: "55, 224, 255",
    edge: "55, 224, 255",
    inferred: "255, 176, 32",
    ambiguous: "255, 84, 112",
    muted: "120, 120, 120",
    core: "235, 253, 255",
    labelBg: "rgba(2,8,14,.72)",
    labelFg: "#eafcff",
    godRing: "255, 176, 32",
  },
} as const;

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
let graphPromise: Promise<any> | null = null;
export function loadGraph(url = '/graph.json'): Promise<any> {
  if (!graphPromise) {
    graphPromise = fetch(url).then(r => r.json()).catch(err => {
      graphPromise = null;
      throw err;
    });
  }
  return graphPromise;
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
  private th: typeof THEME[Theme];
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
    this.resize(); // DPR menor no modo fundo
  }

  public onHover?: (n: GraphNode | null, x: number, y: number) => void;
  public onClick?: (n: GraphNode | null) => void;

  public highlightNodes(files: string[]) {
    this.activeFiles = new Set(files);
    this.recomputeActive();
    this.wake();
  }

  constructor(canvas: HTMLCanvasElement, rawData: any, theme: Theme = 'light') {
    this.cv = canvas;
    const context = canvas.getContext('2d', { alpha: true, desynchronized: true });
    if (!context) throw new Error("Could not get 2D context");
    this.ctx = context;

    this.th = THEME[theme];
    this.reduceMotion = typeof matchMedia === 'function'
      && matchMedia('(prefers-reduced-motion: reduce)').matches;

    for (let i = 0; i < BUCKETS; i++) this.bucket.push([]);
    this.grayLevel = this.th.pal.map(h => {
      const [r, g, b] = hex2rgb(h);
      return Math.round(r * 0.299 + g * 0.587 + b * 0.114);
    });
    this.palRgb = this.th.pal.map(h => hex2rgb(h).join(','));

    this.initData(rawData);
    this.setupEvents();

    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(canvas);
    this.resize();

    // Só desenha e gasta CPU quando o canvas está de fato na tela.
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
    this.ac.abort(); // derruba os listeners de canvas e document de uma vez
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
    const getLobe = (path: string) => LOBES.find(l => path.includes(l.p)) || { p: "", x: 0, y: 0, z: 0, n: "Core" };
    const pal = this.th.pal;

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
        const win = sf.replace(/\//g, '\\');
        for (const p of paths) {
          if (p.includes(sf) || p.includes(win) || sf.includes(p)) { hit = true; break; }
        }
      }
      n.act = hit;
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
    let rgb = hex2rgb(this.th.pal[ci]);
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
    let rgb = hex2rgb(this.th.pal[ci]);
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

    const W = this.W, H = this.H, ctx = this.ctx, th = this.th;
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

    if (!this.bgGrad) {
      const g = ctx.createRadialGradient(W / 2, H * 0.48, 0, W / 2, H * 0.48, Math.max(W, H) * 0.62);
      g.addColorStop(0, th.bg[0]); g.addColorStop(0.55, th.bg[1]); g.addColorStop(1, th.bg[2]);
      this.bgGrad = g;
    }
    ctx.fillStyle = this.bgGrad;
    ctx.fillRect(0, 0, W, H);

    ctx.save();
    ctx.translate(W / 2, H * 0.48);
    ctx.lineWidth = 1;
    for (let i = 0; i < 3; i++) {
      const rr = (230 + i * 95) * this.zoom;
      ctx.beginPath();
      ctx.ellipse(0, 0, rr, rr * 0.30, Math.sin(this.t * 0.13 + i) * 0.09, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(${th.ring},${0.08 - i * 0.02})`;
      ctx.stroke();
    }
    ctx.beginPath();
    ctx.arc(0, 0, 332 * this.zoom, -this.t * 0.17 + 3, -this.t * 0.17 + 3.7);
    ctx.strokeStyle = `rgba(${th.ring},.2)`;
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

    for (let i = 0; i < LOBES.length; i++) {
      const l = LOBES[i];
      if (l.x === 0 && l.y === 0 && l.z === 0 && l.n !== "Agents" && l.n !== "Intelligence (LLM)" && l.n !== "Shared") continue;
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
      const ci = l.i % this.th.pal.length;
      ctx.drawImage(this.areaSprite(ci, gray), l.sx - r, l.sy - r, r * 2, r * 2);
      ctx.font = `bold ${Math.max(12, 18 * l.sc)}px Consolas,Menlo,monospace`;
      ctx.fillStyle = gray ? 'rgba(140,140,140,0.4)' : `rgba(${this.palRgb[ci]},0.85)`;
      ctx.fillText(l.n, l.sx, l.sy - r * 0.1);
    }
  }

  /* Antes: 2740 beginPath/stroke por frame. Agora as arestas são agrupadas por
   * (tipo, alfa quantizado, espessura quantizada) e saem em ~10-30 strokes. */
  private drawEdges(fset: Set<string> | null) {
    const ctx = this.ctx, th = this.th, bg = this._backgroundMode;
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

      const rgb = kind === 2 ? th.ambiguous : kind === 1 ? th.inferred : kind === 3 ? th.muted : th.edge;
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
    const ctx = this.ctx, th = this.th, bg = this._backgroundMode;

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
        ctx.fillStyle = th.pal[n.ci];
        ctx.globalAlpha = Math.min(1, a * 1.25);
      }
      ctx.beginPath();
      ctx.arc(n.sx, n.sy, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;

      ctx.fillStyle = gray
        ? `rgba(160,160,160,${a * 0.5})`
        : `rgba(${th.core},${a * 0.85})`;
      ctx.beginPath();
      ctx.arc(n.sx, n.sy, r * 0.42, 0, Math.PI * 2);
      ctx.fill();

      // Cada arco precisa de um moveTo próprio: sem ele o canvas liga o fim de
      // um subcaminho ao início do próximo com um segmento reto.
      if (n.god && a > 0.2 && !bg) {
        ctx.strokeStyle = `rgba(${th.godRing},${0.32 + 0.2 * Math.sin(this.t * 1.7 + n.deg)})`;
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
        ctx.strokeStyle = active ? th.pal[n.ci] : `rgba(${th.edge},.85)`;
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
    const ctx = this.ctx, th = this.th;
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
      ctx.fillStyle = th.labelBg;
      ctx.fillRect(tx - 3, ty - 7, w + 6, 14);
      ctx.fillStyle = (n === this.sel || n === this.hover || n.act) ? th.labelFg : th.pal[n.ci];
      ctx.fillText(n.label, tx, ty);
    }
  }
}
