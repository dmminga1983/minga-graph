"""Secret detection and redaction.

Used in three places:
  * text stored in the graph (docstrings, notes) is redacted before writing;
  * the report lists files that look like they contain secrets (value masked);
  * ``minga-graph secrets PATH`` is a standalone pre-push check (exit code 1 on hits).

Files named ``.env`` / ``.env.*`` (except ``.env.example``) are never read at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

# (name, pattern). Patterns are deliberately specific to keep false positives low.
_PATTERNS = [
    ("AWS access key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("Private key block", r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----"),
    ("GitHub token", r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b"),
    ("GitHub fine-grained token", r"\bgithub_pat_[A-Za-z0-9_]{50,}\b"),
    ("Anthropic API key", r"\bsk-ant-[A-Za-z0-9_\-]{20,}"),
    ("OpenAI-style API key", r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}"),
    ("Slack token", r"\bxox[abposr]-[A-Za-z0-9\-]{10,}"),
    ("Google API key", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    ("Telegram bot token", r"\b\d{8,10}:AA[A-Za-z0-9_\-]{33}\b"),
    ("Stripe live key", r"\b(?:sk|rk)_live_[A-Za-z0-9]{20,}\b"),
    ("JWT", r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    ("Password in URL", r"[a-z][a-z0-9+.\-]*://[^\s/:@]+:[^\s/@]{6,}@"),
    # key = "literal" assignments. Literal must look random-ish (8+ chars, no spaces).
    ("Hard-coded credential",
     r"(?i)\b(?:password|passwd|pwd|secret|api[_\-]?key|access[_\-]?token|auth[_\-]?token|client[_\-]?secret)"
     r"\b\s*[:=]\s*[\"']([^\"'\s]{8,})[\"']"),
]
_COMPILED = [(name, re.compile(p)) for name, p in _PATTERNS]

# Values that are obviously placeholders, not secrets.
_PLACEHOLDER = re.compile(r"(?i)^(?:x+|\*+|<.*>|\$\{.*\}|\{\{.*\}\}|your[_\-].*|changeme|example.*|dummy.*|test.*|placeholder.*|\.\.\.)$")


@dataclass
class Finding:
    path: str
    line: int
    kind: str
    masked: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.kind}: {self.masked}"


def _mask(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * min(len(value) - 6, 24) + value[-2:]


def scan_text(text: str, path: str = "") -> List[Finding]:
    found: List[Finding] = []
    starts = None
    for name, rx in _COMPILED:
        for m in rx.finditer(text):
            value = m.group(1) if m.groups() else m.group(0)
            if "\n" in m.group(0):
                continue
            ls = text.rfind("\n", 0, m.start()) + 1
            le = text.find("\n", m.end())
            line = text[ls: le if le != -1 else len(text)]
            if name == "Hard-coded credential" and (_PLACEHOLDER.match(value) or "os.environ" in line or "getenv" in line):
                continue
            if starts is None:
                import bisect
                starts = [0] + [i + 1 for i, ch in enumerate(text) if ch == "\n"]
                _bisect = bisect.bisect_right
            found.append(Finding(path, _bisect(starts, m.start()), name, _mask(value)))
    found.sort(key=lambda f: (f.line, f.kind))
    return found


def redact(text: str) -> str:
    if not text:
        return text
    out = text
    for name, rx in _COMPILED:
        if name == "Hard-coded credential":
            out = rx.sub(lambda m: m.group(0).replace(m.group(1), "[REDACTED]")
                         if not _PLACEHOLDER.match(m.group(1)) else m.group(0), out)
        else:
            out = rx.sub("[REDACTED]", out)
    return out


def is_env_file(name: str) -> bool:
    low = name.lower()
    if low in (".env.example", ".env.sample", ".env.template", ".env.dist"):
        return False
    return low == ".env" or low.startswith(".env.") or low.endswith(".env")
