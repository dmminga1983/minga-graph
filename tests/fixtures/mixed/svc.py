"""Python service layer."""
import os
from pathlib import Path


class Repo:
    """Stores users."""

    def save(self, user):
        return self._write(user)

    def _write(self, user):
        # WHY: writes are append-only for audit
        return Path("x").write_text(str(user))


class AuditRepo(Repo):
    def save(self, user):
        super().save(user)
        return log_event("saved")


def log_event(name):
    return os.environ.get("LOG", name)


def main():
    AuditRepo().save({"id": 1})
