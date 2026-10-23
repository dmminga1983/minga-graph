---
name: minga-graph
description: Build and query a local knowledge graph of the current codebase (code, docs, SQL, manifests) instead of grepping. Use for "how is X connected to Y", "what breaks if I change X", architecture overviews, finding where something lives, or when the user types /minga-graph.
---

# minga-graph

A local, deterministic knowledge graph of the project. Nothing leaves the machine: no network, no telemetry, no query logs.

## When invoked as `/minga-graph [path]`

1. Check the CLI exists: `minga-graph --version`. If missing, tell the user to install it once:
   `pipx install git+https://github.com/dmminga1983/minga-graph` (or `pip install --user git+https://github.com/dmminga1983/minga-graph`), and stop.
2. Build (incremental, fast on re-runs): `minga-graph build <path or .>`
   Add `--lang ru` if the user writes in Russian.
3. Read `minga-out/GRAPH_REPORT.md` and give the user a short overview: key nodes, subsystems, import cycles, surprising connections, possible secrets (if any, put this first).
4. Mention that `minga-out/graph.html` opens in any browser for an interactive view.

## Answering questions about the code

Prefer graph queries over reading many files. Each command prints `file:line` evidence, so open only the files that matter.

| Need | Command |
|---|---|
| Where is the relevant code for a question | `minga-graph query "how does auth reach the database"` |
| Everything about one symbol/file/table | `minga-graph explain "UserService"` |
| How two things connect | `minga-graph path "LoginForm" "users"` |
| What breaks if I change X | `minga-graph impact "parse_config" --depth 3` |
| What changed since the last build | `minga-graph diff` |
| Import cycles | `minga-graph cycles` |
| Hard-coded secrets before a push | `minga-graph secrets .` |

Exit code 3 means the name is ambiguous: pick one of the printed ids (e.g. `sym:src/a.py::Foo`) and retry. Exit code 4 means not found: try a shorter or different name, or `query`.

## Reading edges

- `EXTRACTED`: stated explicitly in the source (definition, explicit import binding, SQL REFERENCES, markdown link).
- `INFERRED`: matched by a unique project-wide name. Verify by opening the `@ file:line` location before relying on it for risky changes.
- Ambiguous names are never linked, so a missing edge is not proof of no relationship: confirm with a targeted search if it matters.

## After editing code

Run `minga-graph build .` again (only changed files are re-parsed) and `minga-graph diff` to show what the change did to the structure.
