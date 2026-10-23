"""Cross-file resolution: turns per-file refs into graph edges.

Confidence policy (stricter than "match anything with the same name"):
  EXTRACTED  the source text explicitly binds the name: same-file definition,
             an explicit import binding, ``self.x`` inside the defining class,
             SQL REFERENCES, Markdown links to an existing file.
  INFERRED   the name is matched by a *unique* project-wide symbol name.
  (dropped)  ambiguous names (2+ candidates) and very generic names are not
             linked at all: no edge is better than a wrong edge.
"""

from __future__ import annotations

import posixpath
import sys
from typing import Dict, List, Optional, Tuple

from .model import Edge, Graph, Node, EXTRACTED, INFERRED

GENERIC_NAMES = {
    "get", "set", "run", "add", "put", "pop", "len", "map", "log", "new", "init", "main", "call",
    "append", "extend", "update", "items", "keys", "values", "copy", "join", "split", "strip",
    "format", "print", "push", "filter", "reduce", "find", "error", "warn", "info", "debug",
    "open", "close", "read", "write", "send", "start", "stop", "next", "then", "catch", "emit",
    "apply", "bind", "toString", "render", "create", "delete", "remove", "clear", "load", "save",
    "parse", "test", "exec", "match", "replace", "lower", "upper", "encode", "decode", "dumps",
    "loads", "sort", "sorted", "range", "list", "dict", "str", "int", "float", "bool", "tuple",
    "isinstance", "super", "setUp", "tearDown", "assertEqual", "assertTrue", "describe", "it",
    "expect", "require", "fetch", "resolve", "reject", "handle", "process", "build", "value",
}
STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}
NODE_BUILTINS = {"fs", "path", "os", "http", "https", "url", "util", "crypto", "events", "stream",
                 "child_process", "assert", "buffer", "zlib", "net", "tls", "dns", "readline", "process",
                 "querystring", "worker_threads", "cluster", "perf_hooks", "timers", "module", "vm"}
JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".d.ts")
CALLABLE_KINDS = {"function", "method", "class"}
TYPE_KINDS = {"class", "interface"}


class Index:
    def __init__(self, results: Dict[str, dict]):
        self.results = results
        self.files = set(results)
        self.py_modules: Dict[str, str] = {}
        self.by_qual: Dict[str, str] = {}
        self.top: Dict[str, Dict[str, str]] = {}          # relpath -> name -> id
        self.members: Dict[str, Dict[str, str]] = {}      # class id -> name -> id
        self.by_name: Dict[str, List[Tuple[str, str]]] = {}  # name -> [(id, kind)]
        self.kind: Dict[str, str] = {}
        self.parent: Dict[str, str] = {}                  # symbol id -> containing node id
        self.children: Dict[str, Dict[str, str]] = {}     # node id -> name -> nested def id
        for rel, r in results.items():
            if rel.endswith((".py", ".pyi")) and r.get("module") is not None:
                self.py_modules[r["module"]] = rel
            top = self.top.setdefault(rel, {})
            parents = {e["dst"]: e["src"] for e in r["edges"] if e["rel"] == "contains"}
            for n in r["nodes"]:
                self.kind[n["id"]] = n["kind"]
                if n.get("qual"):
                    self.by_qual[n["qual"]] = n["id"]
                if n["kind"] in ("class", "function", "method", "interface"):
                    self.by_name.setdefault(n["name"], []).append((n["id"], n["kind"]))
                    parent = parents.get(n["id"], "")
                    self.parent[n["id"]] = parent
                    self.children.setdefault(parent, {})[n["name"]] = n["id"]
                    if parent.startswith("file:"):
                        top[n["name"]] = n["id"]
                    elif n["kind"] == "method":
                        self.members.setdefault(parent, {})[n["name"]] = n["id"]
            for name, nid in (r.get("exports") or {}).items():
                top.setdefault(name, nid)
        self.py_tops = {m.split(".")[0] for m in self.py_modules if m}

    # ---- module/file resolution -----------------------------------------
    def py_module_file(self, dotted: str) -> Optional[str]:
        return self.py_modules.get(dotted)

    def js_file(self, from_rel: str, spec: str) -> Optional[str]:
        cands = []
        if spec.startswith("."):
            base = posixpath.normpath(posixpath.join(posixpath.dirname(from_rel), spec))
            cands.append(base)
        elif spec.startswith(("@/", "~/")):
            cands += ["src/" + spec[2:], spec[2:]]
        elif spec.startswith("/"):
            cands.append(spec.lstrip("/"))
        else:
            return None
        for b in cands:
            if b in self.files:
                return b
            for ext in JS_EXTS:
                if b + ext in self.files:
                    return b + ext
            for ext in JS_EXTS:
                if f"{b}/index{ext}" in self.files:
                    return f"{b}/index{ext}"
            # TS ESM style: import "./x.js" for x.ts
            stem, ext0 = posixpath.splitext(b)
            if ext0 in (".js", ".mjs", ".cjs", ".jsx"):
                for ext in (".ts", ".tsx", ".mts", ".cts"):
                    if stem + ext in self.files:
                        return stem + ext
        return None

    # ---- symbol resolution ----------------------------------------------
    def lookup_qual(self, qual: str) -> Optional[str]:
        if qual in self.by_qual:
            return self.by_qual[qual]
        # module.Class.method where the class lives in module/__init__ re-export chains is out of scope
        return None

    def unique(self, name: str, kinds) -> Optional[str]:
        cands = [i for i, k in self.by_name.get(name, []) if k in kinds]
        return cands[0] if len(cands) == 1 else None


def _member(idx: Index, owner: str, rest: List[str]) -> Optional[str]:
    cur = owner
    for part in rest:
        nxt = idx.members.get(cur, {}).get(part)
        if not nxt:
            return None
        cur = nxt
    return cur


def resolve_name(idx: Index, rel: str, ref: dict, kinds) -> Tuple[Optional[str], str, str]:
    """Return (target_id, conf, why)."""
    name = ref["name"]
    r = idx.results[rel]
    parts = name.split(".")
    aliases = r.get("aliases") or {}
    is_py = rel.endswith((".py", ".pyi"))

    # self.method / this.method
    if parts[0] in ("self", "cls", "this") and len(parts) == 2 and ref.get("scope"):
        mem = idx.members.get(ref["scope"], {})
        t = mem.get(parts[1]) or mem.get(parts[1].lstrip("#"))
        if t:
            return t, EXTRACTED, f"{parts[0]}.{parts[1]} inside its class"
        return None, "", ""

    # explicit import binding
    if parts[0] in aliases:
        target = aliases[parts[0]]
        if is_py:
            full = ".".join([target] + parts[1:]) if target else ""
            t = idx.lookup_qual(full) if full else None
            if t:
                return t, EXTRACTED, f"bound by import of {target}"
            # import of a module, then mod.func
            modfile = idx.py_module_file(target)
            if modfile and len(parts) >= 2:
                t = idx.top.get(modfile, {}).get(parts[1])
                if t:
                    t2 = _member(idx, t, parts[2:]) if len(parts) > 2 else t
                    if t2:
                        return t2, EXTRACTED, f"bound by import of {target}"
        else:
            spec, _, imported = target.partition("::")
            tfile = idx.js_file(rel, spec)
            if tfile:
                if imported == "*":
                    if len(parts) >= 2:
                        t = idx.top.get(tfile, {}).get(parts[1])
                        if t:
                            t2 = _member(idx, t, parts[2:]) if len(parts) > 2 else t
                            if t2:
                                return t2, EXTRACTED, f"bound by import from {spec}"
                else:
                    t = idx.top.get(tfile, {}).get(imported)
                    if t:
                        t2 = _member(idx, t, parts[1:]) if len(parts) > 1 else t
                        if t2:
                            return t2, EXTRACTED, f"bound by import from {spec}"
        return None, "", ""  # bound to something external: never guess

    # nested definition visible from the enclosing function scopes (closures)
    scope = ref["src"]
    while scope and not scope.startswith("file:"):
        t = idx.children.get(scope, {}).get(parts[0])
        if t and idx.kind.get(t) in ("function", "class") and len(parts) == 1:
            return t, EXTRACTED, "nested definition in enclosing scope"
        scope = idx.parent.get(scope, "")

    # same-file definition
    local = idx.top.get(rel, {})
    if parts[0] in local:
        t = _member(idx, local[parts[0]], parts[1:]) if len(parts) > 1 else local[parts[0]]
        if t and idx.kind.get(t) in kinds:
            return t, EXTRACTED, "defined in the same file"

    if ref.get("strict"):
        return None, "", ""  # value references are linked only when explicitly bound

    # unique project-wide name
    last = parts[-1].lstrip("#")
    if last in GENERIC_NAMES or len(last) < 3 or last.startswith("__"):
        return None, "", ""
    if len(parts) > 1 and len(last) < 4:
        return None, "", ""
    t = idx.unique(last, kinds)
    if t:
        why = "unique name match" if len(parts) == 1 else "unique method name (receiver type unknown)"
        return t, INFERRED, why
    return None, "", ""


def build_graph(results: Dict[str, dict]) -> Tuple[Graph, Dict[str, int]]:
    g = Graph()
    stats = {"refs": 0, "resolved": 0, "dropped": 0}
    for rel in sorted(results):
        r = results[rel]
        for nd in r["nodes"]:
            g.add_node(Node(**{k: nd[k] for k in ("id", "kind", "name", "file", "line", "end_line", "doc") if k in nd}))
    for rel in sorted(results):
        for ed in results[rel]["edges"]:
            g.add_edge(Edge(**ed))

    idx = Index(results)

    def ensure_pkg(name: str) -> str:
        pid = f"pkg:{name.lower()}"
        g.add_node(Node(id=pid, kind="package", name=name.lower()))
        return pid

    for rel in sorted(results):
        r = results[rel]
        for ref in r["refs"]:
            stats["refs"] += 1
            src, rrel, at = ref["src"], ref["rel"], ref["at"]
            if src not in g.nodes:
                stats["dropped"] += 1
                continue
            edge = None
            if rrel == "imports":
                if "spec" in ref:
                    spec = ref["spec"]
                    tf = idx.js_file(rel, spec)
                    if tf:
                        edge = Edge(src, f"file:{tf}", "imports", EXTRACTED, f"import '{spec}'", at)
                    elif not spec.startswith((".", "/", "node:", "@/", "~/")) and spec.split("/")[0] not in NODE_BUILTINS:
                        pkg = "/".join(spec.split("/")[:2]) if spec.startswith("@") else spec.split("/")[0]
                        edge = Edge(src, ensure_pkg(pkg), "imports", EXTRACTED, f"import '{spec}'", at)
                else:
                    name = ref["name"]
                    mf = idx.py_module_file(name)
                    if mf:
                        edge = Edge(src, f"file:{mf}", "imports", EXTRACTED, f"import {name}", at)
                    elif not ref.get("soft") and name:
                        top = name.split(".")[0]
                        internal = top in idx.py_tops
                        if top and top not in STDLIB and not internal:
                            edge = Edge(src, ensure_pkg(top), "imports", EXTRACTED, f"import {name}", at)
            elif rrel == "links_to":
                spec = ref["spec"]
                target = posixpath.normpath(spec.lstrip("/") if spec.startswith("/")
                                            else posixpath.join(posixpath.dirname(rel), spec))
                if target in idx.files:
                    edge = Edge(src, f"file:{target}", "links_to", EXTRACTED, f"markdown link to {spec}", at)
            elif ref.get("exact"):
                if ref["name"] in g.nodes:
                    if src in g.nodes:
                        edge = Edge(src, ref["name"], rrel, EXTRACTED, "REFERENCES" if rrel == "foreign_key" else "used in view", at)
            else:
                kinds = TYPE_KINDS if rrel == "inherits" else (CALLABLE_KINDS | {"interface"})
                if rrel == "mentions":
                    kinds = CALLABLE_KINDS | {"interface"}
                t, conf, why = resolve_name(idx, rel, ref, kinds)
                if t and t in g.nodes:
                    if rrel == "mentions":
                        conf, why = INFERRED, "doc mentions `" + ref["name"] + "`"
                    elif rrel == "calls" and idx.kind.get(t) == "class":
                        why += "; instantiates"
                    elif rrel == "references":
                        why = "passed or stored as a value; " + why
                    if ref.get("why"):
                        why = f"{ref['why']}; {why}"
                    edge = Edge(src, t, rrel, conf, why, at)
            if edge and g.add_edge(edge):
                stats["resolved"] += 1
            else:
                stats["dropped"] += 1
    return g, stats
