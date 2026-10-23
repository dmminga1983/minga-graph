"""Language extractors.

Each extractor takes (relpath, text) and returns a plain-dict result:

    {
      "nodes": [ {id, kind, name, file, line, end_line, doc}, ... ],
      "edges": [ {src, dst, rel, conf, why, at}, ... ],          # fully local edges
      "refs":  [ {src, name, rel, at, scope?, spec?}, ... ],      # need cross-file resolution
      "aliases": {local_name: qualified_target},                  # import aliases in this file
      "module": "dotted.module.name" or "",
    }

Results are JSON-serialisable so they can be cached per file hash.
"""

from __future__ import annotations

import os
from typing import Callable, Dict, Optional

from . import python_ext, js_ext, markdown_ext, sql_ext, config_ext

Extractor = Callable[[str, str], dict]

_BY_EXT: Dict[str, Extractor] = {
    ".py": python_ext.extract, ".pyi": python_ext.extract,
    ".js": js_ext.extract, ".jsx": js_ext.extract, ".mjs": js_ext.extract, ".cjs": js_ext.extract,
    ".ts": js_ext.extract, ".tsx": js_ext.extract, ".mts": js_ext.extract, ".cts": js_ext.extract,
    ".md": markdown_ext.extract, ".markdown": markdown_ext.extract, ".mdx": markdown_ext.extract,
    ".sql": sql_ext.extract,
}
_BY_NAME: Dict[str, Extractor] = {
    "package.json": config_ext.extract_package_json,
    "pyproject.toml": config_ext.extract_pyproject,
    "requirements.txt": config_ext.extract_requirements,
    "requirements-dev.txt": config_ext.extract_requirements,
}

EXTRACTOR_VERSION = "1"


def pick(relpath: str) -> Optional[Extractor]:
    name = os.path.basename(relpath)
    if name in _BY_NAME:
        return _BY_NAME[name]
    return _BY_EXT.get(os.path.splitext(name)[1].lower())


def file_node(relpath: str, lines: int) -> dict:
    return {"id": f"file:{relpath}", "kind": "file", "name": os.path.basename(relpath),
            "file": relpath, "line": 1, "end_line": lines}
