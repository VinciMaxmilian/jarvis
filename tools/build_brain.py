import json
import subprocess
from pathlib import Path

"""Gera graphify-out/brain.html a partir de graphify-out/graph.json.

Uso (a partir da raiz do repo):  python tools/build_brain.py

O viewer e autocontido (canvas puro, sem CDN) e sobrevive a `graphify update`,
que so reescreve graph.html.
"""

TPL = Path(__file__).resolve().parent / "brain_template.html"
OUT = Path("graphify-out/brain.html")

graph = json.loads(Path("graphify-out/graph.json").read_text(encoding="utf-8"))

labels_path = Path("graphify-out/.graphify_labels.json")
labels = (
    json.loads(labels_path.read_text(encoding="utf-8")) if labels_path.exists() else {}
)

# keep only what the viewer reads — drops ~40% of the payload
KEEP = ("id", "label", "file_type", "source_file", "source_location",
        "community", "rationale")
# graphify carimba o HEAD de ANTES do commit; usa o HEAD real para nao exibir
# um build hash que ja nao corresponde ao conteudo do grafo
try:
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()
except Exception:
    head = graph.get("built_at_commit", "")

slim = {
    "built_at_commit": head,
    "nodes": [
        {k: n[k] for k in KEEP if n.get(k) not in (None, "")} for n in graph["nodes"]
    ],
    "links": [
        {
            k: link[k]
            for k in ("source", "target", "relation", "confidence")
            if link.get(k)
        }
        for link in graph["links"]
    ],
}

html = TPL.read_text(encoding="utf-8")
html = html.replace(
    "/*__DATA__*/{nodes:[],links:[],hyperedges:[]}",
    json.dumps(slim, ensure_ascii=False, separators=(",", ":")),
)
html = html.replace(
    "/*__LABELS__*/{}",
    json.dumps(labels, ensure_ascii=False, separators=(",", ":")),
)

assert "__DATA__" not in html and "__LABELS__" not in html, "placeholder nao substituido"
OUT.write_text(html, encoding="utf-8")
print(
    f"{OUT} -> {OUT.stat().st_size/1024:.1f} KB · "
    f"{len(slim['nodes'])} nos · {len(slim['links'])} arestas"
)
