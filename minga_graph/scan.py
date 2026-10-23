"""Walk a project tree, honouring .gitignore, .mingaignore and safe defaults."""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from typing import Iterator, List, Optional, Sequence, Tuple

from .secrets import is_env_file

DEFAULT_EXCLUDE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".tox", ".nox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    ".next", ".nuxt", ".cache", "coverage", ".idea", ".vscode", "minga-out",
    "target", "vendor", ".gradle", ".terraform", "site-packages", ".eggs",
}
DEFAULT_EXCLUDE_FILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
                         "uv.lock", "Cargo.lock", "composer.lock", "Gemfile.lock"}
MAX_FILE_BYTES = 1_500_000


@dataclass
class _Rule:
    base: str          # directory (relative, posix) the rule file lives in
    pattern: str
    negate: bool
    dir_only: bool
    anchored: bool


def _parse_ignore(text: str, base: str) -> List[_Rule]:
    rules = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.startswith("#"):
            continue
        negate = line.startswith("!")
        if negate:
            line = line[1:]
        line = line.replace("\\ ", " ")
        dir_only = line.endswith("/")
        line = line.rstrip("/")
        anchored = line.startswith("/") or "/" in line
        line = line.lstrip("/")
        if line:
            rules.append(_Rule(base, line, negate, dir_only, anchored))
    return rules


def _rule_matches(rule: _Rule, rel: str, is_dir: bool) -> bool:
    if rule.dir_only and not is_dir:
        return False
    if rule.base:
        if not (rel == rule.base or rel.startswith(rule.base + "/")):
            return False
        rel = rel[len(rule.base) + 1:]
    if rule.anchored:
        pat = rule.pattern
        if fnmatch.fnmatchcase(rel, pat):
            return True
        if pat.startswith("**/") and fnmatch.fnmatchcase(rel, pat[3:]):
            return True
        return False
    return fnmatch.fnmatchcase(rel.rsplit("/", 1)[-1], rule.pattern)


def _ignored(rules: Sequence[_Rule], rel: str, is_dir: bool) -> bool:
    result = False
    for r in rules:
        if _rule_matches(r, rel, is_dir):
            result = not r.negate
    return result


def walk(root: str, extra_excludes: Optional[Sequence[str]] = None) -> Iterator[Tuple[str, str]]:
    """Yield (relative_posix_path, absolute_path) for every candidate file."""
    root = os.path.abspath(root)
    base_rules: List[_Rule] = []
    for name in (".mingaignore",):
        p = os.path.join(root, name)
        if os.path.isfile(p):
            base_rules += _parse_ignore(_read(p), "")
    for pat in extra_excludes or ():
        base_rules += _parse_ignore(pat, "")

    def _walk(dir_abs: str, dir_rel: str, rules: List[_Rule]):
        gi = os.path.join(dir_abs, ".gitignore")
        if os.path.isfile(gi):
            rules = rules + _parse_ignore(_read(gi), dir_rel)
        try:
            entries = sorted(os.scandir(dir_abs), key=lambda e: e.name)
        except OSError:
            return
        for entry in entries:
            rel = f"{dir_rel}/{entry.name}" if dir_rel else entry.name
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    if entry.name in DEFAULT_EXCLUDE_DIRS or entry.name.endswith(".egg-info"):
                        continue
                    if _ignored(rules, rel, True):
                        continue
                    yield from _walk(entry.path, rel, rules)
                elif entry.is_file():
                    if entry.name in DEFAULT_EXCLUDE_FILES or is_env_file(entry.name):
                        continue
                    if _ignored(rules, rel, False):
                        continue
                    if entry.stat().st_size > MAX_FILE_BYTES:
                        continue
                    yield rel, entry.path
            except OSError:
                continue

    yield from _walk(root, "", base_rules)


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def read_text(path: str) -> Optional[str]:
    """Read a text file; return None for binaries."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    if b"\x00" in data[:8192]:
        return None
    for enc in ("utf-8", "cp1251", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return None
