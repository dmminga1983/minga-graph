"""GRAPH_REPORT.md generation (English or Russian)."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import List

from .model import Graph, INFERRED
from .query import import_cycles

T = {
    "en": {
        "title": "Graph report", "overview": "Overview", "files": "files", "nodes": "nodes", "edges": "edges",
        "extracted": "explicit in source (EXTRACTED)", "inferred": "resolved by name (INFERRED)",
        "kinds": "Node kinds", "rels": "Relations", "god": "Key nodes (most connected)",
        "god_hint": "Everything flows through these. Read them first.",
        "comms": "Subsystems (communities)", "bridges": "Surprising connections",
        "bridges_hint": "Rare links between otherwise separate subsystems. Often coupling worth reviewing.",
        "cycles": "Import cycles", "no_cycles": "No import cycles found.",
        "dead": "Possibly unused (candidates)",
        "dead_hint": "Functions/classes with no incoming calls, imports or references in the graph. Check entry points, frameworks and dynamic calls before deleting.",
        "notes": "Rationale and TODO notes", "secrets": "Possible secrets in source",
        "secrets_hint": "Values are masked. Move real secrets to .env (gitignored) and rotate them.",
        "questions": "Suggested questions", "size": "size", "deps": "Third-party packages",
        "how": "How to query",
    },
    "ru": {
        "title": "Отчёт по графу", "overview": "Обзор", "files": "файлов", "nodes": "узлов", "edges": "связей",
        "extracted": "явно в исходнике (EXTRACTED)", "inferred": "выведено по имени (INFERRED)",
        "kinds": "Типы узлов", "rels": "Типы связей", "god": "Ключевые узлы (больше всего связей)",
        "god_hint": "Через них проходит всё остальное. Читать в первую очередь.",
        "comms": "Подсистемы (сообщества)", "bridges": "Неожиданные связи",
        "bridges_hint": "Редкие связи между отдельными подсистемами. Часто это сцепление, которое стоит проверить.",
        "cycles": "Циклические импорты", "no_cycles": "Циклических импортов не найдено.",
        "dead": "Возможно не используется (кандидаты)",
        "dead_hint": "Функции и классы без входящих вызовов, импортов и ссылок в графе. Перед удалением проверьте точки входа, фреймворки и динамические вызовы.",
        "notes": "Пояснения и TODO в коде", "secrets": "Возможные секреты в исходниках",
        "secrets_hint": "Значения скрыты. Реальные секреты перенесите в .env (в .gitignore) и перевыпустите.",
        "questions": "Вопросы, которые стоит задать", "size": "размер", "deps": "Сторонние пакеты",
        "how": "Как задавать вопросы",
    },
}


def _nm(x) -> str:
    return x.file if x.kind == "file" else x.name


def _god_nodes(g: Graph, n: int = 12) -> List[str]:
    cands = [x for x in g.nodes.values() if x.kind not in ("file", "package", "note", "heading")]
    cands.sort(key=lambda x: (-g.degree(x.id), x.id))
    return [x.id for x in cands[:n] if g.degree(x.id) > 0]


def _bridges(g: Graph, n: int = 10):
    pair_count = Counter()
    pair_edges = defaultdict(list)
    for e in g.edges.values():
        if e.rel in ("contains", "depends_on"):
            continue
        a, b = g.nodes[e.src], g.nodes[e.dst]
        if b.kind == "package" or a.community == b.community:
            continue
        key = tuple(sorted((a.community, b.community)))
        pair_count[key] += 1
        pair_edges[key].append(e)
    out = []
    for key, cnt in pair_count.items():
        if cnt > 2:
            continue
        ca, cb = (g.communities.get(k, {}).get("size", 0) for k in key)
        if min(ca, cb) < 4:
            continue
        for e in pair_edges[key]:
            out.append((min(ca, cb), e))
    out.sort(key=lambda x: (-x[0], x[1].key()))
    return [e for _, e in out[:n]]


def _unused(g: Graph, n: int = 25) -> List[str]:
    res = []
    for x in g.nodes.values():
        if x.kind not in ("function", "class"):
            continue
        if x.name.startswith("_") or x.name in ("main",) or x.name.startswith("test") or "test" in x.file.lower():
            continue
        incoming = [e for e in g.in_edges(x.id) if e.rel != "contains"]
        if not incoming:
            res.append(x.id)
    res.sort()
    return res[:n]


def build_report(g: Graph, lang: str = "en", secret_findings=None) -> str:
    t = T.get(lang, T["en"])
    meta = g.meta
    edges = list(g.edges.values())
    conf = Counter(e.conf for e in edges if e.rel != "contains")
    nfiles = sum(1 for x in g.nodes.values() if x.kind == "file")
    lines = [f"# {t['title']}: {meta.get('root_name', '')}", ""]
    lines.append(f"_minga-graph {meta.get('version', '')} · {meta.get('built_at', '')}_")
    lines.append("")
    lines.append(f"## {t['overview']}")
    lines.append("")
    lines.append(f"- **{nfiles}** {t['files']}, **{len(g.nodes)}** {t['nodes']}, **{len(edges)}** {t['edges']}")
    total = sum(conf.values()) or 1
    lines.append(f"- {conf.get('EXTRACTED', 0)} ({100 * conf.get('EXTRACTED', 0) // total}%) {t['extracted']}; "
                 f"{conf.get(INFERRED, 0)} ({100 * conf.get(INFERRED, 0) // total}%) {t['inferred']}")
    kinds = Counter(x.kind for x in g.nodes.values())
    lines.append(f"- {t['kinds']}: " + ", ".join(f"{k} {v}" for k, v in kinds.most_common()))
    rels = Counter(e.rel for e in edges)
    lines.append(f"- {t['rels']}: " + ", ".join(f"{k} {v}" for k, v in rels.most_common()))
    lines.append("")

    god = _god_nodes(g)
    if god:
        lines += [f"## {t['god']}", "", f"_{t['god_hint']}_", "", "| # | node | kind | degree | location |", "|---|---|---|---|---|"]
        for i, nid in enumerate(god, 1):
            x = g.nodes[nid]
            lines.append(f"| {i} | `{x.name}` | {x.kind} | {g.degree(nid)} | {x.file}:{x.line} |")
        lines.append("")

    comms = sorted(g.communities.items(), key=lambda kv: -kv[1]["size"])
    big = [(c, info) for c, info in comms if info["size"] >= 3][:15]
    if big:
        lines += [f"## {t['comms']}", ""]
        for c, info in big:
            members = [x for x in g.nodes.values() if x.community == c and x.kind not in ("file", "note", "package")]
            members.sort(key=lambda x: (-g.degree(x.id), x.id))
            top = ", ".join(f"`{x.name}`" for x in members[:6])
            lines.append(f"- **{c}. {info['label']}** ({t['size']} {info['size']}): {top}")
        lines.append("")

    br = _bridges(g)
    if br:
        lines += [f"## {t['bridges']}", "", f"_{t['bridges_hint']}_", ""]
        for e in br:
            a, b = g.nodes[e.src], g.nodes[e.dst]
            lines.append(f"- `{_nm(a)}` ({g.communities[a.community]['label']}) --{e.rel}--> "
                         f"`{_nm(b)}` ({g.communities[b.community]['label']}) [{e.conf}] @ {e.at}")
        lines.append("")

    cyc = import_cycles(g)
    lines += [f"## {t['cycles']}", ""]
    if cyc:
        for comp in cyc[:10]:
            lines.append("- " + " ↔ ".join(c.replace("file:", "") for c in comp))
    else:
        lines.append(t["no_cycles"])
    lines.append("")

    un = _unused(g)
    if un:
        lines += [f"## {t['dead']}", "", f"_{t['dead_hint']}_", ""]
        for nid in un:
            x = g.nodes[nid]
            lines.append(f"- `{x.name}` ({x.kind}) {x.file}:{x.line}")
        lines.append("")

    notes = sorted((x for x in g.nodes.values() if x.kind == "note"), key=lambda x: (x.file, x.line))
    if notes:
        lines += [f"## {t['notes']}", ""]
        for x in notes[:30]:
            lines.append(f"- {x.file}:{x.line} {x.name}")
        if len(notes) > 30:
            lines.append(f"- … +{len(notes) - 30}")
        lines.append("")

    pkgs = sorted((x for x in g.nodes.values() if x.kind == "package"), key=lambda x: (-len(g.in_edges(x.id)), x.name))
    if pkgs:
        lines += [f"## {t['deps']}", "", ", ".join(f"`{x.name}` ({len(g.in_edges(x.id))})" for x in pkgs[:40]), ""]

    if secret_findings:
        lines += [f"## ⚠ {t['secrets']}", "", f"_{t['secrets_hint']}_", ""]
        for f in secret_findings[:50]:
            lines.append(f"- {f.path}:{f.line} {f.kind}: `{f.masked}`")
        lines.append("")

    qs = []
    if len(god) >= 2:
        qs.append(f'minga-graph path "{g.nodes[god[0]].name}" "{g.nodes[god[1]].name}"')
    if god:
        qs.append(f'minga-graph explain "{g.nodes[god[0]].name}"')
        qs.append(f'minga-graph impact "{g.nodes[god[0]].name}"')
    if br:
        qs.append(f'minga-graph path "{g.nodes[br[0].src].name}" "{g.nodes[br[0].dst].name}"')
    if big:
        qs.append(f'minga-graph query "{big[0][1]["label"].split(" · ")[0]}"')
    if qs:
        lines += [f"## {t['questions']}", "", "```"] + qs + ["```", ""]
    return "\n".join(lines)
