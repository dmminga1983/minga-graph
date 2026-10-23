"""SQL schema extractor: tables, views, foreign keys, view dependencies."""

from __future__ import annotations

import re

NAME = r"(?:[`\"\[]?[\w$]+[`\"\]]?\.)?[`\"\[]?([\w$]+)[`\"\]]?"
CREATE_TABLE = re.compile(r"\bcreate\s+(?:or\s+replace\s+)?(?:temporary\s+|temp\s+|unlogged\s+)?table\s+(?:if\s+not\s+exists\s+)?" + NAME, re.I)
CREATE_VIEW = re.compile(r"\bcreate\s+(?:or\s+replace\s+)?(?:materialized\s+)?view\s+(?:if\s+not\s+exists\s+)?" + NAME + r"[\s\S]*?\bas\b([\s\S]*?)(?:;|$)", re.I)
REFERENCES = re.compile(r"\breferences\s+" + NAME, re.I)
ALTER_FK = re.compile(r"\balter\s+table\s+(?:only\s+)?(?:if\s+exists\s+)?" + NAME + r"[\s\S]*?\breferences\s+" + NAME, re.I)
FROM_JOIN = re.compile(r"\b(?:from|join)\s+" + NAME, re.I)
SQL_KEYWORDS = {"select", "lateral", "unnest", "values", "only"}


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*[\s\S]*?\*/", lambda m: "\n" * m.group(0).count("\n"), sql)
    return re.sub(r"--[^\n]*", "", sql)


def extract(relpath: str, text: str) -> dict:
    from . import file_node

    sql = _strip_comments(text)
    fid = f"file:{relpath}"
    res = {"nodes": [file_node(relpath, text.count("\n") + 1)], "edges": [], "refs": [], "aliases": {}, "module": ""}

    def line(pos):
        return sql.count("\n", 0, pos) + 1

    statements = []
    for m in CREATE_TABLE.finditer(sql):
        # statement body: up to the matching closing paren + ;
        end = sql.find(";", m.end())
        end = len(sql) if end == -1 else end
        statements.append(("table", m.group(1).lower(), m.start(), sql[m.end():end]))
    for m in CREATE_VIEW.finditer(sql):
        statements.append(("view", m.group(1).lower(), m.start(), m.group(2)))

    for kind, name, pos, body in statements:
        tid = f"table:{name}"
        res["nodes"].append({"id": tid, "kind": kind, "name": name, "file": relpath, "line": line(pos)})
        res["edges"].append({"src": fid, "dst": tid, "rel": "contains", "conf": "EXTRACTED",
                             "why": f"CREATE {kind.upper()}", "at": f"{relpath}:{line(pos)}"})
        if kind == "table":
            for r in REFERENCES.finditer(body):
                res["refs"].append({"src": tid, "name": f"table:{r.group(1).lower()}", "rel": "foreign_key",
                                    "at": f"{relpath}:{line(pos)}", "exact": True})
        else:
            for r in FROM_JOIN.finditer(body):
                t = r.group(1).lower()
                if t not in SQL_KEYWORDS:
                    res["refs"].append({"src": tid, "name": f"table:{t}", "rel": "references",
                                        "at": f"{relpath}:{line(pos)}", "exact": True})
    for m in ALTER_FK.finditer(sql):
        res["refs"].append({"src": f"table:{m.group(1).lower()}", "name": f"table:{m.group(2).lower()}",
                            "rel": "foreign_key", "at": f"{relpath}:{line(m.start())}", "exact": True})
    return res
