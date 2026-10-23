"""JavaScript / TypeScript extractor.

No parser dependency: a small lexer blanks out comments and string contents
(preserving offsets and newlines), then declarations, imports and calls are
found with targeted regexes and brace matching. It is not a full parser, so
call edges it produces are marked INFERRED unless backed by an explicit import.
"""

from __future__ import annotations

import bisect
import re
from typing import List, Tuple

from ..secrets import redact

KEYWORDS = {
    "if", "for", "while", "switch", "catch", "function", "return", "typeof", "new", "await",
    "super", "import", "export", "delete", "void", "in", "of", "do", "else", "try", "case",
    "throw", "yield", "constructor", "async", "get", "set", "static", "with", "instanceof",
}
ID = r"[A-Za-z_$][\w$]*"


def _lex(src: str) -> Tuple[str, str]:
    """Return (no_comments, code). ``code`` also blanks string/template contents."""
    n = len(src)
    nc = list(src)
    code = list(src)
    i = 0
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = src.find("\n", i)
            j = n if j == -1 else j
            for k in range(i, j):
                nc[k] = code[k] = " "
            i = j
            continue
        if c == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            for k in range(i, j):
                if src[k] != "\n":
                    nc[k] = code[k] = " "
            i = j
            continue
        if c in "'\"`":
            q = c
            j = i + 1
            while j < n:
                ch = src[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch == q:
                    break
                if q != "`" and ch == "\n":
                    break
                j += 1
            for k in range(i + 1, min(j, n)):
                if src[k] != "\n":
                    code[k] = " "
            i = j + 1
            continue
        i += 1
    return "".join(nc), "".join(code)


def _brace_pairs(code: str):
    pairs = {}
    stack = []
    for i, ch in enumerate(code):
        if ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            pairs[stack.pop()] = i
    return pairs


IMPORT_FROM = re.compile(r"\bimport\s+(?:type\s+)?([\w$\s{},*]+?)\s+from\s*['\"]([^'\"]+)['\"]")
IMPORT_SIDE = re.compile(r"\bimport\s*['\"]([^'\"]+)['\"]")
EXPORT_FROM = re.compile(r"\bexport\s+(?:type\s+)?(\*(?:\s+as\s+" + ID + r")?|\{[^}]*\})\s*from\s*['\"]([^'\"]+)['\"]")
REQUIRE = re.compile(r"(?:\b(?:const|let|var)\s+(" + ID + r"|\{[^}]*\})\s*=\s*)?\brequire\s*\(\s*['\"]([^'\"]+)['\"]\s*\)")
DYN_IMPORT = re.compile(r"\bimport\s*\(\s*['\"]([^'\"]+)['\"]\s*\)")

CLASS_RX = re.compile(r"\b(export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(" + ID + r")(?:\s*<[^>{]*>)?"
                      r"(?:\s+extends\s+([\w$.]+)(?:\s*<[^>{]*>)?)?(?:\s+implements\s+([\w$.,\s<>]+?))?\s*\{")
IFACE_RX = re.compile(r"\b(export\s+)?interface\s+(" + ID + r")(?:\s*<[^>{]*>)?(?:\s+extends\s+([\w$.,\s<>]+?))?\s*\{")
FUNC_RX = re.compile(r"\b(export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(" + ID + r")\s*(?:<[^>(]*>)?\s*\(")
ARROW_RX = re.compile(r"\b(export\s+)?(?:const|let|var)\s+(" + ID + r")\s*(?::[^=;]+)?=\s*(?:async\s+)?"
                      r"(?:function\b[^(]*\(|(?:<[^>]*>\s*)?\([^)]*\)\s*(?::[^=;{]+)?=>|" + ID + r"\s*=>)")
METHOD_RX = re.compile(r"^[ \t]*(?:(?:public|private|protected|static|async|readonly|override|abstract|get|set)\s+)*\*?\s*"
                       r"(#?" + ID + r")\s*(?:<[^>(]*>)?\s*\([^;{]*?\)\s*(?::\s*[^{;=]+)?\{", re.M)
EXPORT_LIST = re.compile(r"\bexport\s*\{([^}]*)\}(?!\s*from)")
EXPORT_DEFAULT_ID = re.compile(r"\bexport\s+default\s+(" + ID + r")\s*;?\s*$", re.M)
CALL_RX = re.compile(r"(?<![\w$.#])((?:this\.)?#?" + ID + r"(?:\.#?" + ID + r")*)\s*(?:<[^<>()]*>)?\s*\(")
JSDOC_RX = re.compile(r"/\*\*([\s\S]*?)\*/\s*$")


def module_name(relpath: str) -> str:
    return re.sub(r"\.(?:d\.)?[cm]?[jt]sx?$", "", relpath)


def _find_body(code: str, pos: int, arrow: bool):
    """Return the offset of the '{' opening a function body, or None (expression body)."""
    n = len(code)
    if arrow:
        j = pos
        while j < n and code[j] in " \t\r\n":
            j += 1
        return j if j < n and code[j] == "{" else None
    # pos is just after '(' of the parameter list: skip to the matching ')'
    depth = 1
    j = pos
    while j < n and depth:
        if code[j] == "(":
            depth += 1
        elif code[j] == ")":
            depth -= 1
        j += 1
    # then skip an optional return type / arrow up to the body
    limit = min(n, j + 400)
    angle = 0
    while j < limit:
        ch = code[j]
        if ch == "<":
            angle += 1
        elif ch == ">":
            angle = max(0, angle - 1)
        elif ch == "{" and angle == 0:
            # "{" right after ':' in a return type is an object type; accept when followed by body-like content
            return j
        elif ch == ";":
            return None
        j += 1
    return None


def _parse_clause(clause: str):
    """Parse an import clause into [(local, imported)]."""
    out = []
    clause = clause.strip()
    m = re.match(r"(" + ID + r")\s*(?:,|$)", clause)
    if m and not clause.startswith("{") and not clause.startswith("*"):
        out.append((m.group(1), "default"))
        clause = clause[m.end():].strip()
    m = re.search(r"\*\s+as\s+(" + ID + r")", clause)
    if m:
        out.append((m.group(1), "*"))
    m = re.search(r"\{([^}]*)\}", clause)
    if m:
        for part in m.group(1).split(","):
            part = part.strip()
            if not part:
                continue
            part = re.sub(r"^type\s+", "", part)
            if " as " in part:
                imp, loc = [x.strip() for x in part.split(" as ", 1)]
            else:
                imp = loc = part
            if re.fullmatch(ID, loc) and re.fullmatch(ID + "|default", imp):
                out.append((loc, imp))
    return out


def extract(relpath: str, text: str) -> dict:
    from . import file_node

    nc, code = _lex(text)
    line_starts = [0] + [i + 1 for i, ch in enumerate(text) if ch == "\n"]

    def line_of(pos: int) -> int:
        return bisect.bisect_right(line_starts, pos)

    fid = f"file:{relpath}"
    res = {"nodes": [file_node(relpath, len(line_starts))], "edges": [], "refs": [], "aliases": {},
           "module": module_name(relpath), "exports": {}}

    def at(pos):
        return f"{relpath}:{line_of(pos)}"

    # ---- imports ---------------------------------------------------------
    def imp(spec, pos, pairs=()):
        res["refs"].append({"src": fid, "name": spec, "rel": "imports", "at": at(pos), "spec": spec})
        for loc, name in pairs:
            res["aliases"][loc] = f"{spec}::{name}"

    for m in IMPORT_FROM.finditer(nc):
        imp(m.group(2), m.start(), _parse_clause(m.group(1)))
    for m in IMPORT_SIDE.finditer(nc):
        imp(m.group(1), m.start())
    for m in EXPORT_FROM.finditer(nc):
        imp(m.group(2), m.start())
    for m in DYN_IMPORT.finditer(nc):
        imp(m.group(1), m.start())
    for m in REQUIRE.finditer(nc):
        target = m.group(1)
        pairs = []
        if target:
            if target.startswith("{"):
                pairs = _parse_clause(target.replace(":", " as "))
            else:
                pairs = [(target, "*")]
        imp(m.group(2), m.start(), pairs)

    pairs = _brace_pairs(code)
    decls: List[dict] = []  # {id, start, end, name, kind}

    def body_end(open_pos):
        return pairs.get(open_pos, open_pos)

    def jsdoc(pos):
        m = JSDOC_RX.search(text[max(0, pos - 2000):pos])
        if not m:
            return ""
        lines = [re.sub(r"^\s*\*\s?", "", ln).strip() for ln in m.group(1).splitlines()]
        lines = [ln for ln in lines if ln and not ln.startswith("@")]
        return redact(lines[0][:200]) if lines else ""

    def add_decl(kind, name, start, open_pos, exported, parent=fid, qual=None):
        qual = qual or name
        nid = f"sym:{relpath}::{qual}"
        end = body_end(open_pos) if open_pos is not None else start
        res["nodes"].append({"id": nid, "kind": kind, "name": name, "file": relpath, "line": line_of(start),
                             "end_line": line_of(end), "doc": jsdoc(start), "qual": f"{res['module']}::{qual}"})
        res["edges"].append({"src": parent, "dst": nid, "rel": "contains", "conf": "EXTRACTED",
                             "why": f"{kind} defined here", "at": at(start)})
        decls.append({"id": nid, "start": start, "end": end, "name": name, "kind": kind, "open": open_pos})
        if exported and parent == fid:
            res["exports"][name] = nid
        return nid

    def depth_at(pos):
        # number of enclosing braces = top-level when 0
        d = 0
        for o, c in pairs.items():
            if o < pos < c:
                d += 1
        return d

    top_level_cache = {}

    def is_top(pos):
        if pos not in top_level_cache:
            top_level_cache[pos] = depth_at(pos) == 0
        return top_level_cache[pos]

    for m in CLASS_RX.finditer(code):
        start = m.start(2)
        if not is_top(m.start()):
            continue
        open_pos = m.end() - 1
        cid = add_decl("class", m.group(2), m.start(), open_pos, bool(m.group(1)) or "default" in m.group(0)[:30])
        if m.group(3):
            res["refs"].append({"src": cid, "name": m.group(3), "rel": "inherits", "at": at(start)})
        if m.group(4):
            for iface in m.group(4).split(","):
                iface = re.sub(r"<.*", "", iface).strip()
                if iface:
                    res["refs"].append({"src": cid, "name": iface, "rel": "inherits", "at": at(start), "why": "implements"})
        body_start, body_stop = open_pos + 1, body_end(open_pos)
        body = code[body_start:body_stop]
        for mm in METHOD_RX.finditer(body):
            mname = mm.group(1)
            if mname in KEYWORDS and mname != "constructor":
                continue
            abs_pos = body_start + mm.start(1)
            # only direct members of the class body
            if depth_at(abs_pos) != depth_at(open_pos + 1):
                continue
            add_decl("method", mname, abs_pos, body_start + mm.end() - 1, False, parent=cid,
                     qual=f"{m.group(2)}.{mname}")

    for m in IFACE_RX.finditer(code):
        if not is_top(m.start()):
            continue
        iid = add_decl("interface", m.group(2), m.start(), m.end() - 1, bool(m.group(1)))
        if m.group(3):
            for base in m.group(3).split(","):
                base = re.sub(r"<.*", "", base).strip()
                if base:
                    res["refs"].append({"src": iid, "name": base, "rel": "inherits", "at": at(m.start())})

    for rx in (FUNC_RX, ARROW_RX):
        for m in rx.finditer(code):
            if not is_top(m.start()):
                continue
            name = m.group(2)
            if any(d["name"] == name and d["kind"] in ("function",) for d in decls):
                continue
            open_pos = _find_body(code, m.end(), arrow=rx is ARROW_RX and m.group(0).rstrip().endswith("=>"))
            add_decl("function", name, m.start(), open_pos, bool(m.group(1)) or "export default" in code[m.start():m.start() + 20])

    for m in EXPORT_LIST.finditer(code):
        for part in m.group(1).split(","):
            part = part.strip()
            if not part:
                continue
            local, _, exported = part.partition(" as ")
            local, exported = local.strip(), (exported or local).strip()
            for d in decls:
                if d["name"] == local and d["kind"] != "method":
                    res["exports"][exported] = d["id"]
    for m in EXPORT_DEFAULT_ID.finditer(code):
        for d in decls:
            if d["name"] == m.group(1) and d["kind"] != "method":
                res["exports"]["default"] = d["id"]

    # ---- calls -----------------------------------------------------------
    funcs = sorted([d for d in decls if d["kind"] in ("function", "method") and d["open"] is not None],
                   key=lambda d: d["end"] - d["start"])
    class_of = {}
    for d in decls:
        if d["kind"] == "method":
            class_of[d["id"]] = d["id"].rsplit(".", 1)[0]
    seen = set()
    for m in CALL_RX.finditer(code):
        name = m.group(1)
        head = name.split(".")[0]
        if head in KEYWORDS or name in KEYWORDS:
            continue
        pos = m.start()
        owner = None
        for d in funcs:  # smallest enclosing function
            if d["open"] < pos < d["end"]:
                owner = d
                break
        src = owner["id"] if owner else fid
        if owner is None and is_top(pos) is False:
            # call inside a class field initialiser or object literal: attribute to file
            src = fid
        # skip the declaration itself ("function foo(" / method signature)
        if any(d["start"] <= pos <= (d["open"] or d["start"]) and d["name"] == name.split(".")[-1].lstrip("#") for d in decls):
            continue
        key = (src, name)
        if key in seen:
            continue
        seen.add(key)
        ref = {"src": src, "name": name, "rel": "calls", "at": at(pos)}
        if owner and owner["id"] in class_of:
            ref["scope"] = class_of[owner["id"]]
        res["refs"].append(ref)
    return res
