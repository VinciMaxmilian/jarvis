import { useEffect, useRef, useState, useCallback } from 'react';
import { NeuralEngine, loadGraph, type GraphNode, type Theme } from './Engine';
import { FileExplorer } from './FileExplorer';

interface NeuralMapProps {
  backgroundMode?: boolean;
  activeNodes?: string[];
  theme?: Theme;
}

export function NeuralMap({ backgroundMode = false, activeNodes, theme = 'light' }: NeuralMapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<NeuralEngine | null>(null);
  const [ready, setReady] = useState(false);

  const [showAreas, setShowAreas] = useState(true);
  const [showEdges, setShowEdges] = useState(true);
  const [spin, setSpin] = useState(true);

  const [hiddenPaths, setHiddenPaths] = useState<Set<string>>(new Set());
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [showFileExplorer, setShowFileExplorer] = useState(false);

  // Uma única criação/destruição por montagem. Sem o dispose, o rAF do engine
  // continuava rodando depois de sair da página.
  useEffect(() => {
    let cancelled = false;
    loadGraph()
      .then(json => {
        if (cancelled || !canvasRef.current || engineRef.current) return;
        const engine = new NeuralEngine(canvasRef.current, json, theme);
        engine.onClick = setSelectedNode;
        engine.backgroundMode = backgroundMode;
        engineRef.current = engine;
        setReady(true);
      })
      .catch(err => console.error('Failed to load graph.json', err));

    return () => {
      cancelled = true;
      engineRef.current?.dispose();
      engineRef.current = null;
      setReady(false);
    };
    // theme/backgroundMode iniciais só; mudanças vão pelos efeitos abaixo
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme]);

  useEffect(() => {
    if (engineRef.current) engineRef.current.backgroundMode = backgroundMode;
  }, [backgroundMode, ready]);

  useEffect(() => {
    if (engineRef.current) engineRef.current.highlightNodes(activeNodes ?? []);
  }, [activeNodes, ready]);

  useEffect(() => {
    if (engineRef.current) engineRef.current.setOptions({ showAreas, showEdges, spin });
  }, [showAreas, showEdges, spin, ready]);

  useEffect(() => {
    if (!engineRef.current) return;
    const id = window.setTimeout(() => engineRef.current?.search(searchQuery), 150);
    return () => window.clearTimeout(id);
  }, [searchQuery, ready]);

  const handleTogglePath = useCallback((path: string) => {
    setHiddenPaths(prev => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      if (engineRef.current) {
        engineRef.current.hiddenPaths = next;
        engineRef.current.wake();
      }
      return next;
    });
  }, []);

  const handleIsolatePath = useCallback((path: string) => {
    const engine = engineRef.current;
    if (!engine) return;
    const next = new Set<string>();
    for (const n of engine.nodes) {
      const p = n.source_file || 'unknown';
      if (p !== path) next.add(p);
    }
    setHiddenPaths(next);
    engine.hiddenPaths = next;
    engine.wake();
  }, []);

  const handleRealign = () => engineRef.current?.realign();

  return (
    <div
      className="neural-root"
      style={{
        position: 'relative', width: '100%', height: '100%', overflow: 'hidden',
        background: backgroundMode ? 'transparent' : 'var(--neu-bg)',
      }}
    >
      <canvas
        ref={canvasRef}
        style={{
          width: '100%', height: '100%', display: 'block',
          // sem filter: blur() — um blur de tela cheia recompõe a cada frame
          opacity: backgroundMode ? 0.5 : 1,
          pointerEvents: backgroundMode ? 'none' : 'auto',
        }}
      />

      {!backgroundMode && (
        <div className="neural-hud-controls neu-raised">
          <input
            className="neu-input neural-search"
            placeholder="BUSCAR NÓ..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
          />
          <button className={`neu-chip ${showAreas ? 'is-on' : ''}`} onClick={() => setShowAreas(!showAreas)}>ZONAS</button>
          <button className={`neu-chip ${showEdges ? 'is-on' : ''}`} onClick={() => setShowEdges(!showEdges)}>ARESTAS</button>
          <button className={`neu-chip ${spin ? 'is-on' : ''}`} onClick={() => setSpin(!spin)}>ROTAÇÃO</button>
          <button className="neu-chip" onClick={handleRealign}>REALINHAR</button>
          <button className="neu-chip mobile-only-btn" onClick={() => setShowFileExplorer(!showFileExplorer)}>
            {showFileExplorer ? 'FECHAR' : 'ARQUIVOS'}
          </button>
        </div>
      )}

      {!backgroundMode && ready && (
        <div className={`file-explorer-container ${showFileExplorer ? 'open' : ''}`}>
          <FileExplorer
            nodes={engineRef.current?.nodes ?? []}
            hiddenPaths={hiddenPaths}
            onTogglePath={handleTogglePath}
            onIsolatePath={handleIsolatePath}
          />
        </div>
      )}

      {!backgroundMode && selectedNode && (
        <div className="node-detail-panel neu-raised">
          <button
            className="neu-close"
            onClick={() => { setSelectedNode(null); engineRef.current?.selectNode(null); }}
            aria-label="Fechar"
          >✕</button>
          <h2 className="neu-title">{selectedNode.label}</h2>

          <div style={{ display: 'flex', gap: 6, marginBottom: 14, flexWrap: 'wrap' }}>
            <span className="neu-tag" style={{ color: selectedNode.c }}>
              {(selectedNode.file_type || '?').toUpperCase()}
            </span>
            <span className="neu-tag">{selectedNode.lobe.n}</span>
            {selectedNode.god && <span className="neu-tag is-gold">GOD NODE</span>}
          </div>

          <dl className="neu-kv">
            <div><dt>ORIGEM</dt><dd>{selectedNode.source_file || '—'}</dd></div>
            <div><dt>GRAU</dt><dd>{selectedNode.deg} conexões</dd></div>
            <div><dt>ID</dt><dd>{selectedNode.id}</dd></div>
          </dl>
        </div>
      )}
    </div>
  );
}
