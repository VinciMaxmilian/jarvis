import { useMemo, memo } from 'react';
import type { GraphNode } from './Engine';

interface TreeNode {
  dir: boolean;
  name: string;
  path: string;
  count: number;
  children: Record<string, TreeNode>;
  c?: string; // color
}

interface FileExplorerProps {
  nodes: GraphNode[];
  hiddenPaths: Set<string>;
  onTogglePath: (path: string) => void;
  onIsolatePath: (path: string) => void;
}

export const FileExplorer = memo(function FileExplorer({ nodes, hiddenPaths, onTogglePath, onIsolatePath }: FileExplorerProps) {
  const tree = useMemo(() => {
    const root: Record<string, TreeNode> = {};
    nodes.forEach(n => {
      const path = n.source_file || "unknown";
      const parts = path.split('/');
      let curr = root;
      for (let i = 0; i < parts.length - 1; i++) {
        const p = parts[i];
        if (!curr[p]) curr[p] = { dir: true, name: p, children: {}, count: 0, path: parts.slice(0, i+1).join('/') };
        curr[p].count++;
        curr = curr[p].children;
      }
      const file = parts[parts.length - 1];
      if (!curr[file]) curr[file] = { dir: false, name: file, count: 0, path: path, children: {}, c: n.c };
      curr[file].count++;
    });
    return root;
  }, [nodes]);

  return (
    <div className="neu-raised" style={{
      width: '100%', height: '100%',
      overflowY: 'auto', padding: '14px',
      fontFamily: "var(--font-mono, 'JetBrains Mono', monospace)", fontSize: '11px',
      display: 'flex', flexDirection: 'column'
    }}>
      {/* separador: hairline por token quando existir, fio neumórfico enquanto não */}
      <div style={{
        fontSize: '9px', letterSpacing: '0.14em', color: 'var(--ink-3)',
        marginBottom: 12, paddingBottom: 8,
        borderBottom: '1px solid var(--color-divider, var(--neu-edge-lo))'
      }}>
        ARQUIVOS · clique p/ ocultar · dir p/ isolar
      </div>
      <div style={{ flex: 1 }}>
        <TreeLevel level={tree} hiddenPaths={hiddenPaths} onToggle={onTogglePath} onIsolate={onIsolatePath} depth={0} />
      </div>
    </div>
  );
});

function TreeLevel({ level, hiddenPaths, onToggle, onIsolate, depth }: { level: Record<string, TreeNode>, hiddenPaths: Set<string>, onToggle: (p: string) => void, onIsolate: (p: string) => void, depth: number }) {
  const keys = Object.keys(level).sort((a, b) => {
    if (level[a].dir && !level[b].dir) return -1;
    if (!level[a].dir && level[b].dir) return 1;
    return a.localeCompare(b);
  });

  return (
    <div style={{ marginLeft: depth > 0 ? 12 : 0, paddingLeft: depth > 0 ? 4 : 0, borderLeft: depth > 0 ? '1px solid var(--color-divider, var(--neu-edge-lo))' : 'none' }}>
      {keys.map(k => {
        const node = level[k];
        if (node.dir) {
          return (
            <details key={node.path} open={depth < 1} style={{ marginBottom: 2 }}>
              <summary style={{
                cursor: 'pointer', color: 'var(--ink-2)', userSelect: 'none',
                display: 'flex', justifyContent: 'space-between', marginLeft: -16, listStyle: 'none'
              }}>
                <span style={{ fontWeight: 500, letterSpacing: '0.05em' }}>🗀 {node.name}</span>
                <span style={{ opacity: 0.4, fontSize: '9px' }}>{node.count}</span>
              </summary>
              <TreeLevel level={node.children} hiddenPaths={hiddenPaths} onToggle={onToggle} onIsolate={onIsolate} depth={depth + 1} />
            </details>
          );
        } else {
          const isOff = hiddenPaths.has(node.path);
          let icon = "📄";
          if (node.name.endsWith(".py")) icon = "🐍";
          else if (node.name.endsWith(".ts") || node.name.endsWith(".tsx")) icon = "⚛️";
          else if (node.name.endsWith(".md")) icon = "📓";
          else if (node.name.endsWith(".json")) icon = "🔧";

          return (
            <div
              key={node.path}
              onClick={() => onToggle(node.path)}
              onContextMenu={(e) => { e.preventDefault(); onIsolate(node.path); }}
              style={{
                cursor: 'pointer', color: node.c, display: 'flex', justifyContent: 'space-between',
                padding: '3px 0', borderLeft: '1px solid transparent', marginLeft: 4,
                textDecoration: isOff ? 'line-through' : 'none',
                opacity: isOff ? 0.3 : 1,
                filter: isOff ? 'grayscale(1)' : 'none',
                transition: '0.1s'
              }}
              onMouseEnter={e => { e.currentTarget.style.transform = 'translateX(2px)'; e.currentTarget.style.background = 'var(--color-divider, var(--neu-edge))'; }}
              onMouseLeave={e => { e.currentTarget.style.transform = 'none'; e.currentTarget.style.background = 'transparent'; }}
            >
              <span>{icon} {node.name}</span>
              {node.count > 1 && <span style={{ opacity: 0.4, fontSize: '9px' }}>({node.count} nós)</span>}
            </div>
          );
        }
      })}
    </div>
  );
}
