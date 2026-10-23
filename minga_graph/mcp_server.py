"""Minimal MCP stdio server (JSON-RPC 2.0, newline-delimited). Local only, read-only.

Register in Claude Code:
    claude mcp add minga-graph -- minga-graph mcp /path/to/project
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

from . import __version__
from .build import load_graph
from .query import (Ambiguous, NotFound, explain, find, fmt_impact, fmt_path, fmt_subgraph, impact,
                    question_subgraph, shortest_path)

TOOLS = [
    {"name": "graph_query", "description": "Return the part of the code knowledge graph relevant to a plain-language question (nodes, edges, file:line evidence). Use before grepping the codebase.",
     "inputSchema": {"type": "object", "properties": {"question": {"type": "string"}, "budget": {"type": "integer", "default": 40}}, "required": ["question"]}},
    {"name": "graph_explain", "description": "Explain one node (class, function, file, table, heading): location, doc, every connection with its evidence.",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "graph_path", "description": "Shortest path between two nodes, hop by hop, with evidence for every edge.",
     "inputSchema": {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}}, "required": ["a", "b"]}},
    {"name": "graph_impact", "description": "What depends on a node (transitive callers, importers, subclasses). Use before changing or deleting code.",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "depth": {"type": "integer", "default": 3}}, "required": ["name"]}},
    {"name": "graph_stats", "description": "Size of the graph and when it was built.",
     "inputSchema": {"type": "object", "properties": {}}},
]


class Server:
    def __init__(self, root: str):
        self.root = root
        self._g = None
        self._mtime = None

    @property
    def g(self):
        path = os.path.join(self.root, "graph.json") if os.path.exists(os.path.join(self.root, "graph.json")) \
            else os.path.join(self.root, "minga-out", "graph.json")
        mtime = os.path.getmtime(path) if os.path.exists(path) else None
        if self._g is None or mtime != self._mtime:
            self._g = load_graph(path)
            self._mtime = mtime
        return self._g

    def call(self, name: str, args: Dict[str, Any]) -> str:
        g = self.g
        try:
            if name == "graph_query":
                nodes, edges = question_subgraph(g, args["question"], int(args.get("budget", 40)))
                return fmt_subgraph(g, args["question"], nodes, edges)
            if name == "graph_explain":
                return explain(g, find(g, args["name"]))
            if name == "graph_path":
                a, b = find(g, args["a"]), find(g, args["b"])
                p = shortest_path(g, a, b)
                return fmt_path(g, p) if p else f"No path between {args['a']} and {args['b']}."
            if name == "graph_impact":
                nid = find(g, args["name"])
                return fmt_impact(g, nid, impact(g, nid, int(args.get("depth", 3))))
            if name == "graph_stats":
                return json.dumps(g.meta, ensure_ascii=False, indent=1)
        except Ambiguous as exc:
            return f"Ambiguous name {exc.name!r}. Candidates:\n" + "\n".join("  " + c for c in exc.candidates[:30])
        except NotFound as exc:
            return f"No node named {exc}."
        raise KeyError(name)

    def handle(self, msg: Dict[str, Any]):
        method = msg.get("method")
        mid = msg.get("id")
        if mid is None:  # notification
            return None
        try:
            if method == "initialize":
                ver = (msg.get("params") or {}).get("protocolVersion", "2025-06-18")
                result = {"protocolVersion": ver, "capabilities": {"tools": {}},
                          "serverInfo": {"name": "minga-graph", "version": __version__}}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                p = msg.get("params") or {}
                try:
                    text = self.call(p.get("name", ""), p.get("arguments") or {})
                    result = {"content": [{"type": "text", "text": text}], "isError": False}
                except KeyError as exc:
                    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool or argument: {exc}"}}
                except FileNotFoundError:
                    result = {"content": [{"type": "text", "text": "No graph yet. Run: minga-graph build <project>"}], "isError": True}
            else:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
            return {"jsonrpc": "2.0", "id": mid, "result": result}
        except Exception as exc:  # pragma: no cover
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(exc)}}


def serve(root: str) -> int:
    srv = Server(os.path.abspath(root))
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        resp = srv.handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0
