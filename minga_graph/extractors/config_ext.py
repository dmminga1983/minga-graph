"""Dependency manifests: package.json, pyproject.toml, requirements*.txt."""

from __future__ import annotations

import json
import re

try:  # Python 3.11+
    import tomllib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


def _base(relpath, text):
    from . import file_node
    return {"nodes": [file_node(relpath, text.count("\n") + 1)], "edges": [], "refs": [], "aliases": {}, "module": ""}


def _dep(res, relpath, name, why, line=1):
    name = name.strip().lower()
    if not name:
        return
    pid = f"pkg:{name}"
    res["nodes"].append({"id": pid, "kind": "package", "name": name})
    res["edges"].append({"src": f"file:{relpath}", "dst": pid, "rel": "depends_on", "conf": "EXTRACTED",
                         "why": why, "at": f"{relpath}:{line}"})


def _line_of(text, needle):
    idx = text.find(needle)
    return text.count("\n", 0, idx) + 1 if idx >= 0 else 1


def extract_package_json(relpath: str, text: str) -> dict:
    res = _base(relpath, text)
    try:
        data = json.loads(text)
    except ValueError:
        return res
    if not isinstance(data, dict):
        return res
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        deps = data.get(section) or {}
        if isinstance(deps, dict):
            for name in sorted(deps):
                _dep(res, relpath, name, f"package.json {section}", _line_of(text, f'"{name}"'))
    return res


_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._\-]*)")


def extract_requirements(relpath: str, text: str) -> dict:
    res = _base(relpath, text)
    for i, line in enumerate(text.splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = _REQ_NAME.match(line)
        if m:
            _dep(res, relpath, m.group(1), "requirements entry", i)
    return res


def extract_pyproject(relpath: str, text: str) -> dict:
    res = _base(relpath, text)
    if tomllib is None:
        return res
    try:
        data = tomllib.loads(text)
    except Exception:
        return res
    project = data.get("project", {}) if isinstance(data, dict) else {}
    deps = list(project.get("dependencies", []) or [])
    for group in (project.get("optional-dependencies") or {}).values():
        deps += list(group or [])
    poetry = data.get("tool", {}).get("poetry", {}) if isinstance(data.get("tool"), dict) else {}
    deps += [k for k in (poetry.get("dependencies") or {}) if k.lower() != "python"]
    for spec in deps:
        m = _REQ_NAME.match(str(spec))
        if m:
            _dep(res, relpath, m.group(1), "pyproject dependency", _line_of(text, m.group(1)))
    return res
