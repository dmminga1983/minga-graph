"""Install the Claude Code skill and an optional git hook. Writes only local files."""

from __future__ import annotations

import os
import stat
from importlib import resources

HOOK_BEGIN = "# >>> minga-graph >>>"
HOOK_END = "# <<< minga-graph <<<"
HOOK_BODY = f"""{HOOK_BEGIN}
# Rebuild the knowledge graph after each commit (incremental, local, silent on success).
if command -v minga-graph >/dev/null 2>&1; then
  minga-graph build . --no-html --quiet >/dev/null 2>&1 &
fi
{HOOK_END}
"""


def skill_text() -> str:
    return resources.files("minga_graph").joinpath("skill/SKILL.md").read_text(encoding="utf-8")


def skill_dir(project: bool, root: str = ".") -> str:
    base = os.path.abspath(os.path.join(root, ".claude")) if project else os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(base, "skills", "minga-graph")


def install_skill(project: bool = False, root: str = ".") -> str:
    d = skill_dir(project, root)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "SKILL.md")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(skill_text())
    return path


def uninstall_skill(project: bool = False, root: str = ".") -> bool:
    path = os.path.join(skill_dir(project, root), "SKILL.md")
    if os.path.exists(path):
        os.remove(path)
        try:
            os.rmdir(os.path.dirname(path))
        except OSError:
            pass
        return True
    return False


def _hook_path(root: str, name: str = "post-commit") -> str:
    git = os.path.join(os.path.abspath(root), ".git")
    if not os.path.isdir(git):
        raise FileNotFoundError("not a git repository (no .git directory)")
    return os.path.join(git, "hooks", name)


def install_hook(root: str = ".") -> str:
    path = _hook_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = ""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        if HOOK_BEGIN in text:
            return path
    if not text:
        text = "#!/bin/sh\n"
    text = text.rstrip("\n") + "\n" + HOOK_BODY
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def uninstall_hook(root: str = ".") -> bool:
    path = _hook_path(root)
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    if HOOK_BEGIN not in text:
        return False
    start = text.index(HOOK_BEGIN)
    end = text.index(HOOK_END) + len(HOOK_END)
    text = (text[:start] + text[end:]).replace("\n\n\n", "\n\n")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return True
