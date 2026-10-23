"""Command-line interface.

Exit codes: 0 ok, 1 error / secrets found, 3 ambiguous name, 4 node not found.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__


def _graph(args):
    from .build import load_graph
    try:
        return load_graph(args.graph)
    except FileNotFoundError:
        print(f"No graph found at {args.graph!r}. Run: minga-graph build <project>", file=sys.stderr)
        sys.exit(1)


def _find(g, name):
    from .query import Ambiguous, NotFound, find
    try:
        return find(g, name)
    except Ambiguous as exc:
        print(f"Ambiguous name {name!r}. Candidates:", file=sys.stderr)
        for c in exc.candidates[:30]:
            print(f"  {c}", file=sys.stderr)
        sys.exit(3)
    except NotFound:
        print(f"No node named {name!r}.", file=sys.stderr)
        sys.exit(4)


def cmd_build(args):
    from .build import build
    log = (lambda *a, **k: None) if args.quiet else print
    s = build(args.path, args.out, lang=args.lang, html=not args.no_html, excludes=args.exclude or (),
              resolution=args.resolution, node_limit=args.node_limit, full=args.full, log=log)
    if args.json:
        print(json.dumps(s, indent=1))
    elif not args.quiet:
        print(f"minga-graph: {s['files']} files ({s['extracted']} parsed, {s['cached']} cached) -> "
              f"{s['nodes']} nodes, {s['edges']} edges, {s['communities']} communities in {s['seconds']}s")
        print(f"  refs resolved {s['resolved']}/{s['refs']} (unresolved or ambiguous refs are dropped, never guessed)")
        if s["secrets"]:
            print(f"  ⚠ {s['secrets']} possible secret(s) in source, see GRAPH_REPORT.md or run: minga-graph secrets {args.path}")
        print(f"  output: {s['out']}{os.sep}{{graph.json, GRAPH_REPORT.md{', graph.html' if not args.no_html else ''}}}")
    return 0


def cmd_explain(args):
    from .query import explain
    g = _graph(args)
    print(explain(g, _find(g, args.name), args.limit))
    return 0


def cmd_path(args):
    from .query import fmt_path, shortest_path
    g = _graph(args)
    a, b = _find(g, args.a), _find(g, args.b)
    p = shortest_path(g, a, b, skip_contains=args.no_contains)
    if not p:
        print(f"No path between {args.a!r} and {args.b!r}.")
        return 4
    print(fmt_path(g, p))
    return 0


def cmd_query(args):
    from .query import fmt_subgraph, question_subgraph
    g = _graph(args)
    nodes, edges = question_subgraph(g, args.question, args.budget)
    if args.json:
        print(json.dumps({"nodes": [g.nodes[n].to_dict() for n in nodes], "edges": [e.to_dict() for e in edges]},
                         ensure_ascii=False, indent=1))
    else:
        print(fmt_subgraph(g, args.question, nodes, edges))
    return 0 if nodes else 4


def cmd_impact(args):
    from .query import fmt_impact, impact
    g = _graph(args)
    nid = _find(g, args.name)
    print(fmt_impact(g, nid, impact(g, nid, args.depth)))
    return 0


def cmd_diff(args):
    from .build import load_graph
    from .query import diff, fmt_diff
    base = args.graph if os.path.isdir(args.graph) else os.path.dirname(args.graph)
    if os.path.isdir(os.path.join(base, "minga-out")):
        base = os.path.join(base, "minga-out")
    old_path = args.old or os.path.join(base, "graph.prev.json")
    try:
        old, new = load_graph(old_path), load_graph(args.graph)
    except FileNotFoundError as exc:
        print(f"Missing graph: {exc}. Build twice (or pass --old FILE) to compare.", file=sys.stderr)
        return 1
    print(fmt_diff(diff(old, new)))
    return 0


def cmd_cycles(args):
    from .query import import_cycles
    g = _graph(args)
    cyc = import_cycles(g, 100)
    if not cyc:
        print("No import cycles.")
        return 0
    for c in cyc:
        print(" <-> ".join(x.replace("file:", "") for x in c))
    return 0


def cmd_secrets(args):
    from .scan import read_text, walk
    from .secrets import scan_text
    hits = []
    for rel, abspath in walk(args.path):
        text = read_text(abspath)
        if text:
            hits += scan_text(text, rel)
    for h in hits:
        print(h)
    if hits:
        print(f"\n{len(hits)} possible secret(s). Values are masked. Move them to .env (gitignored) and rotate.", file=sys.stderr)
        return 1
    print("No secrets found.")
    return 0


def cmd_install(args):
    from .install import install_skill
    path = install_skill(project=args.project)
    print(f"Skill installed: {path}")
    print("In Claude Code type:  /minga-graph .")
    print("Optional MCP server:  claude mcp add minga-graph -- minga-graph mcp <project>")
    return 0


def cmd_uninstall(args):
    from .install import uninstall_skill
    print("Removed." if uninstall_skill(project=args.project) else "Skill was not installed.")
    return 0


def cmd_hook(args):
    from .install import install_hook, uninstall_hook
    try:
        if args.action == "install":
            print(f"Hook installed: {install_hook(args.path)}")
        else:
            print("Hook removed." if uninstall_hook(args.path) else "No minga-graph hook found.")
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def cmd_mcp(args):
    from .mcp_server import serve
    return serve(args.path)


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="minga-graph", description="Local, explainable knowledge graph of a codebase. No network, no telemetry.")
    p.add_argument("--version", action="version", version=f"minga-graph {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def graph_arg(sp):
        sp.add_argument("--graph", "-g", default=".", help="project dir, minga-out dir or graph.json (default: .)")

    b = sub.add_parser("build", help="build or incrementally update the graph")
    b.add_argument("path", nargs="?", default=".")
    b.add_argument("--out", "-o", help="output dir (default: <path>/minga-out)")
    b.add_argument("--lang", choices=["en", "ru"], default=os.environ.get("MINGA_GRAPH_LANG", "en"), help="report language")
    b.add_argument("--no-html", action="store_true")
    b.add_argument("--exclude", "-x", action="append", help="extra ignore pattern (gitignore syntax), repeatable")
    b.add_argument("--resolution", type=float, default=1.0, help="community granularity (>1 = smaller communities)")
    b.add_argument("--node-limit", type=int, default=4000, help="max nodes drawn in graph.html (0 = all)")
    b.add_argument("--full", action="store_true", help="ignore the cache and re-parse everything")
    b.add_argument("--quiet", "-q", action="store_true")
    b.add_argument("--json", action="store_true", help="print the build summary as JSON")
    b.set_defaults(fn=cmd_build)

    e = sub.add_parser("explain", help="explain one node and all its connections")
    e.add_argument("name"); graph_arg(e)
    e.add_argument("--limit", type=int, default=60)
    e.set_defaults(fn=cmd_explain)

    pa = sub.add_parser("path", help="shortest path between two nodes")
    pa.add_argument("a"); pa.add_argument("b"); graph_arg(pa)
    pa.add_argument("--no-contains", action="store_true", help="ignore structural 'contains' edges")
    pa.set_defaults(fn=cmd_path)

    q = sub.add_parser("query", help="relevant subgraph for a plain-language question (EN/RU)")
    q.add_argument("question"); graph_arg(q)
    q.add_argument("--budget", type=int, default=40)
    q.add_argument("--json", action="store_true")
    q.set_defaults(fn=cmd_query)

    im = sub.add_parser("impact", help="what depends on a node (blast radius of a change)")
    im.add_argument("name"); graph_arg(im)
    im.add_argument("--depth", type=int, default=3)
    im.set_defaults(fn=cmd_impact)

    d = sub.add_parser("diff", help="what changed in the graph since the previous build")
    graph_arg(d)
    d.add_argument("--old", help="older graph.json to compare against")
    d.set_defaults(fn=cmd_diff)

    c = sub.add_parser("cycles", help="list import cycles")
    graph_arg(c)
    c.set_defaults(fn=cmd_cycles)

    s = sub.add_parser("secrets", help="scan a tree for hard-coded secrets (exit 1 if any)")
    s.add_argument("path", nargs="?", default=".")
    s.set_defaults(fn=cmd_secrets)

    i = sub.add_parser("install", help="install the /minga-graph skill for Claude Code")
    i.add_argument("--project", action="store_true", help="install into ./.claude instead of ~/.claude")
    i.set_defaults(fn=cmd_install)
    u = sub.add_parser("uninstall", help="remove the skill")
    u.add_argument("--project", action="store_true")
    u.set_defaults(fn=cmd_uninstall)

    h = sub.add_parser("hook", help="git post-commit hook that keeps the graph fresh")
    h.add_argument("action", choices=["install", "uninstall"])
    h.add_argument("path", nargs="?", default=".")
    h.set_defaults(fn=cmd_hook)

    m = sub.add_parser("mcp", help="run the read-only MCP stdio server")
    m.add_argument("path", nargs="?", default=".")
    m.set_defaults(fn=cmd_mcp)
    return p


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    args = make_parser().parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
