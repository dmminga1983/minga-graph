"""Core graph data model.

Every edge carries:
  * ``conf``  - EXTRACTED (stated explicitly in the source) or INFERRED
                (resolved by minga-graph, e.g. a call matched by name);
  * ``why``   - a short human explanation of how the edge was obtained;
  * ``at``    - evidence location ``path:line`` so it can be checked by eye.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

EXTRACTED = "EXTRACTED"
INFERRED = "INFERRED"

# Relations that express "A depends on B". Used by impact analysis.
DEPENDENCY_RELS = {"imports", "calls", "inherits", "references", "foreign_key",
                   "depends_on", "uses"}


@dataclass
class Node:
    id: str
    kind: str            # file, module, class, function, method, heading, table, view, package, note
    name: str
    file: str = ""
    line: int = 0
    end_line: int = 0
    doc: str = ""
    community: int = -1

    def to_dict(self) -> Dict[str, Any]:
        d = {"id": self.id, "kind": self.kind, "name": self.name, "community": self.community}
        for k in ("file", "line", "end_line", "doc"):
            v = getattr(self, k)
            if v:
                d[k] = v
        return d


@dataclass
class Edge:
    src: str
    dst: str
    rel: str
    conf: str = EXTRACTED
    why: str = ""
    at: str = ""

    def key(self):
        return (self.src, self.dst, self.rel)

    def to_dict(self) -> Dict[str, Any]:
        d = {"src": self.src, "dst": self.dst, "rel": self.rel, "conf": self.conf}
        if self.why:
            d["why"] = self.why
        if self.at:
            d["at"] = self.at
        return d


@dataclass
class Graph:
    nodes: Dict[str, Node] = field(default_factory=dict)
    edges: Dict[tuple, Edge] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)
    communities: Dict[int, Dict[str, Any]] = field(default_factory=dict)

    # ---- mutation -------------------------------------------------------
    def add_node(self, node: Node) -> Node:
        existing = self.nodes.get(node.id)
        if existing is None:
            self.nodes[node.id] = node
            return node
        # Merge: keep the richer record.
        for attr in ("file", "line", "end_line", "doc"):
            if not getattr(existing, attr) and getattr(node, attr):
                setattr(existing, attr, getattr(node, attr))
        return existing

    def add_edge(self, edge: Edge) -> Optional[Edge]:
        if edge.src == edge.dst:
            return None
        if edge.src not in self.nodes or edge.dst not in self.nodes:
            return None
        k = edge.key()
        old = self.edges.get(k)
        if old is None or (old.conf == INFERRED and edge.conf == EXTRACTED):
            self.edges[k] = edge
            return edge
        return old

    # ---- adjacency -----------------------------------------------------
    def out_edges(self, nid: str) -> List[Edge]:
        return self._index()[0].get(nid, [])

    def in_edges(self, nid: str) -> List[Edge]:
        return self._index()[1].get(nid, [])

    def _index(self):
        sig = (len(self.nodes), len(self.edges))
        if getattr(self, "_idx_sig", None) != sig:
            out: Dict[str, List[Edge]] = {}
            inc: Dict[str, List[Edge]] = {}
            for e in self.edges.values():
                out.setdefault(e.src, []).append(e)
                inc.setdefault(e.dst, []).append(e)
            for lst in list(out.values()) + list(inc.values()):
                lst.sort(key=lambda e: (e.rel, e.src, e.dst))
            self._idx = (out, inc)
            self._idx_sig = sig
        return self._idx

    def degree(self, nid: str, skip_contains: bool = True) -> int:
        n = 0
        for e in self.out_edges(nid) + self.in_edges(nid):
            if skip_contains and e.rel == "contains":
                continue
            n += 1
        return n

    # ---- serialisation -------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph": self.meta,
            "communities": {str(k): v for k, v in sorted(self.communities.items())},
            "nodes": [n.to_dict() for n in sorted(self.nodes.values(), key=lambda n: n.id)],
            "edges": [e.to_dict() for e in sorted(self.edges.values(), key=lambda e: e.key())],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Graph":
        g = cls()
        g.meta = dict(data.get("graph", {}))
        g.communities = {int(k): v for k, v in data.get("communities", {}).items()}
        for nd in data.get("nodes", []):
            g.nodes[nd["id"]] = Node(**{k: nd[k] for k in Node.__dataclass_fields__ if k in nd})
        for ed in data.get("edges", []):
            e = Edge(**{k: ed[k] for k in Edge.__dataclass_fields__ if k in ed})
            g.edges[e.key()] = e
        return g

    def iter_nodes(self, kinds: Optional[Iterable[str]] = None):
        ks = set(kinds) if kinds else None
        for n in self.nodes.values():
            if ks is None or n.kind in ks:
                yield n
