/**
 * O motor do brain, como um documento HTML autocontido.
 *
 * ## Por que canvas dentro de um WebView, e não componentes nativos
 *
 * O desenho é um grafo de força 3D: algumas centenas de nós e ~900 arestas,
 * reprojetados e repintados a cada quadro. Feito com `react-native-svg` isso
 * seriam ~1.200 nós de view atravessando a ponte 60 vezes por segundo — o
 * caminho mais curto para um app que engasga. Um `<canvas>` 2D pinta tudo dentro
 * do próprio processo do WebView e nada disso cruza a fronteira.
 *
 * O WebView já é dependência obrigatória (o login do Cloudflare Access não
 * existe sem ele), então isto não custa uma biblioteca nova.
 *
 * **Isto não é o código React do PWA.** O que foi reaproveitado é o *conceito*
 * do `NeuralMap`: lobos por diretório, projeção com yaw/pitch, física de mola e
 * repulsão. A implementação é outra, menor, e com um modelo de cor que o PWA não
 * tem (ver abaixo).
 *
 * ## O comportamento pedido para a aba de chat
 *
 * No modo `chat` o cérebro inteiro nasce **cinza**. Cada nó carrega dois valores
 * independentes, e a separação é o ponto todo:
 *
 * - `flash` — o "acender". Vai a 1 quando o nó é tocado e **decai** em ~2s. É o
 *   brilho, o raio maior, o pulso.
 * - `lit` — a cor. Vai a 1 quando o nó é tocado e **não volta atrás**. A cor do
 *   nó é uma interpolação entre o cinza e a cor da comunidade dele, guiada por
 *   `lit`.
 *
 * O resultado é o que foi pedido: além de acender, o cérebro vai *colorindo de
 * volta* conforme a conversa toca partes do código. As arestas seguem a média do
 * `lit` das duas pontas, então os traços coloriram junto, e um traço entre um nó
 * já colorido e um ainda cinza fica no meio do caminho. Vizinhos diretos de um
 * nó tocado recebem `lit` parcial — é isso que faz a cor se espalhar em vez de
 * aparecer como pontos isolados.
 *
 * No modo `full` (aba Brain) vale o desenho colorido de sempre, com toque para
 * girar e pinça para aproximar.
 *
 * ## Nota de estilo
 *
 * O JavaScript abaixo não usa template literals. Ele vive *dentro* de um, e
 * `${` aninhado viraria interpolação do TypeScript. Concatenação com `+` é o que
 * mantém isto legível sem escapar um caractere a cada duas linhas.
 */

export const BRAIN_HTML = `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no" />
<style>
  html, body { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #02060c; }
  canvas { display: block; width: 100%; height: 100%; touch-action: none; }
</style>
</head>
<body>
<canvas id="cv"></canvas>
<script>
(function () {
  'use strict';

  var PAL = ['#00e5ff', '#ffb020', '#4d9dff', '#00ffc8', '#b06bff', '#ff7a3d', '#7dff6f', '#ff5c8a'];

  // Cor e cinza de cada entrada da paleta, pré-computados. O cinza é a
  // luminância perceptual (Rec. 601) e não a média dos canais: a média deixa o
  // amarelo e o ciano com o mesmo tom, e metade da paleta some.
  var COLORS = PAL.map(function (hex) {
    var r = parseInt(hex.slice(1, 3), 16);
    var g = parseInt(hex.slice(3, 5), 16);
    var b = parseInt(hex.slice(5, 7), 16);
    var lum = Math.round(r * 0.299 + g * 0.587 + b * 0.114);
    return { r: r, g: g, b: b, lum: lum };
  });

  // Interpola cinza -> cor. \`t\` = 0 devolve o cinza puro; 1, a cor cheia.
  function tint(ci, t, a) {
    var c = COLORS[ci % COLORS.length];
    var r = Math.round(c.lum + (c.r - c.lum) * t);
    var g = Math.round(c.lum + (c.g - c.lum) * t);
    var b = Math.round(c.lum + (c.b - c.lum) * t);
    return 'rgba(' + r + ',' + g + ',' + b + ',' + a + ')';
  }

  var LOBES = [
    { p: 'apps/web', x: -800, y: 0, z: -800, n: 'WEB' },
    { p: 'apps/api', x: 0, y: 0, z: -800, n: 'API' },
    { p: 'apps/mobile', x: 800, y: 0, z: -800, n: 'MOBILE' },
    { p: 'packages/llm', x: -800, y: 0, z: 0, n: 'LLM' },
    { p: 'packages/agents', x: 0, y: 0, z: 0, n: 'AGENTS' },
    { p: 'packages/memory', x: 800, y: 0, z: 0, n: 'MEMORY' },
    { p: 'packages/shared', x: -800, y: 0, z: 800, n: 'SHARED' },
    { p: 'packages/', x: 0, y: 0, z: 800, n: 'PACKAGES' },
    { p: 'tests', x: 800, y: 0, z: 800, n: 'TESTS' },
    { p: 'infrastructure', x: -1600, y: 0, z: 0, n: 'INFRA' }
  ];
  var CORE_LOBE = { p: '', x: 0, y: 0, z: 0, n: 'CORE' };

  function lobeOf(path) {
    for (var i = 0; i < LOBES.length; i++) {
      if (path.indexOf(LOBES[i].p) >= 0) return LOBES[i];
    }
    return CORE_LOBE;
  }

  var cv = document.getElementById('cv');
  var ctx = cv.getContext('2d');

  var nodes = [];
  var links = [];
  var byId = {};
  var neighbours = {};

  var W = 0, H = 0, DPR = 1;
  var yaw = 0.4, pitch = -0.9, zoom = 0.7, dist = 780;
  var panX = 0, panY = 0;
  var alpha = 0;
  var t = 0;
  var chatMode = true;
  var running = false;

  function resize() {
    DPR = Math.min(window.devicePixelRatio || 1, 2);
    W = cv.clientWidth || window.innerWidth;
    H = cv.clientHeight || window.innerHeight;
    cv.width = Math.max(1, Math.round(W * DPR));
    cv.height = Math.max(1, Math.round(H * DPR));
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }
  window.addEventListener('resize', resize);
  resize();

  function setGraph(graph) {
    var rawNodes = (graph && graph.nodes) || [];
    var rawLinks = (graph && graph.links) || [];

    nodes = [];
    byId = {};
    neighbours = {};

    for (var i = 0; i < rawNodes.length; i++) {
      var raw = rawNodes[i];
      var lobe = lobeOf(raw.source_file || '');
      var node = {
        id: raw.id,
        label: raw.label || raw.id,
        file: (raw.source_file || '').replace(/\\\\/g, '/'),
        ci: (raw.community | 0) % COLORS.length,
        lobe: lobe,
        x: 0, y: 0, z: 0,
        vx: 0, vy: 0, vz: 0,
        sx: 0, sy: 0, sc: 1, dz: 0,
        deg: 0, r: 3,
        lit: 0, flash: 0
      };
      nodes.push(node);
      byId[node.id] = node;
      neighbours[node.id] = [];
    }

    links = [];
    for (var j = 0; j < rawLinks.length; j++) {
      var a = byId[rawLinks[j].source];
      var b = byId[rawLinks[j].target];
      if (!a || !b || a === b) continue;
      var link = { a: a, b: b, conf: rawLinks[j].confidence || '' };
      links.push(link);
      a.deg++; b.deg++;
      neighbours[a.id].push(b);
      neighbours[b.id].push(a);
    }

    // Posição inicial em espiral de Fibonacci dentro do lobo: distribui sem
    // aglomerar no centro, que é o que deixa a física gastar os primeiros
    // segundos só desempilhando nós.
    var N = Math.max(2, nodes.length);
    var GA = Math.PI * (3 - Math.sqrt(5));
    for (var k = 0; k < nodes.length; k++) {
      var n = nodes[k];
      n.r = 2.2 + Math.sqrt(n.deg) * 2.0;
      var yy = 1 - (k / (N - 1)) * 2;
      var rr = Math.sqrt(Math.max(0, 1 - yy * yy));
      var th = GA * k;
      var R = 140 + Math.random() * 25;
      n.x = Math.cos(th) * rr * R + n.lobe.x;
      n.y = yy * R + n.lobe.y;
      n.z = Math.sin(th) * rr * R + n.lobe.z;
    }

    // Aquecimento sem desenhar: chegar já assentado evita a explosão inicial.
    alpha = 1;
    for (var w = 0; w < 140; w++) step();
    alpha = 0.35;

    if (!running) {
      running = true;
      requestAnimationFrame(draw);
    }
  }

  function step() {
    if (alpha < 0.004) return;
    var REP = 1100, SPR = 0.02, LEN = 58;
    var n = nodes.length;
    if (!n) return;

    // Repulsão amostrada: 12 pares por nó em vez de N. O erro por quadro é
    // ruído; ao longo de dezenas de quadros a média converge para o mesmo campo,
    // por uma fração do custo — que é o que torna isto viável num celular.
    for (var i = 0; i < n; i++) {
      var a = nodes[i];
      for (var s = 0; s < 12; s++) {
        var b = nodes[(i + 1 + ((Math.random() * (n - 1)) | 0)) % n];
        if (a === b) continue;
        var dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z;
        var d2 = dx * dx + dy * dy + dz * dz;
        if (d2 > 25000) continue;
        if (d2 < 1) { d2 = 1; dx = Math.random() - 0.5; dy = Math.random() - 0.5; dz = Math.random() - 0.5; }
        var f = (REP / d2) / Math.sqrt(d2);
        a.vx += dx * f; a.vy += dy * f; a.vz += dz * f;
        b.vx -= dx * f; b.vy -= dy * f; b.vz -= dz * f;
      }
    }

    for (var l = 0; l < links.length; l++) {
      var la = links[l].a, lb = links[l].b;
      var ex = lb.x - la.x, ey = lb.y - la.y, ez = lb.z - la.z;
      var ed = Math.sqrt(ex * ex + ey * ey + ez * ez) || 1;
      var ef = (ed - LEN) * SPR / ed;
      la.vx += ex * ef; la.vy += ey * ef; la.vz += ez * ef;
      lb.vx -= ex * ef; lb.vy -= ey * ef; lb.vz -= ez * ef;
    }

    for (var m = 0; m < n; m++) {
      var p = nodes[m];
      p.vx += (p.lobe.x - p.x) * 0.015;
      p.vy += (p.lobe.y - p.y) * 0.015;
      p.vz += (p.lobe.z - p.z) * 0.015;
      p.vx *= 0.82; p.vy *= 0.82; p.vz *= 0.82;
      p.x += p.vx * alpha; p.y += p.vy * alpha; p.z += p.vz * alpha;
    }
    alpha *= 0.985;
  }

  function project(p) {
    var x = p.x - panX, y = p.y - panY, z = p.z;
    var cy = Math.cos(yaw), sy = Math.sin(yaw);
    var x1 = x * cy - z * sy, z1 = x * sy + z * cy;
    var cp = Math.cos(pitch), sp = Math.sin(pitch);
    var y2 = y * cp - z1 * sp, z2 = y * sp + z1 * cp;
    var sc = (dist * zoom) / Math.max(120, dist + z2);
    p.sx = W / 2 + x1 * sc;
    p.sy = H / 2 + y2 * sc;
    p.sc = sc;
    p.dz = z2;
  }

  function draw() {
    t += 0.016;
    yaw += chatMode ? 0.0011 : (dragging ? 0 : 0.0016);

    step();
    for (var i = 0; i < nodes.length; i++) project(nodes[i]);

    ctx.clearRect(0, 0, W, H);

    var bg = ctx.createRadialGradient(W / 2, H * 0.48, 0, W / 2, H * 0.48, Math.max(W, H) * 0.62);
    bg.addColorStop(0, '#061722');
    bg.addColorStop(0.55, '#030b13');
    bg.addColorStop(1, '#02060c');
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, W, H);

    // Anéis de HUD.
    ctx.save();
    ctx.translate(W / 2, H * 0.48);
    for (var ring = 0; ring < 3; ring++) {
      var rr = (150 + ring * 70) * zoom;
      ctx.beginPath();
      ctx.ellipse(0, 0, rr, rr * 0.3, Math.sin(t * 0.13 + ring) * 0.09, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(55,224,255,' + (0.07 - ring * 0.02).toFixed(3) + ')';
      ctx.lineWidth = 1;
      ctx.stroke();
    }
    ctx.restore();

    // Halos dos lobos.
    var probe = { x: 0, y: 0, z: 0, sx: 0, sy: 0, sc: 0, dz: 0 };
    var halos = [];
    for (var li = 0; li < LOBES.length; li++) {
      probe.x = LOBES[li].x; probe.y = LOBES[li].y; probe.z = LOBES[li].z;
      project(probe);
      if (probe.sc > 0.05) {
        halos.push({ i: li, n: LOBES[li].n, sx: probe.sx, sy: probe.sy, sc: probe.sc, dz: probe.dz });
      }
    }
    halos.sort(function (p, q) { return q.dz - p.dz; });
    for (var hi = 0; hi < halos.length; hi++) {
      var halo = halos[hi];
      var hr = 300 * halo.sc;
      // O halo acompanha o modo: cinza na aba de chat, colorido na aba Brain.
      var hc = chatMode ? 0 : 1;
      var rg = ctx.createRadialGradient(halo.sx, halo.sy, 0, halo.sx, halo.sy, hr);
      rg.addColorStop(0, tint(halo.i, hc, 0.07));
      rg.addColorStop(0.5, tint(halo.i, hc, 0.025));
      rg.addColorStop(1, tint(halo.i, hc, 0));
      ctx.fillStyle = rg;
      ctx.beginPath();
      ctx.arc(halo.sx, halo.sy, hr, 0, Math.PI * 2);
      ctx.fill();
      ctx.font = 'bold ' + Math.max(9, Math.round(13 * halo.sc)) + 'px Menlo,Consolas,monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = tint(halo.i, hc, chatMode ? 0.3 : 0.7);
      ctx.fillText(halo.n, halo.sx, halo.sy - hr * 0.12);
    }

    // --- Arestas ---------------------------------------------------------- //
    ctx.lineCap = 'round';
    for (var e = 0; e < links.length; e++) {
      var link = links[e];
      var na = link.a, nb = link.b;
      // Média do \`lit\` das duas pontas: é o que faz um traço entre um nó já
      // colorido e um ainda cinza ficar no meio do caminho, em vez de saltar.
      var lit = (na.lit + nb.lit) / 2;
      var flash = Math.max(na.flash, nb.flash);

      var a, width;
      if (chatMode) {
        a = 0.045 + lit * 0.32 + flash * 0.45;
        width = 0.7 + flash * 1.9 + lit * 0.5;
      } else {
        var depth = (na.dz + nb.dz) / 2;
        a = 0.16 + 0.3 * (1 - Math.min(1, Math.max(0, (depth + 420) / 840)));
        a = Math.max(a, flash * 0.85);
        width = 0.75 + flash * 1.6;
      }

      var amb = link.conf === 'AMBIGUOUS';
      var inf = link.conf === 'INFERRED';
      if (chatMode) {
        // Cinza -> cor da confiança. O mesmo código de cor do PWA (vermelho para
        // ambíguo, âmbar para inferido, ciano para direto), só que emergindo do
        // cinza conforme as pontas coloriram.
        var target = amb ? [255, 84, 112] : inf ? [255, 176, 32] : [55, 224, 255];
        var base = Math.round(target[0] * 0.299 + target[1] * 0.587 + target[2] * 0.114);
        var lr = Math.round(base + (target[0] - base) * lit);
        var lg = Math.round(base + (target[1] - base) * lit);
        var lb = Math.round(base + (target[2] - base) * lit);
        ctx.strokeStyle = 'rgba(' + lr + ',' + lg + ',' + lb + ',' + a.toFixed(3) + ')';
      } else {
        ctx.strokeStyle = amb
          ? 'rgba(255,84,112,' + a.toFixed(3) + ')'
          : inf ? 'rgba(255,176,32,' + (a * 0.8).toFixed(3) + ')'
            : 'rgba(55,224,255,' + a.toFixed(3) + ')';
      }
      ctx.lineWidth = width;
      if (inf || amb) ctx.setLineDash([3, 4]); else ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(na.sx, na.sy);
      ctx.lineTo(nb.sx, nb.sy);
      ctx.stroke();
    }
    ctx.setLineDash([]);

    // --- Nós -------------------------------------------------------------- //
    var order = nodes.slice().sort(function (p, q) { return q.dz - p.dz; });
    for (var o = 0; o < order.length; o++) {
      var nd = order[o];
      var r = nd.r * nd.sc;
      var a2;

      if (chatMode) {
        // Base quase apagada; \`lit\` traz presença permanente e \`flash\` dá o
        // pico do momento em que a tool tocou o arquivo.
        a2 = 0.09 + nd.lit * 0.55 + nd.flash * 0.36;
        r *= 1 + nd.flash * 0.9;
      } else {
        a2 = 0.42 + 0.58 * Math.min(1, Math.max(0, (420 - nd.dz) / 840));
        a2 = Math.max(a2, nd.flash * 0.95);
        r *= 1 + nd.flash * 0.7;
      }
      if (a2 <= 0.02) continue;

      var tone = chatMode ? nd.lit : 1;

      var glow = ctx.createRadialGradient(nd.sx, nd.sy, 0, nd.sx, nd.sy, r * 5);
      glow.addColorStop(0, tint(nd.ci, tone, a2 * 0.45));
      glow.addColorStop(0.45, tint(nd.ci, tone, a2 * 0.1));
      glow.addColorStop(1, tint(nd.ci, tone, 0));
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(nd.sx, nd.sy, r * 5, 0, Math.PI * 2);
      ctx.fill();

      ctx.fillStyle = tint(nd.ci, tone, Math.min(1, a2 * 1.25));
      ctx.beginPath();
      ctx.arc(nd.sx, nd.sy, r, 0, Math.PI * 2);
      ctx.fill();

      // Miolo claro. Em cinza ele também é cinza, senão o núcleo branco daria a
      // impressão de nó aceso onde não há nenhum.
      var core = chatMode ? Math.round(160 + 75 * nd.lit) : 235;
      ctx.fillStyle = 'rgba(' + core + ',' + Math.min(255, core + 18) + ',' + Math.min(255, core + 20) + ',' + (a2 * 0.8).toFixed(3) + ')';
      ctx.beginPath();
      ctx.arc(nd.sx, nd.sy, r * 0.42, 0, Math.PI * 2);
      ctx.fill();

      // Anel pulsante enquanto o flash dura.
      if (nd.flash > 0.05) {
        ctx.strokeStyle = tint(nd.ci, 1, nd.flash * 0.9);
        ctx.lineWidth = 1.6;
        var R = r + 7;
        for (var q = 0; q < 4; q++) {
          var A = t * 2.5 + q * Math.PI / 2;
          ctx.beginPath();
          ctx.arc(nd.sx, nd.sy, R, A, A + 0.62);
          ctx.stroke();
        }
      }
    }

    // Rótulo só de quem está aceso agora — no celular não cabe mais que isso.
    ctx.font = '9px Menlo,Consolas,monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    for (var lb2 = 0; lb2 < order.length; lb2++) {
      var ln = order[lb2];
      if (ln.flash < 0.25) continue;
      var tx = ln.sx + ln.r * ln.sc + 7;
      var ty = ln.sy;
      var wdt = ctx.measureText(ln.label).width;
      ctx.fillStyle = 'rgba(2,8,14,0.72)';
      ctx.fillRect(tx - 3, ty - 7, wdt + 6, 14);
      ctx.fillStyle = tint(ln.ci, 1, Math.min(1, ln.flash + 0.3));
      ctx.fillText(ln.label, tx, ty);
    }

    // \`flash\` decai; \`lit\` NÃO. É essa assimetria que faz o cérebro ir
    // colorindo de volta em vez de voltar ao cinza depois de cada tool.
    for (var d = 0; d < nodes.length; d++) {
      if (nodes[d].flash > 0.001) nodes[d].flash *= 0.968; else nodes[d].flash = 0;
    }

    requestAnimationFrame(draw);
  }

  /**
   * Casamento fuzzy entre o caminho vindo do \`tool_call\` e o \`source_file\` do
   * nó. Os dois lados chegam em formatos diferentes (absoluto do container,
   * relativo do repositório, com barra invertida no Windows), então a
   * comparação é por contenção nos dois sentidos depois de normalizar a barra.
   */
  function matches(file, path) {
    if (!file || !path) return false;
    return path.indexOf(file) >= 0 || file.indexOf(path) >= 0;
  }

  function activate(paths) {
    if (!paths || !paths.length) return;
    var normalized = [];
    for (var i = 0; i < paths.length; i++) {
      normalized.push(String(paths[i]).replace(/\\\\/g, '/'));
    }

    for (var n = 0; n < nodes.length; n++) {
      var node = nodes[n];
      var hit = false;
      for (var p = 0; p < normalized.length; p++) {
        if (matches(node.file, normalized[p])) { hit = true; break; }
      }
      if (!hit) continue;

      node.lit = 1;
      node.flash = 1;
      // Vizinhos ganham cor parcial: é o que faz a cor se ESPALHAR pelo grafo em
      // vez de aparecer como pontos soltos, e é o que dá cor às arestas que
      // saem do nó tocado.
      var nb = neighbours[node.id] || [];
      for (var k = 0; k < nb.length; k++) {
        nb[k].lit = Math.max(nb[k].lit, 0.5);
        nb[k].flash = Math.max(nb[k].flash, 0.55);
      }
    }
    alpha = Math.max(alpha, 0.12);
  }

  /** Volta tudo ao cinza. Usado quando começa uma conversa nova. */
  function reset() {
    for (var i = 0; i < nodes.length; i++) {
      nodes[i].lit = 0;
      nodes[i].flash = 0;
    }
  }

  function setMode(mode) {
    var next = mode !== 'full';
    if (next === chatMode) return;
    chatMode = next;
    // A aba de chat olha o cérebro de cima e de longe (ele é fundo); a aba Brain
    // olha de frente e de perto (ele é o assunto).
    pitch = chatMode ? -0.9 : -0.22;
    zoom = chatMode ? 0.7 : 1;
    alpha = Math.max(alpha, 0.1);
  }

  // --- Toque (só faz diferença no modo \`full\`; no chat a view nativa não
  // entrega eventos) ------------------------------------------------------- //
  var dragging = false, lastX = 0, lastY = 0, pinchStart = 0, zoomStart = 1;

  cv.addEventListener('touchstart', function (ev) {
    if (ev.touches.length === 1) {
      dragging = true;
      lastX = ev.touches[0].clientX;
      lastY = ev.touches[0].clientY;
    } else if (ev.touches.length === 2) {
      dragging = false;
      pinchStart = Math.hypot(
        ev.touches[0].clientX - ev.touches[1].clientX,
        ev.touches[0].clientY - ev.touches[1].clientY
      );
      zoomStart = zoom;
    }
  }, { passive: true });

  cv.addEventListener('touchmove', function (ev) {
    if (ev.touches.length === 2 && pinchStart > 0) {
      var d = Math.hypot(
        ev.touches[0].clientX - ev.touches[1].clientX,
        ev.touches[0].clientY - ev.touches[1].clientY
      );
      zoom = Math.max(0.25, Math.min(4, zoomStart * (d / pinchStart)));
      return;
    }
    if (!dragging || ev.touches.length !== 1) return;
    var x = ev.touches[0].clientX, y = ev.touches[0].clientY;
    yaw += (x - lastX) * 0.006;
    pitch += (y - lastY) * 0.006;
    pitch = Math.max(-1.45, Math.min(1.45, pitch));
    lastX = x; lastY = y;
  }, { passive: true });

  cv.addEventListener('touchend', function () {
    dragging = false;
    pinchStart = 0;
  }, { passive: true });

  // Superfície que o lado nativo chama por \`injectJavaScript\`. Escolhido em vez
  // de \`postMessage\`: o evento de \`postMessage\` chega em \`document\` no Android e
  // em \`window\` no iOS, e depender dessa diferença é uma classe de bug que não
  // precisa existir. \`injectJavaScript\` simplesmente avalia a chamada.
  window.__brain = {
    setGraph: setGraph,
    activate: activate,
    reset: reset,
    setMode: setMode
  };

  // Avisa o lado nativo que a superfície existe. Antes disto, qualquer
  // \`injectJavaScript\` cairia num \`window.__brain\` indefinido.
  if (window.ReactNativeWebView) {
    window.ReactNativeWebView.postMessage(JSON.stringify({ type: 'ready' }));
  }
})();
</script>
</body>
</html>
`;
