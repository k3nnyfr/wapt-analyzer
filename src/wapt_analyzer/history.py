"""Deployment history in a local SQLite database: since when a package has been failing or pending on a host.

The WAPT server only keeps the current state of each host. Every online ``report`` records the deployment
issues it sees (``deploy.track_deployments``): an issue (host, package, kind) stays open while it is seen, and is
closed (``resolved_on``) by the first report that no longer sees it on a host present in the inventory. An issue
that comes back later opens a new row.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .deploy import HostDeployment

SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    at    TEXT PRIMARY KEY,               -- ISO date of the report
    hosts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS issues (
    id          INTEGER PRIMARY KEY,
    host_uuid   TEXT NOT NULL,
    host        TEXT NOT NULL,
    package     TEXT NOT NULL,
    kind        TEXT NOT NULL,            -- error / audit / install / upgrade / remove
    version     TEXT NOT NULL DEFAULT '', -- last version seen
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    resolved_on TEXT                      -- NULL while open
);
CREATE UNIQUE INDEX IF NOT EXISTS open_issue ON issues (host_uuid, package, kind) WHERE resolved_on IS NULL;
CREATE INDEX IF NOT EXISTS issue_host ON issues (host_uuid);
"""
HISTORY_FILE = "history.sqlite"
RETENTION_DAYS = 400   # resolved issues older than this are forgotten

Key = tuple[str, str, str]   # host uuid, package, kind


def _issues(state: HostDeployment):
    for issue in state.errors + state.pending:
        yield (state.uuid, issue.package, issue.kind), issue


class DeployHistory:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)
        self.db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> DeployHistory:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def runs(self) -> int:
        return self.db.execute("SELECT count(*) FROM runs").fetchone()[0]

    def record(self, states: list[HostDeployment], at: datetime) -> str:
        """Record the issues seen at ``at``; close the open issues of these hosts that are gone.

        Returns the recorded date, which is the ``first_seen`` of the new issues and the ``resolved_on`` of the
        closed ones."""
        when = at.isoformat(timespec="seconds")
        seen: set[Key] = set()
        with self.db:
            for state in states:
                for key, issue in _issues(state):
                    seen.add(key)
                    updated = self.db.execute(
                        "UPDATE issues SET last_seen = ?, version = ?, host = ? "
                        "WHERE host_uuid = ? AND package = ? AND kind = ? AND resolved_on IS NULL",
                        (when, issue.version, state.host, *key)).rowcount
                    if not updated:
                        self.db.execute(
                            "INSERT INTO issues (host_uuid, host, package, kind, version, first_seen, last_seen) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)", (key[0], state.host, key[1], key[2], issue.version,
                                                             when, when))
            hosts = {s.uuid for s in states}
            for row_id, *key in self.db.execute(
                    "SELECT id, host_uuid, package, kind FROM issues WHERE resolved_on IS NULL").fetchall():
                if key[0] in hosts and tuple(key) not in seen:
                    self.db.execute("UPDATE issues SET resolved_on = ? WHERE id = ?", (when, row_id))
            self.db.execute("INSERT OR REPLACE INTO runs (at, hosts) VALUES (?, ?)", (when, len(states)))
            limit = (at - timedelta(days=RETENTION_DAYS)).isoformat(timespec="seconds")
            self.db.execute("DELETE FROM issues WHERE resolved_on IS NOT NULL AND resolved_on < ?", (limit,))
        return when

    def open_since(self) -> dict[Key, str]:
        """First observation of each open issue."""
        return {(u, p, k): first for u, p, k, first in self.db.execute(
            "SELECT host_uuid, package, kind, first_seen FROM issues WHERE resolved_on IS NULL")}

    def resolved_on(self, when: str) -> list[dict]:
        """Issues closed by the report recorded at ``when``."""
        cur = self.db.execute(
            "SELECT host, package, kind, version, first_seen, resolved_on FROM issues "
            "WHERE resolved_on = ? ORDER BY host, package", (when,))
        return [dict(zip([c[0] for c in cur.description], row, strict=True)) for row in cur.fetchall()]
