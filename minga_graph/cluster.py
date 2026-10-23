"""Deterministic Louvain community detection + LLM-free labels (pure Python)."""

from __future__ import annotations

import posixpath
from collections import Counter, defaultdict
from typing import Dict, List

from .model import Graph

REL_WEIGHT = {"contains": 1.0, "calls": 2.0, "inherits": 3.0, "imports": 1.5, "uses": 1.5,
              "references": 2.0, "foreign_key": 3.0, "links_to": 1.0, "mentions": 0.5,
              "explains": 1.0, "depends_on": 0.3}


def _one_level(adj: Dict[str, Dict[str, float]], resolution: float):
    nodes = sorted(adj)
    k = {n: sum(adj[n].values()) for n in nodes}
    m2 = sum(k.values())
    comm = {n: n for n in nodes}
    tot = dict(k)
    if m2 == 0:
        return comm, False
    moved_any = False
    for _ in range(30):
        moved = False
        for n in nodes:
            c_old = comm[n]
            w_to: Dict[str, float] = defaultdict(float)
            for nb, w in adj[n].items():
                if nb != n:
                    w_to[comm[nb]] += w
            tot[c_old] -= k[n]
            best, best_gain = c_old, w_to.get(c_old, 0.0) - resolution * tot[c_old] * k[n] / m2
            for c in sorted(w_to):
                gain = w_to[c] - resolution * tot[c] * k[n] / m2
                if gain > best_gain + 1e-12:
                    best, best_gain = c, gain
            tot[best] += k[n]
            comm[n] = best
            if best != c_old:
                moved = moved_any = True
        if not moved:
            break
    return comm, moved_any


def louvain(g: Graph, resolution: float = 1.0) -> Dict[str, int]:
    adj: Dict[str, Dict[str, float]] = {nid: {} for nid in g.nodes}
    for e in g.edges.values():
        w = REL_WEIGHT.get(e.rel, 1.0)
        if g.nodes[e.dst].kind == "package":
            w *= 0.2  # third-party packages should not glue unrelated code together
        adj[e.src][e.dst] = adj[e.src].get(e.dst, 0.0) + w
        adj[e.dst][e.src] = adj[e.dst].get(e.src, 0.0) + w
    member = {n: n for n in adj}  # original node -> current super node
    for _level in range(10):
        comm, moved = _one_level(adj, resolution)
        if not moved:
            break
        member = {n: comm[s] for n, s in member.items()}
        new: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for u, nbrs in adj.items():
            cu = comm[u]
            new[cu]  # ensure node exists
            for v, w in nbrs.items():
                new[cu][comm[v]] += w
        adj = {u: dict(v) for u, v in new.items()}
    groups: Dict[str, List[str]] = defaultdict(list)
    for n, c in member.items():
        groups[c].append(n)
    ordered = sorted(groups.values(), key=lambda ms: (-len(ms), min(ms)))
    return {n: i for i, ms in enumerate(ordered) for n in ms}


def assign(g: Graph, resolution: float = 1.0) -> None:
    part = louvain(g, resolution)
    for nid, c in part.items():
        g.nodes[nid].community = c
    members: Dict[int, List[str]] = defaultdict(list)
    for nid, c in part.items():
        members[c].append(nid)
    g.communities = {}
    name_count = Counter(n.name for n in g.nodes.values())
    for c, ids in members.items():
        g.communities[c] = {"size": len(ids), "label": _label(g, ids, name_count)}


def _label(g: Graph, ids: List[str], name_count: Counter) -> str:
    code = [i for i in ids if g.nodes[i].kind in ("class", "function", "method", "interface", "table", "view", "heading")]
    pool = code or ids
    hub = max(pool, key=lambda i: (g.degree(i), -len(g.nodes[i].name), i))
    dirs = Counter(posixpath.dirname(g.nodes[i].file) for i in ids if g.nodes[i].file)
    hub_name = g.nodes[hub].name
    if g.nodes[hub].kind == "file":
        hub_name = g.nodes[hub].file
    elif name_count[hub_name] > 1 and g.nodes[hub].file:
        hub_name = f"{hub_name} ({posixpath.basename(g.nodes[hub].file)})"
    if dirs:
        d, cnt = dirs.most_common(1)[0]
        if d and cnt >= max(2, len(ids) // 3):
            return f"{hub_name} · {d}/"
    return hub_name
