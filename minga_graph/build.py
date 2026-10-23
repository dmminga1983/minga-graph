"""Build pipeline: scan -> extract (cached per file hash) -> resolve -> cluster -> write."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import shutil
import time
from typing import Dict, List, Optional, Sequence

from . import SCHEMA_VERSION, __version__
from .cluster import assign
from .extractors import EXTRACTOR_VERSION, pick
from .html import build_html, DEFAULT_NODE_LIMIT
from .model import Graph
from .report import build_report
from .resolve import build_graph
from .scan import read_text, walk
from .secrets import Finding, scan_text

OUT_DIR = "minga-out"
CACHE_FILE = "cache.json"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def _code_fingerprint() -> str:
    """Cache key part that changes whenever minga-graph's own code changes."""
    h = hashlib.sha256()
    pkg = os.path.dirname(os.path.abspath(__file__))
    for dirpath, _dirs, files in sorted(os.walk(pkg)):
        for f in sorted(files):
            if f.endswith(".py"):
                with open(os.path.join(dirpath, f), "rb") as fh:
                    h.update(fh.read())
    return h.hexdigest()[:16]


def _load_json(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _atomic_write(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


def build(root: str, out_dir: Optional[str] = None, *, lang: str = "en", html: bool = True,
          excludes: Sequence[str] = (), resolution: float = 1.0, node_limit: int = DEFAULT_NODE_LIMIT,
          full: bool = False, log=print) -> Dict:
    t0 = time.time()
    root = os.path.abspath(root)
    out = os.path.abspath(out_dir or os.path.join(root, OUT_DIR))
    os.makedirs(out, exist_ok=True)
    _ensure_gitignore_hint(out)

    cache_path = os.path.join(out, CACHE_FILE)
    cache = {} if full else (_load_json(cache_path) or {})
    cache_key = f"{SCHEMA_VERSION}:{EXTRACTOR_VERSION}:{__version__}:{_code_fingerprint()}"
    if cache.get("_v") != cache_key:
        cache = {}
    files_cache = cache.get("files", {})

    results: Dict[str, dict] = {}
    secrets: List[Finding] = []
    new_cache: Dict[str, dict] = {}
    n_scanned = n_reused = 0
    for rel, abspath in walk(root, excludes):
        if os.path.commonpath([abspath, out]) == out:
            continue
        ext = pick(rel)
        text = read_text(abspath)
        if text is None:
            continue
        h = _sha(text)
        cached = files_cache.get(rel)
        hit = bool(cached and cached.get("sha") == h)
        if hit:
            found = [Finding(**f) for f in cached.get("secrets", [])]
        else:
            found = scan_text(text, rel)
        secrets.extend(found)
        if ext is None:
            new_cache[rel] = {"sha": h, "secrets": [f.__dict__ for f in found]}
            continue
        if hit and "res" in cached:
            results[rel] = cached["res"]
            n_reused += 1
        else:
            try:
                results[rel] = ext(rel, text)
            except Exception as exc:  # never let one odd file kill the build
                log(f"  ! skipped {rel}: {type(exc).__name__}: {exc}")
                continue
            n_scanned += 1
        new_cache[rel] = {"sha": h, "res": results[rel], "secrets": [f.__dict__ for f in found]}

    g, stats = build_graph(results)
    assign(g, resolution)
    g.meta = {
        "schema_version": SCHEMA_VERSION,
        "version": __version__,
        "root_name": os.path.basename(root.rstrip(os.sep)) or root,
        "built_at": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
        "files": len(results),
        "nodes": len(g.nodes),
        "edges": len(g.edges),
        "resolution": resolution,
    }

    graph_path = os.path.join(out, "graph.json")
    if os.path.exists(graph_path):
        shutil.copyfile(graph_path, os.path.join(out, "graph.prev.json"))
    _atomic_write(graph_path, json.dumps(g.to_dict(), ensure_ascii=False, indent=1))
    _atomic_write(os.path.join(out, "GRAPH_REPORT.md"), build_report(g, lang, secrets))
    if html:
        _atomic_write(os.path.join(out, "graph.html"), build_html(g, node_limit))
    _atomic_write(cache_path, json.dumps({"_v": cache_key,
                                          "files": new_cache}, ensure_ascii=False))
    summary = {
        "out": out, "files": len(results), "extracted": n_scanned, "cached": n_reused,
        "nodes": len(g.nodes), "edges": len(g.edges), "communities": len(g.communities),
        "secrets": len(secrets), "seconds": round(time.time() - t0, 2), **stats,
    }
    return summary


def _ensure_gitignore_hint(out: str) -> None:
    """Keep the cache out of git by default; graph.json/report can be committed if wanted."""
    p = os.path.join(out, ".gitignore")
    if not os.path.exists(p):
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("cache.json\ngraph.prev.json\n*.tmp\n")


def load_graph(path: str) -> Graph:
    if os.path.isdir(path):
        cand = os.path.join(path, "graph.json")
        if not os.path.exists(cand):
            cand = os.path.join(path, OUT_DIR, "graph.json")
        path = cand
    data = _load_json(path)
    if data is None:
        raise FileNotFoundError(path)
    return Graph.from_dict(data)
