import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIXTURE = os.path.join(HERE, "fixtures", "mixed")
sys.path.insert(0, ROOT)

from minga_graph.build import build, load_graph  # noqa: E402
from minga_graph.extractors import js_ext, python_ext  # noqa: E402
from minga_graph.mcp_server import Server  # noqa: E402
from minga_graph.query import (Ambiguous, NotFound, find, impact, import_cycles,  # noqa: E402
                               question_subgraph, shortest_path)
from minga_graph.secrets import redact, scan_text  # noqa: E402


class FixtureGraph(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp()
        cls.summary = build(FIXTURE, cls.out, log=lambda *a: None)
        cls.g = load_graph(cls.out)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def edge(self, src, dst, rel):
        return self.g.edges.get((src, dst, rel))

    def test_outputs_written(self):
        for f in ("graph.json", "GRAPH_REPORT.md", "graph.html", "cache.json"):
            self.assertTrue(os.path.exists(os.path.join(self.out, f)), f)
        with open(os.path.join(self.out, "graph.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["graph"]["schema_version"], 1)

    def test_html_is_offline(self):
        with open(os.path.join(self.out, "graph.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertNotIn("http://", html.replace("http://www.w3.org", ""))
        self.assertNotIn("https://", html)
        self.assertIn("Content-Security-Policy", html)

    def test_ts_import_binding_is_extracted(self):
        e = self.edge("sym:src/api/client.ts::ApiClient.normalize", "sym:src/util/format.ts::formatUser", "calls")
        self.assertIsNotNone(e)
        self.assertEqual(e.conf, "EXTRACTED")
        self.assertTrue(e.at.startswith("src/api/client.ts:"))

    def test_this_method_and_inheritance(self):
        self.assertIsNotNone(self.edge("sym:src/api/client.ts::ApiClient.getUser",
                                       "sym:src/api/client.ts::ApiClient.normalize", "calls"))
        self.assertIsNotNone(self.edge("sym:src/api/client.ts::ApiClient", "sym:src/api/client.ts::BaseClient", "inherits"))

    def test_strings_are_not_calls(self):
        names = {e.dst for e in self.g.out_edges("sym:src/api/client.ts::ApiClient.getUser")}
        self.assertFalse(any("call(" in n for n in names))

    def test_jsx_cross_file(self):
        self.assertIsNotNone(self.edge("sym:src/ui/Profile.jsx::Profile", "sym:src/api/client.ts::loadProfile", "calls"))
        self.assertIsNotNone(self.edge("file:src/ui/Profile.jsx", "file:src/api/client.ts", "imports"))

    def test_external_packages(self):
        self.assertIn("pkg:axios", self.g.nodes)
        self.assertIn("pkg:react", self.g.nodes)

    def test_sql(self):
        self.assertIsNotNone(self.edge("table:orders", "table:users", "foreign_key"))
        self.assertIsNotNone(self.edge("table:big_orders", "table:orders", "references"))

    def test_markdown(self):
        self.assertIsNotNone(self.edge("doc:docs/ARCH.md#data", "file:db/schema.sql", "links_to"))
        e = self.edge("doc:docs/ARCH.md#architecture", "sym:src/api/client.ts::ApiClient", "mentions")
        self.assertIsNotNone(e)
        self.assertEqual(e.conf, "INFERRED")

    def test_python(self):
        self.assertIsNotNone(self.edge("sym:svc.py::AuditRepo", "sym:svc.py::Repo", "inherits"))
        self.assertIsNotNone(self.edge("sym:svc.py::Repo.save", "sym:svc.py::Repo._write", "calls"))
        notes = [n for n in self.g.nodes.values() if n.kind == "note"]
        self.assertTrue(any("append-only" in n.doc for n in notes))
        self.assertNotIn("pkg:os", self.g.nodes)  # stdlib is not a dependency

    def test_find_ambiguous_and_missing(self):
        with self.assertRaises(Ambiguous):
            find(self.g, "save")
        with self.assertRaises(NotFound):
            find(self.g, "definitely_not_here")
        self.assertEqual(find(self.g, "Repo.save"), "sym:svc.py::Repo.save")

    def test_path_prefers_semantic_edges(self):
        p = shortest_path(self.g, find(self.g, "Profile"), find(self.g, "formatUser"))
        rels = [e.rel for _, e in p[1:]]
        self.assertNotIn("contains", rels)

    def test_impact(self):
        rows = impact(self.g, find(self.g, "formatUser"))
        srcs = {s for _, s, _ in rows}
        self.assertIn("sym:src/api/client.ts::ApiClient.normalize", srcs)

    def test_query_ru(self):
        nodes, _ = question_subgraph(self.g, "где таблица пользователей и заказов")
        self.assertTrue({"table:users", "table:orders"} & set(nodes))

    def test_incremental_cache(self):
        s2 = build(FIXTURE, self.out, log=lambda *a: None)
        self.assertEqual(s2["extracted"], 0)
        self.assertEqual(s2["cached"], self.summary["files"])

    def test_mcp(self):
        srv = Server(self.out)
        r = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(r["result"]["serverInfo"]["name"], "minga-graph")
        r = srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(len(r["result"]["tools"]), 5)
        r = srv.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "graph_explain", "arguments": {"name": "ApiClient"}}})
        self.assertIn("BaseClient", r["result"]["content"][0]["text"])
        self.assertIsNone(srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))


class Extractors(unittest.TestCase):
    def test_python_relative_imports_and_closures(self):
        src = "from .b import f as g\n\ndef outer():\n    def inner():\n        return 1\n    return inner() + g()\n"
        r = python_ext.extract("pkg/a.py", src)
        self.assertEqual(r["aliases"]["g"], "pkg.b.f")
        ids = {n["id"] for n in r["nodes"]}
        self.assertIn("sym:pkg/a.py::outer.inner", ids)

    def test_python_syntax_error_does_not_crash(self):
        r = python_ext.extract("bad.py", "def (:\n")
        self.assertEqual(len(r["nodes"]), 1)

    def test_js_lexer_preserves_offsets(self):
        src = "const a = 'x(y)'; // call(z)\n/* f() */ g();"
        nc, code = js_ext._lex(src)
        self.assertEqual(len(code), len(src))
        self.assertNotIn("call", code)
        self.assertIn("g()", code)


class Secrets(unittest.TestCase):
    def test_detects_and_masks(self):
        token = "ghp_" + "A1b2C3d4E5" * 4  # built at runtime: no real token in the repo
        hits = scan_text(f"TOKEN = '{token}'\n", "x.py")
        self.assertTrue(hits)
        self.assertNotIn(token, str(hits[0]))

    def test_redact(self):
        key = "sk-ant-" + "x9" * 20
        self.assertNotIn(key, redact(f"use {key} here"))

    def test_env_lookup_is_not_a_finding(self):
        self.assertEqual(scan_text("password = os.environ['DB_PASSWORD']\n"), [])
        self.assertEqual(scan_text("api_key = 'your_api_key_here'\n"), [])

    def test_env_files_are_never_scanned(self):
        d = tempfile.mkdtemp()
        try:
            with open(os.path.join(d, ".env"), "w") as fh:
                fh.write("SECRET_KEY='" + "Z" * 30 + "'\n")
            with open(os.path.join(d, "app.py"), "w") as fh:
                fh.write("x = 1\n")
            s = build(d, os.path.join(d, "minga-out"), log=lambda *a: None)
            self.assertEqual(s["secrets"], 0)
            self.assertEqual(s["files"], 1)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class Cycles(unittest.TestCase):
    def test_import_cycle_detected(self):
        d = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(d, "p"))
            open(os.path.join(d, "p", "__init__.py"), "w").close()
            with open(os.path.join(d, "p", "a.py"), "w") as fh:
                fh.write("from p import b\n")
            with open(os.path.join(d, "p", "b.py"), "w") as fh:
                fh.write("import p.a\n")
            build(d, os.path.join(d, "out"), log=lambda *a: None)
            g = load_graph(os.path.join(d, "out"))
            cyc = import_cycles(g)
            self.assertIn(["file:p/a.py", "file:p/b.py"], cyc)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class Cli(unittest.TestCase):
    def test_cli_end_to_end(self):
        out = tempfile.mkdtemp()
        try:
            env = dict(os.environ, PYTHONPATH=ROOT)
            run = lambda *a: subprocess.run([sys.executable, "-m", "minga_graph", *a], capture_output=True,
                                            text=True, env=env, cwd=ROOT)
            self.assertEqual(run("build", FIXTURE, "-o", out, "-q").returncode, 0)
            r = run("explain", "save", "-g", out)
            self.assertEqual(r.returncode, 3)
            r = run("explain", "nope_nope", "-g", out)
            self.assertEqual(r.returncode, 4)
            r = run("path", "Profile", "formatUser", "-g", out)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("formatUser", r.stdout)
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
