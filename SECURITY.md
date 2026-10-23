# Security policy

## Design guarantees

- **No network access.** minga-graph never opens a socket. It has zero runtime dependencies (Python standard library only), so there is no third-party code to compromise.
- **No telemetry, no query logs.** Nothing about your code or your questions is recorded anywhere except the output folder you chose.
- **Secrets stay out.** `.env` files are never read. Text stored in the graph (docstrings, comments) is redacted with the same detector that powers `minga-graph secrets`.
- **Read-only MCP server.** It only reads `graph.json`; it cannot run commands or modify files.
- **Offline HTML.** `graph.html` loads nothing from the internet and ships a strict Content-Security-Policy.

## Reporting a vulnerability

Please use GitHub's **private vulnerability reporting** (Security tab, "Report a vulnerability").
Do not open a public issue for security problems.

## Supply chain

- CI uses only the `pull_request` trigger with a read-only token; actions are pinned to commit SHAs.
- Releases are built from tagged commits on `main`, which is protected by the `main-protection` ruleset and CODEOWNERS.
