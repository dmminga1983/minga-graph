"""Graph queries: find, explain, path, question->subgraph, impact, cycles, diff."""

from __future__ import annotations

import re
from collections import deque
from typing import Dict, List, Optional, Set, Tuple

from .model import DEPENDENCY_RELS, Edge, Graph


class Ambiguous(Exception):
    def __init__(self, name: str, candidates: List[str]):
        super().__init__(name)
        self.name = name
        self.candidates = candidates


class NotFound(Exception):
    pass


# ---------------------------------------------------------------- finding
def find(g: Graph, name: str) -> str:
    """Resolve a user-supplied name to exactly one node id."""
    if name in g.nodes:
        return name
    low = name.lower()
    for prefix in ("file:", "sym:", "doc:", "table:", "pkg:"):
        if prefix + name in g.nodes:
            return prefix + name
    exact = [n.id for n in g.nodes.values() if n.name == name]
    if not exact:
        exact = [n.id for n in g.nodes.values() if n.name.lower() == low]
    if not exact:
        # qualified forms: Class.method, path/file.py, path::sym
        exact = [n.id for n in g.nodes.values()
                 if n.id.endswith("::" + name) or n.id.endswith("." + name)
                 or (n.kind == "file" and (n.file == name or n.file.endswith("/" + name)))]
    if not exact:
        raise NotFound(name)
    if len(exact) == 1:
        return exact[0]
    # prefer definitions over files/notes when names collide
    rank = {"class": 0, "interface": 0, "function": 1, "table": 1, "view": 1, "method": 2, "file": 3,
            "heading": 4, "package": 5, "note": 6}
    exact.sort(key=lambda i: (rank.get(g.nodes[i].kind, 9), i))
    best = rank.get(g.nodes[exact[0]].kind, 9)
    top = [i for i in exact if rank.get(g.nodes[i].kind, 9) == best]
    if len(top) == 1:
        return top[0]
    raise Ambiguous(name, exact)


def describe(g: Graph, nid: str) -> str:
    n = g.nodes[nid]
    loc = f"{n.file}:{n.line}" if n.file and n.line else (n.file or "")
    return f"{n.name} [{n.kind}]" + (f" ({loc})" if loc else "")


def fmt_edge(g: Graph, e: Edge, from_id: str) -> str:
    if e.src == from_id:
        arrow, other = "-->", e.dst
    else:
        arrow, other = "<--", e.src
    why = f" · {e.why}" if e.why else ""
    at = f" @ {e.at}" if e.at else ""
    return f"  {arrow} {describe(g, other)} [{e.rel}] [{e.conf}]{why}{at}"


# ---------------------------------------------------------------- explain
def explain(g: Graph, nid: str, limit: int = 60) -> str:
    n = g.nodes[nid]
    comm = g.communities.get(n.community, {})
    out = [f"Node: {n.name}", f"  Kind:      {n.kind}", f"  Id:        {n.id}"]
    if n.file:
        out.append(f"  Source:    {n.file}" + (f" L{n.line}" + (f"-{n.end_line}" if n.end_line and n.end_line != n.line else "") if n.line else ""))
    if n.doc:
        out.append(f"  Doc:       {n.doc}")
    out.append(f"  Community: {n.community}" + (f" ({comm.get('label')})" if comm else ""))
    edges = g.out_edges(nid) + g.in_edges(nid)
    out.append(f"  Degree:    {g.degree(nid)} (+{sum(1 for e in edges if e.rel == 'contains')} contains)")
    out.append("")
    out.append(f"Connections ({len(edges)}):")
    rank = {"calls": 0, "inherits": 0, "imports": 1, "references": 1, "uses": 1, "foreign_key": 0,
            "depends_on": 2, "links_to": 3, "mentions": 4, "explains": 5, "contains": 6}
    edges.sort(key=lambda e: (rank.get(e.rel, 3), e.conf != "EXTRACTED", e.rel, e.src, e.dst))
    for e in edges[:limit]:
        out.append(fmt_edge(g, e, nid))
    if len(edges) > limit:
        out.append(f"  ... {len(edges) - limit} more (use --limit)")
    return "\n".join(out)


# ---------------------------------------------------------------- path
PATH_COST = {"calls": 1.0, "inherits": 1.0, "references": 1.1, "uses": 1.1, "foreign_key": 1.0,
             "imports": 1.4, "links_to": 1.3, "mentions": 1.6, "explains": 1.2, "contains": 1.5,
             "depends_on": 3.0}


def shortest_path(g: Graph, a: str, b: str, skip_contains: bool = False) -> Optional[List[Tuple[str, Optional[Edge]]]]:
    """Undirected weighted shortest path (Dijkstra) preferring semantic edges
    (calls, inherits) over structural ones (contains, imports).
    Returns [(node, edge_used_to_reach_it), ...]."""
    import heapq
    if a == b:
        return [(a, None)]
    dist = {a: 0.0}
    prev: Dict[str, Tuple[str, Edge]] = {}
    heap = [(0.0, a)]
    while heap:
        d, cur = heapq.heappop(heap)
        if d > dist.get(cur, 1e18):
            continue
        if cur == b:
            path = []
            node = b
            while node != a:
                p, pe = prev[node]
                path.append((node, pe))
                node = p
            path.append((a, None))
            return list(reversed(path))
        for e in g.out_edges(cur) + g.in_edges(cur):
            if skip_contains and e.rel == "contains":
                continue
            nxt = e.dst if e.src == cur else e.src
            if g.nodes[nxt].kind == "package" and nxt != b:
                continue  # don't route through third-party hubs
            nd = d + PATH_COST.get(e.rel, 1.2) + (0.15 if e.conf != "EXTRACTED" else 0.0)
            if nd < dist.get(nxt, 1e18) - 1e-9:
                dist[nxt] = nd
                prev[nxt] = (cur, e)
                heapq.heappush(heap, (nd, nxt))
    return None


def fmt_path(g: Graph, path) -> str:
    hops = len(path) - 1
    out = [f"Shortest path ({hops} hop{'s' if hops != 1 else ''}):"]
    line = g.nodes[path[0][0]].name
    for i in range(1, len(path)):
        node, e = path[i]
        prev = path[i - 1][0]
        if e.src == prev:
            line += f" --{e.rel}--> {g.nodes[node].name}"
        else:
            line += f" <--{e.rel}-- {g.nodes[node].name}"
    out.append("  " + line)
    out.append("")
    out.append("Evidence:")
    for i in range(1, len(path)):
        node, e = path[i]
        out.append(f"  {g.nodes[e.src].name} --{e.rel}--> {g.nodes[e.dst].name} [{e.conf}] {e.why} @ {e.at}")
    return "\n".join(out)


# ---------------------------------------------------------------- question
STOP = set("""a an the of to in on for and or is are was were be by with from as at it this that these those
what which who how why where when does do did can could should would into about between connect connects
connected show me find all any there their its my our your
и в во на с со по к ко у о об от до из за для что как где когда почему какой какая какие кто это этот эта
эти тот та те же ли не ни или а но да связан связано связаны связь между покажи найди все всё мне""".split())


def _tokens(text: str) -> List[str]:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    toks = re.findall(r"[\w]+", text.lower(), flags=re.UNICODE)
    out = []
    for t in toks:
        for p in t.split("_"):
            if len(p) >= 2 and p not in STOP:
                out.append(p)
    return out


def _stem(t: str) -> str:
    for suf in ("ations", "ation", "ings", "ing", "ers", "er", "es", "s", "ами", "ями", "ов", "ев", "ам", "ям", "ах", "ях", "ой", "ей", "ий", "ый", "ая", "ое", "ые", "ы", "и", "а", "я", "у", "ю", "е", "о"):
        if len(t) > len(suf) + 2 and t.endswith(suf):
            return t[: -len(suf)]
    return t


# Russian programming vocabulary -> English identifiers, so Russian questions find English code.
# Keys are word prefixes (matched with startswith on the lower-cased token).
RU_EN = {
    "граф": "graph", "кластер": "cluster community louvain", "сообществ": "community cluster",
    "строит": "build", "сборк": "build", "собира": "build", "постро": "build",
    "баз": "db database", "данн": "data", "авториз": "auth login", "аутентиф": "auth login",
    "вход": "login signin", "логин": "login", "выход": "logout", "регистр": "register signup",
    "пользоват": "user", "юзер": "user", "запрос": "query request", "ответ": "response reply",
    "ошибк": "error exception", "исключ": "exception error", "тест": "test", "конфиг": "config settings",
    "настройк": "settings config", "файл": "file", "отчёт": "report", "отчет": "report",
    "секрет": "secret", "ключ": "key token", "токен": "token", "пароль": "password", "путь": "path",
    "поиск": "search find", "найт": "find search", "импорт": "import", "вызов": "call", "вызыва": "call",
    "класс": "class", "функци": "function", "метод": "method", "сервер": "server", "клиент": "client",
    "оплат": "payment pay", "плат": "payment", "заказ": "order", "товар": "product item", "корзин": "cart",
    "бот": "bot", "сообщен": "message", "кэш": "cache", "кеш": "cache", "почт": "mail email",
    "уведомл": "notification notify", "маршрут": "route router", "модел": "model", "таблиц": "table",
    "схем": "schema", "парс": "parse parser", "разбор": "parse parser", "извлеч": "extract",
    "экспорт": "export", "загруз": "load upload", "сохран": "save store", "удал": "delete remove",
    "созда": "create", "обнов": "update", "провер": "check validate verify", "валид": "validate",
    "шаблон": "template", "страниц": "page", "компонент": "component", "кнопк": "button",
    "форм": "form", "api": "api", "апи": "api", "хук": "hook", "событ": "event", "очеред": "queue",
    "задач": "task job", "планиров": "schedule scheduler", "лог": "log logger", "журнал": "log",
    "безопасн": "security", "права": "permission role", "рол": "role", "сесси": "session",
    "кластериз": "cluster", "визуал": "html render view", "отрисов": "render draw", "html": "html",
    "сканир": "scan walk", "обход": "walk", "игнор": "ignore", "связ": "edge link", "узел": "node",
    "узл": "node", "резолв": "resolve", "разреш": "resolve", "зависим": "dependency depends impact",
    "влиян": "impact", "цикл": "cycle", "сравн": "diff compare", "изменен": "diff change",
}


def _expand_ru(tokens: List[str]) -> List[str]:
    out = []
    for t in tokens:
        out.append(t)
        if re.search(r"[а-яё]", t):
            for k, v in RU_EN.items():
                if t.startswith(k):
                    out.extend(v.split())
                    break
    return out


def score_nodes(g: Graph, question: str) -> List[Tuple[float, str]]:
    qt = [_stem(t) for t in _expand_ru(_tokens(question))]
    if not qt:
        return []
    scored = []
    for n in g.nodes.values():
        if n.kind == "package":
            continue
        name_t = {_stem(t) for t in _tokens(n.name)}
        file_t = {_stem(t) for t in _tokens(n.file)}
        doc_t = {_stem(t) for t in _tokens(n.doc)} if n.doc else set()
        s = 0.0
        for t in qt:
            if t in name_t:
                s += 3.0
            elif any(x.startswith(t) or t.startswith(x) for x in name_t if len(x) >= 3):
                s += 1.5
            if t in file_t:
                s += 0.7
            if t in doc_t:
                s += 1.0
        if s:
            if n.kind in ("class", "function", "method", "interface", "table"):
                s += 0.5
            s += min(g.degree(n.id), 30) / 60.0
            scored.append((s, n.id))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored


def question_subgraph(g: Graph, question: str, budget: int = 40) -> Tuple[List[str], List[Edge]]:
    scored = score_nodes(g, question)
    if not scored:
        return [], []
    top_score = scored[0][0]
    seeds = [nid for s, nid in scored[:8] if s >= top_score * 0.45]
    keep: List[str] = list(seeds)
    kept: Set[str] = set(seeds)
    # connect seeds to each other first (the "what connects A to B" case)
    for i in range(len(seeds)):
        for j in range(i + 1, min(len(seeds), 5)):
            p = shortest_path(g, seeds[i], seeds[j], skip_contains=True)
            if p and len(p) <= 5:
                for node, _ in p:
                    if node not in kept and len(keep) < budget:
                        keep.append(node)
                        kept.add(node)
    # then their strongest direct neighbours
    for s in seeds:
        nbrs = sorted(g.out_edges(s) + g.in_edges(s), key=lambda e: (e.rel == "contains", e.conf != "EXTRACTED"))
        for e in nbrs:
            other = e.dst if e.src == s else e.src
            if other not in kept and len(keep) < budget and g.nodes[other].kind != "package":
                keep.append(other)
                kept.add(other)
    edges = [e for e in g.edges.values() if e.src in kept and e.dst in kept]
    edges.sort(key=lambda e: e.key())
    return keep, edges


def fmt_subgraph(g: Graph, question: str, nodes: List[str], edges: List[Edge]) -> str:
    if not nodes:
        return f"No nodes match: {question!r}. Try a symbol, file or concept name."
    out = [f"Question: {question}", f"Relevant nodes ({len(nodes)}):"]
    for nid in nodes:
        n = g.nodes[nid]
        doc = f" · {n.doc}" if n.doc else ""
        out.append(f"  • {describe(g, nid)}{doc}")
    out.append("")
    out.append(f"Edges ({len(edges)}):")
    for e in edges:
        if e.rel == "contains":
            continue
        out.append(f"  {g.nodes[e.src].name} --{e.rel}--> {g.nodes[e.dst].name} [{e.conf}] @ {e.at}")
    return "\n".join(out)


# ---------------------------------------------------------------- impact
def impact(g: Graph, nid: str, depth: int = 3) -> List[Tuple[int, str, Edge]]:
    """Who depends on ``nid`` (transitively)? Includes members of a file/class target."""
    targets = {nid}
    stack = [nid]
    while stack:  # changing a class/file affects its members' dependents too
        cur = stack.pop()
        for e in g.out_edges(cur):
            if e.rel == "contains" and e.dst not in targets:
                targets.add(e.dst)
                stack.append(e.dst)
    seen = set(targets)
    frontier = list(targets)
    result: List[Tuple[int, str, Edge]] = []
    for d in range(1, depth + 1):
        nxt = []
        for cur in frontier:
            for e in g.in_edges(cur):
                if e.rel not in DEPENDENCY_RELS or e.src in seen:
                    continue
                seen.add(e.src)
                result.append((d, e.src, e))
                nxt.append(e.src)
        frontier = nxt
        if not frontier:
            break
    return result


def fmt_impact(g: Graph, nid: str, rows) -> str:
    out = [f"Impact of changing {describe(g, nid)}:"]
    if not rows:
        out.append("  nothing in the graph depends on it.")
        return "\n".join(out)
    files = sorted({g.nodes[s].file for _, s, _ in rows if g.nodes[s].file})
    out.append(f"  {len(rows)} dependent node(s) across {len(files)} file(s)")
    for d, s, e in rows:
        out.append(f"  {'  ' * (d - 1)}[{d}] {describe(g, s)} --{e.rel}--> {g.nodes[e.dst].name} [{e.conf}]")
    return "\n".join(out)


# ---------------------------------------------------------------- cycles
def import_cycles(g: Graph, limit: int = 20) -> List[List[str]]:
    """Strongly connected components (size > 1) of the file import graph (Tarjan, iterative)."""
    adj: Dict[str, List[str]] = {}
    for e in g.edges.values():
        if e.rel == "imports" and e.dst.startswith("file:") and e.src.startswith("file:"):
            adj.setdefault(e.src, []).append(e.dst)
    index: Dict[str, int] = {}
    low: Dict[str, int] = {}
    on: Set[str] = set()
    st: List[str] = []
    comps: List[List[str]] = []
    counter = 0
    for root in sorted(adj):
        if root in index:
            continue
        work = [(root, 0)]
        while work:
            v, i = work.pop()
            if i == 0:
                index[v] = low[v] = counter
                counter += 1
                st.append(v)
                on.add(v)
            nbrs = sorted(adj.get(v, []))
            if i < len(nbrs):
                work.append((v, i + 1))
                w = nbrs[i]
                if w not in index:
                    work.append((w, 0))
                elif w in on:
                    low[v] = min(low[v], index[w])
                continue
            if low[v] == index[v]:
                comp = []
                while True:
                    w = st.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1:
                    comps.append(sorted(comp))
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[v])
    comps.sort(key=lambda c: (-len(c), c))
    return comps[:limit]


# ---------------------------------------------------------------- diff
def diff(old: Graph, new: Graph) -> Dict[str, list]:
    on, nn = set(old.nodes), set(new.nodes)
    oe, ne = set(old.edges), set(new.edges)
    return {
        "added_nodes": sorted(nn - on),
        "removed_nodes": sorted(on - nn),
        "added_edges": sorted(ne - oe),
        "removed_edges": sorted(oe - ne),
    }


def fmt_diff(d: Dict[str, list], limit: int = 40) -> str:
    out = []
    for key, title in (("added_nodes", "Added nodes"), ("removed_nodes", "Removed nodes"),
                       ("added_edges", "Added edges"), ("removed_edges", "Removed edges")):
        items = d[key]
        out.append(f"{title}: {len(items)}")
        for it in items[:limit]:
            out.append("  " + (f"{it[0]} --{it[2]}--> {it[1]}" if isinstance(it, tuple) else it))
        if len(items) > limit:
            out.append(f"  ... {len(items) - limit} more")
    return "\n".join(out)
