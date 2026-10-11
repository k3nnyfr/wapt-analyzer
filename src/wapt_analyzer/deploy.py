"""Deployment tracking: what the agents report about the packages they should install.

Everything comes from the inventory already collected (``installed_packages`` of each host):

- ``install_status``: ``OK``, ``ERROR``, or pending (``NEED-INSTALL``, ``NEED-UPGRADE``, ``NEED-REMOVE``). A pending
  upgrade is reported as two rows: the installed version marked ``NEED-UPGRADE`` and the target version marked
  ``NEED-INSTALL``;
- ``last_audit_status``: result of the package ``audit()`` (``OK``, ``WARNING``, ``ERROR``);
- ``last_seen_on`` of the host: a host silent for days reports nothing, its state is stale.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .server import Host

OUTPUT_TAIL = 400


@dataclass
class Issue:
    package: str
    version: str              # target version (pending), version in error otherwise
    kind: str                 # error / audit / install / upgrade / remove
    installed: str = ""       # installed version, for a pending upgrade
    status: str = ""
    date: str = ""            # install date (error) or last audit date (audit)
    output: str = ""          # end of the install or audit output


@dataclass
class HostDeployment:
    host: str
    uuid: str
    os: str
    last_seen_on: str
    silent_days: int | None
    stale: bool
    errors: list[Issue] = field(default_factory=list)   # install and audit errors
    pending: list[Issue] = field(default_factory=list)

    @property
    def has_issue(self) -> bool:
        return self.stale or bool(self.errors or self.pending)


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        date = datetime.fromisoformat(value)
    except ValueError:
        return None
    return date if date.tzinfo else date.replace(tzinfo=timezone.utc)


def _tail(text: str | None) -> str:
    text = (text or "").strip()
    return text if len(text) <= OUTPUT_TAIL else "…" + text[-OUTPUT_TAIL:]


def host_deployment(host: Host, now: datetime, stale_days: int) -> HostDeployment:
    seen = _parse_date(host.last_seen_on)
    days = (now - seen).days if seen else None
    result = HostDeployment(host=host.name, uuid=host.uuid, os=host.os_family, last_seen_on=host.last_seen_on,
                            silent_days=days, stale=days is None or days >= stale_days)
    rows = host.installed_packages
    upgrading = {p.get("package"): p for p in rows if p.get("install_status") == "NEED-UPGRADE"}
    for p in rows:
        name, version, status = p.get("package") or "", str(p.get("version") or ""), p.get("install_status")
        if status == "ERROR":
            result.errors.append(Issue(name, version, "error", status=status, date=p.get("install_date") or "",
                                       output=_tail(p.get("install_output"))))
        elif status == "NEED-INSTALL":
            current = upgrading.get(name)
            result.pending.append(Issue(name, version, "upgrade" if current else "install", status=status,
                                        installed=str(current.get("version") or "") if current else ""))
        elif status == "NEED-REMOVE":
            result.pending.append(Issue(name, version, "remove", status=status))
        audit = p.get("last_audit_status")
        if audit in ("ERROR", "WARNING"):
            result.errors.append(Issue(name, version, "audit", status=audit, date=p.get("last_audit_on") or "",
                                       output=_tail(p.get("last_audit_output"))))
    # A pending upgrade whose target row is missing still shows the installed version as outdated
    targets = {i.package for i in result.pending}
    result.pending += [Issue(n, "", "upgrade", installed=str(p.get("version") or ""), status="NEED-UPGRADE")
                       for n, p in upgrading.items() if n not in targets]
    result.errors.sort(key=lambda i: (i.kind, i.package))
    result.pending.sort(key=lambda i: (i.kind, i.package))
    return result


def track_deployments(hosts: list[Host], stale_days: int = 7, now: datetime | None = None) -> list[HostDeployment]:
    """Deployment state of every host, the hosts with an issue first (errors, then pending, then silent)."""
    now = now or datetime.now(timezone.utc)
    states = [host_deployment(h, now, stale_days) for h in hosts]
    return sorted(states, key=lambda s: (not s.errors, not s.pending, not s.stale, s.host))


def by_package(states: list[HostDeployment]) -> list[dict]:
    """Per package: the hosts in error and those waiting to install it, most affected first."""
    found: dict[str, dict] = defaultdict(lambda: {"errors": [], "pending": [], "versions": set()})
    for s in states:
        for issue in s.errors:
            found[issue.package]["errors"].append(s.host)
        for issue in s.pending:
            found[issue.package]["pending"].append(s.host)
            if issue.version:
                found[issue.package]["versions"].add(issue.version)
    rows = [{"package": name, "errors": sorted(set(v["errors"])), "pending": sorted(set(v["pending"])),
             "versions": sorted(v["versions"])} for name, v in found.items()]
    return sorted(rows, key=lambda r: (-len(r["errors"]), -len(r["pending"]), r["package"]))


def _issue_dict(state: HostDeployment, issue: Issue, since: dict | None, now: datetime, run_at: str) -> dict:
    data = issue.__dict__.copy()
    first = (since or {}).get((state.uuid, issue.package, issue.kind))
    if first:
        seen = _parse_date(first)
        failed = _parse_date(issue.date) if issue.kind == "error" else None
        if failed and seen and failed < seen:    # failed before the history started: the agent knows when
            first, seen = failed.isoformat(timespec="seconds"), failed
        data.update(since=first, days=(now - seen).days if seen else None,
                    new=(since or {}).get((state.uuid, issue.package, issue.kind)) == run_at)
    return data


def add_to_report(data: dict, states: list[HostDeployment], stale_days: int, *, since: dict | None = None,
                  alert_days: int = 0, resolved: list[dict] | None = None, run_at: str = "",
                  now: datetime | None = None) -> None:
    """Report section « Déploiements » and its counters.

    With the history (``since``: first observation of each open issue), each issue gets its age (``days``), and
    ``new`` when first seen by this report (``run_at``, empty on the first recorded report: everything would be
    new); ``resolved``: issues closed by this report."""
    now = now or datetime.now(timezone.utc)
    issues = [s for s in states if s.has_issue]
    hosts = [{"host": s.host, "uuid": s.uuid, "os": s.os, "last_seen_on": s.last_seen_on,
              "silent_days": s.silent_days, "stale": s.stale,
              "errors": [_issue_dict(s, i, since, now, run_at) for i in s.errors],
              "pending": [_issue_dict(s, i, since, now, run_at) for i in s.pending]} for s in issues]
    lasting = [(h, i) for h in hosts for i in h["errors"] + h["pending"]
               if alert_days and (i.get("days") or 0) >= alert_days]
    data["deployments"] = {
        "stale_days": stale_days,
        "history": since is not None,
        "alert_days": alert_days,
        "hosts": hosts,
        "packages": by_package(states),
        "lasting": [{"host": h["host"], "uuid": h["uuid"], **i} for h, i in lasting],
        "resolved": resolved or [],
    }
    data["summary"].update(
        deploy_hosts=len(issues),
        deploy_errors=sum(len(s.errors) for s in states),
        deploy_error_hosts=sum(1 for s in states if s.errors),
        deploy_pending_hosts=sum(1 for s in states if s.pending),
        stale_hosts=sum(1 for s in states if s.stale),
    )
    if since is not None:
        data["summary"]["deploy_lasting"] = len(lasting)
