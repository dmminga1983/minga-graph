"""Python extractor based on the standard library ``ast`` module (exact, deterministic)."""

from __future__ import annotations

import ast
import io
import re
import tokenize

from ..secrets import redact

NOTE_RX = re.compile(r"#\s*(NOTE|WHY|HACK|TODO|FIXME|XXX|SECURITY)\b[:\s]\s*(.+)", re.I)


def module_name(relpath: str) -> str:
    p = relpath[:-4] if relpath.endswith(".pyi") else relpath[:-3]
    parts = [x for x in p.split("/") if x]
    # Drop a leading "src" layout directory.
    if parts and parts[0] == "src" and len(parts) > 1:
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _first_line(doc):
    if not doc:
        return ""
    for line in doc.strip().splitlines():
        line = line.strip()
        if line:
            return redact(line[:200])
    return ""


def _dotted(node) -> str:
    """Return 'a.b.c' for Name/Attribute chains, '' otherwise."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    if isinstance(node, ast.Call):
        inner = _dotted(node.func)
        return (inner + "()." + ".".join(reversed(parts))) if inner and parts else ""
    return ""


def extract(relpath: str, text: str) -> dict:
    from . import file_node

    nlines = text.count("\n") + 1
    fid = f"file:{relpath}"
    mod = module_name(relpath)
    res = {"nodes": [file_node(relpath, nlines)], "edges": [], "refs": [], "aliases": {}, "module": mod}
    try:
        tree = ast.parse(text, filename=relpath)
    except (SyntaxError, ValueError):
        return res

    mod_doc = _first_line(ast.get_docstring(tree))
    if mod_doc:
        res["nodes"][0]["doc"] = mod_doc

    is_pkg_init = relpath.endswith("__init__.py")
    pkg = mod if is_pkg_init else mod.rpartition(".")[0]
    spans = []  # (start, end, id) for attaching notes

    def at(n):
        return f"{relpath}:{getattr(n, 'lineno', 0)}"

    def add_import(name: str, n, alias: str, target: str):
        res["refs"].append({"src": fid, "name": name, "rel": "imports", "at": at(n)})
        if alias:
            res["aliases"][alias] = target

    def resolve_relative(module, level):
        if not level:
            return module or ""
        base = pkg.split(".") if pkg else []
        if level > 1:
            base = base[: len(base) - (level - 1)] if level - 1 <= len(base) else []
        return ".".join([*base, module] if module else base)

    def scan_body(fn, src_id, class_id):
        """Calls, function-local imports, and functions passed as values (callbacks, registries)."""
        seen_calls, seen_refs = set(), set()
        called = set()
        for sub in ast.walk(fn):
            if isinstance(sub, ast.Call):
                called.add(id(sub.func))
        for sub in ast.walk(fn):
            if sub is fn:
                continue
            if isinstance(sub, ast.Import):
                for a in sub.names:
                    add_import(a.name, sub, a.asname or a.name.split(".")[0],
                               a.name if a.asname else a.name.split(".")[0])
            elif isinstance(sub, ast.ImportFrom):
                base = resolve_relative(sub.module, sub.level)
                for a in sub.names:
                    if a.name == "*":
                        continue
                    full = f"{base}.{a.name}" if base else a.name
                    res["refs"].append({"src": fid, "name": full, "rel": "imports", "at": at(sub), "soft": True})
                    add_import(base, sub, a.asname or a.name, full)
            elif isinstance(sub, ast.Call):
                name = _dotted(sub.func)
                if name and "()" not in name and name not in seen_calls:
                    seen_calls.add(name)
                    ref = {"src": src_id, "name": name, "rel": "calls", "at": at(sub)}
                    if class_id:
                        ref["scope"] = class_id
                    res["refs"].append(ref)
            elif isinstance(sub, (ast.Name, ast.Attribute)) and isinstance(getattr(sub, "ctx", None), ast.Load) \
                    and id(sub) not in called:
                name = _dotted(sub)
                if name and name not in seen_refs and name not in seen_calls and name.split(".")[0] not in ("self", "cls"):
                    seen_refs.add(name)
                    res["refs"].append({"src": src_id, "name": name, "rel": "references", "at": at(sub), "strict": True})

    def visit(body, parent_id, qual_prefix, class_id=None):
        for n in body:
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                if isinstance(n, ast.Import):
                    for a in n.names:
                        add_import(a.name, n, a.asname or a.name.split(".")[0],
                                   a.name if a.asname else a.name.split(".")[0])
                else:
                    base = resolve_relative(n.module, n.level)
                    for a in n.names:
                        if a.name == "*":
                            add_import(base, n, "", "")
                            continue
                        full = f"{base}.{a.name}" if base else a.name
                        # "from pkg import sub" may be a module or a symbol: emit both, resolver keeps what exists.
                        res["refs"].append({"src": fid, "name": full, "rel": "imports", "at": at(n), "soft": True})
                        add_import(base, n, a.asname or a.name, full)
                continue
            if isinstance(n, ast.ClassDef):
                qual = f"{qual_prefix}{n.name}"
                cid = f"sym:{relpath}::{qual}"
                res["nodes"].append({"id": cid, "kind": "class", "name": n.name, "file": relpath,
                                     "line": n.lineno, "end_line": getattr(n, "end_lineno", n.lineno),
                                     "doc": _first_line(ast.get_docstring(n)), "qual": f"{mod}.{qual}" if mod else qual})
                res["edges"].append({"src": parent_id, "dst": cid, "rel": "contains", "conf": "EXTRACTED",
                                     "why": "class defined here", "at": at(n)})
                spans.append((n.lineno, getattr(n, "end_lineno", n.lineno), cid))
                for b in n.bases:
                    name = _dotted(b)
                    if name and name != "object":
                        res["refs"].append({"src": cid, "name": name, "rel": "inherits", "at": at(n)})
                for d in n.decorator_list:
                    name = _dotted(d.func if isinstance(d, ast.Call) else d)
                    if name:
                        res["refs"].append({"src": cid, "name": name, "rel": "uses", "at": at(d), "why": "decorator"})
                visit(n.body, cid, qual + ".", class_id=cid)
                continue
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{qual_prefix}{n.name}"
                fnid = f"sym:{relpath}::{qual}"
                kind = "method" if class_id else "function"
                res["nodes"].append({"id": fnid, "kind": kind, "name": n.name, "file": relpath,
                                     "line": n.lineno, "end_line": getattr(n, "end_lineno", n.lineno),
                                     "doc": _first_line(ast.get_docstring(n)), "qual": f"{mod}.{qual}" if mod else qual})
                res["edges"].append({"src": parent_id, "dst": fnid, "rel": "contains", "conf": "EXTRACTED",
                                     "why": f"{kind} defined here", "at": at(n)})
                spans.append((n.lineno, getattr(n, "end_lineno", n.lineno), fnid))
                for d in n.decorator_list:
                    name = _dotted(d.func if isinstance(d, ast.Call) else d)
                    if name:
                        res["refs"].append({"src": fnid, "name": name, "rel": "uses", "at": at(d), "why": "decorator"})
                scan_body(n, fnid, class_id)
                # nested defs (closures) are indexed too
                nested = [s for s in n.body if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
                if nested:
                    visit(nested, fnid, qual + ".", class_id=None)
                continue
            # if/try/with/for blocks can hide defs and imports: recurse into them.
            if isinstance(n, (ast.If, ast.Try, ast.With, ast.AsyncWith, ast.For, ast.AsyncFor, ast.While)) or \
                    type(n).__name__ == "TryStar":
                if parent_id == fid:
                    header = getattr(n, "test", None) or getattr(n, "iter", None)
                    for item in [header] + [w.context_expr for w in getattr(n, "items", [])]:
                        if item is None:
                            continue
                        for sub in ast.walk(item):
                            if isinstance(sub, ast.Call):
                                name = _dotted(sub.func)
                                if name and "()" not in name:
                                    res["refs"].append({"src": fid, "name": name, "rel": "calls", "at": at(sub)})
                blocks = []
                for field in ("body", "orelse", "finalbody", "handlers"):
                    for x in getattr(n, field, None) or []:
                        blocks.extend(x.body if isinstance(x, ast.ExceptHandler) else [x])
                visit(blocks, parent_id, qual_prefix, class_id)
                continue
            # Plain module-level statements: top-level calls (app wiring) become calls from the file.
            if parent_id == fid:
                scan_body(n, fid, None)

    visit(tree.body, fid, "")

    # Rationale comments become first-class nodes linked to their enclosing symbol.
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type != tokenize.COMMENT:
                continue
            m = NOTE_RX.search(tok.string)
            if not m:
                continue
            line = tok.start[0]
            owner = fid
            best = None
            for s, e, sid in spans:
                if s <= line <= e and (best is None or e - s < best):
                    owner, best = sid, e - s
            nid = f"note:{relpath}:{line}"
            res["nodes"].append({"id": nid, "kind": "note", "name": f"{m.group(1).upper()}: {redact(m.group(2).strip())[:80]}",
                                 "file": relpath, "line": line, "doc": redact(m.group(2).strip())[:300]})
            res["edges"].append({"src": nid, "dst": owner, "rel": "explains", "conf": "EXTRACTED",
                                 "why": f"{m.group(1).upper()} comment inside", "at": f"{relpath}:{line}"})
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return res
