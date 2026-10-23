# minga-graph

Turn a codebase (code, docs, SQL schemas, dependency manifests) into a **local knowledge graph** you can query instead of grepping. Every edge says how it was found and points to the exact `file:line`. Built for Claude Code; works from any terminal and through MCP.

[Русская версия →](README.ru.md)

![graph.html: the minga-graph codebase, one function selected with its evidence](docs/graph.png)

## Why another one

minga-graph is inspired by the idea behind graphify and written from scratch with different priorities: **nothing leaves your machine and nothing outside your control runs.**

| | minga-graph |
|---|---|
| Runtime dependencies | **none** (Python standard library only) |
| Network access | **never**: no LLM calls, no cloud, no CDN, no update checks |
| Telemetry / query logs | **none** |
| Edge evidence | every edge has `EXTRACTED`/`INFERRED`, a reason and `file:line` |
| Wrong edges | ambiguous names are **not linked at all** instead of guessed |
| Extra analysis | impact (blast radius), graph diff, import cycles, unused-code candidates, secret scan |
| Questions | English **and Russian** (`minga-graph query "где проверяется токен"`) |
| Visualisation | one offline `graph.html` with a strict Content-Security-Policy |

Honest trade-off: fewer languages for now (see below). Adding languages is on the roadmap.

## Install

Needs Python 3.10+.

```bash
pipx install git+https://github.com/dmminga1983/minga-graph
minga-graph install          # adds the /minga-graph skill to Claude Code (~/.claude/skills)
```

Then in Claude Code: `/minga-graph .`

Without installing: `python -m minga_graph build .` from a clone.

## Use

```bash
minga-graph build .                                # incremental: only changed files are re-parsed
minga-graph query "how does the client reach the users table"
minga-graph explain ApiClient
minga-graph path Profile formatUser
minga-graph impact formatUser                      # what breaks if I change it
minga-graph diff                                   # structure changes since the previous build
minga-graph cycles
minga-graph secrets .                              # exit 1 if a hard-coded secret is found
```

Output in `minga-out/`:

```
graph.html        interactive graph, opens offline in any browser
GRAPH_REPORT.md   key nodes, subsystems, surprising links, cycles, unused candidates, secrets
graph.json        the full graph for scripts and the MCP server
```

Example:

```
$ minga-graph path Profile formatUser
Shortest path (4 hops):
  Profile --calls--> loadProfile --calls--> getUser --calls--> normalize --calls--> formatUser

Evidence:
  Profile --calls--> loadProfile [EXTRACTED] bound by import from ../api/client @ src/ui/Profile.jsx:6
  loadProfile --calls--> getUser [INFERRED] unique method name (receiver type unknown) @ src/api/client.ts:30
  getUser --calls--> normalize [EXTRACTED] this.normalize inside its class @ src/api/client.ts:14
  normalize --calls--> formatUser [EXTRACTED] bound by import from ../util/format @ src/api/client.ts:18
```

Exit codes: `0` ok, `1` error or secrets found, `3` ambiguous name (candidates are printed), `4` not found.

## What it understands

| Input | What becomes nodes and edges |
|---|---|
| Python (`.py`, `.pyi`) | modules, classes, functions, methods, nested functions; imports (incl. relative and function-local), calls, inheritance, decorators, callbacks passed as values, `# NOTE/WHY/TODO/FIXME/HACK/SECURITY` comments. Parsed with the exact `ast` module. |
| JavaScript / TypeScript (`.js .jsx .ts .tsx .mjs .cjs`) | ES imports, `require`, re-exports, classes, interfaces, functions, arrow functions, methods (incl. `#private`), `extends`/`implements`, calls, `this.x()` |
| SQL | tables, views, foreign keys (`REFERENCES`, `ALTER TABLE`), view dependencies |
| Markdown | heading tree, links to local files, `` `Symbol` `` mentions linked to code |
| Manifests | `package.json`, `pyproject.toml`, `requirements*.txt` dependencies |

Ignored by default: `.gitignore` rules (nested too), `.mingaignore`, `node_modules`, virtualenvs, build output, lock files, and **all `.env` files (never read)**.

## Edge confidence

- `EXTRACTED`: the source binds the name explicitly: same-file definition, an import binding, `self.x`/`this.x` in the defining class, SQL `REFERENCES`, a Markdown link.
- `INFERRED`: matched by a unique project-wide name (for example a method called on an object whose type is unknown). Open the `@ file:line` before relying on it for a risky change.
- Ambiguous or very generic names (`get`, `run`, `update`…) are dropped. No edge is better than a wrong edge.

## MCP server

```bash
claude mcp add minga-graph -- minga-graph mcp /path/to/project
```

Tools: `graph_query`, `graph_explain`, `graph_path`, `graph_impact`, `graph_stats`. Read-only, reloads the graph when it is rebuilt.

## Keep the graph fresh

```bash
minga-graph hook install      # git post-commit hook, rebuilds in the background
```

## Options

`--lang ru` Russian report · `--exclude PATTERN` extra ignore rule · `--resolution 1.5` smaller communities · `--node-limit N` nodes drawn in HTML · `--full` ignore cache · `--json` machine-readable summary.

## Owner control

This repository includes an owner-control kit (CODEOWNERS, an importable branch ruleset, safe SHA-pinned CI, Dependabot, private vulnerability reporting). See [docs/OWNER_CONTROL.md](docs/OWNER_CONTROL.md) for what it does and the 3-minute one-time setup. The kit can be copied into any repository.

## Roadmap

Go, Java, C#, PHP and Rust extractors; type-aware receiver resolution for `obj.method()`; cross-repo graphs.

## License

MIT. Not affiliated with Graphify Labs; this is an independent implementation.
