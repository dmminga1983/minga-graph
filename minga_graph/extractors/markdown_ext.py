"""Markdown extractor: heading tree, links to local files, and `code` mentions."""

from __future__ import annotations

import re

from ..secrets import redact

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
LINK = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
INLINE_CODE = re.compile(r"`([A-Za-z_][\w.]*(?:\(\))?)`")
FENCE = re.compile(r"^\s*(```|~~~)")


def slug(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text.lower(), flags=re.UNICODE).strip()
    return re.sub(r"[\s]+", "-", s)


def extract(relpath: str, text: str) -> dict:
    from . import file_node

    lines = text.splitlines()
    fid = f"file:{relpath}"
    res = {"nodes": [file_node(relpath, len(lines))], "edges": [], "refs": [], "aliases": {}, "module": ""}
    stack = []  # (level, id)
    in_fence = False
    used = set()
    current = fid
    for i, line in enumerate(lines, 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING.match(line)
        if m:
            level, title = len(m.group(1)), redact(m.group(2).strip())
            base = slug(title) or f"h{i}"
            sid, k = base, 2
            while sid in used:
                sid, k = f"{base}-{k}", k + 1
            used.add(sid)
            hid = f"doc:{relpath}#{sid}"
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else fid
            res["nodes"].append({"id": hid, "kind": "heading", "name": title[:120], "file": relpath, "line": i})
            res["edges"].append({"src": parent, "dst": hid, "rel": "contains", "conf": "EXTRACTED",
                                 "why": "section", "at": f"{relpath}:{i}"})
            stack.append((level, hid))
            current = hid
            continue
        for lm in LINK.finditer(line):
            target = lm.group(2)
            if re.match(r"^[a-z][a-z0-9+.\-]*:", target, re.I) or target.startswith("#"):
                continue
            res["refs"].append({"src": current, "name": target.split("#")[0], "rel": "links_to",
                                "at": f"{relpath}:{i}", "spec": target.split("#")[0]})
        for cm in INLINE_CODE.finditer(line):
            name = cm.group(1).rstrip("()")
            if len(name) < 3:
                continue
            res["refs"].append({"src": current, "name": name, "rel": "mentions", "at": f"{relpath}:{i}"})
    # close heading spans: end_line = line before next heading of same or higher level
    heads = [n for n in res["nodes"] if n["kind"] == "heading"]
    for idx, h in enumerate(heads):
        h["end_line"] = (heads[idx + 1]["line"] - 1) if idx + 1 < len(heads) else len(lines)
    return res
