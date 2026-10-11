"""Fleet health: operating systems out of support, outdated WAPT agents, expiry of the signer certificate.

End-of-support dates come from the Microsoft lifecycle pages (state of October 2026); Apple publishes none,
it patches in practice the last three major macOS versions (``[health] macos_min_version``).
"""

from __future__ import annotations

import logging
import ssl
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from .packages import Version
from .server import Host

log = logging.getLogger(__name__)

# Windows build -> (release, end of support Home/Pro, end of support Enterprise/Education)
WINDOWS = {
    7601: ("Windows 7", "2020-01-14", "2020-01-14"),
    9200: ("Windows 8", "2016-01-12", "2016-01-12"),
    9600: ("Windows 8.1", "2023-01-10", "2023-01-10"),
    22000: ("Windows 11 21H2", "2023-10-10", "2024-10-08"),
    22621: ("Windows 11 22H2", "2024-10-08", "2025-10-14"),
    22631: ("Windows 11 23H2", "2025-11-11", "2026-11-10"),
    26100: ("Windows 11 24H2", "2026-10-13", "2027-10-12"),
    26200: ("Windows 11 25H2", "2027-10-12", "2028-10-10"),
}
WINDOWS_10_END = "2025-10-14"            # every Windows 10 release (builds 10240 to 19045), LTSC aside
WINDOWS_SERVER = {
    9200: ("Windows Server 2012", "2023-10-10"),
    9600: ("Windows Server 2012 R2", "2023-10-10"),
    14393: ("Windows Server 2016", "2027-01-12"),
    17763: ("Windows Server 2019", "2029-01-09"),
    20348: ("Windows Server 2022", "2031-10-14"),
    26100: ("Windows Server 2025", "2034-10-10"),
}


@dataclass
class OsSupport:
    release: str
    end: str = ""          # end of support date, "" if unknown
    status: str = "unknown"  # ended / soon / ok / unknown
    days: int | None = None  # days until the end (negative: ended for that long)


def _build(os_version: str) -> int | None:
    parts = (os_version or "").split(".")
    try:
        return int(parts[2]) if len(parts) >= 3 else None
    except ValueError:
        return None


def os_support(host: Host, today: date, warn_days: int = 90, macos_min: str = "15") -> OsSupport:
    name, version = host.os_name.strip(), host.os_version
    family = host.os_family
    if family == "windows":
        build = _build(version)
        if build is None:
            return OsSupport(name)
        if "server" in name.lower():
            release, end = WINDOWS_SERVER.get(build, (name, ""))
        elif 10240 <= build <= 19045:
            release, end = ("Windows 10" if "ltsc" not in name.lower() else name,
                            WINDOWS_10_END if "ltsc" not in name.lower() else "")
        elif build in WINDOWS:
            release, home, enterprise = WINDOWS[build]
            end = enterprise if any(e in name.lower() for e in ("enterprise", "education")) else home
        else:
            return OsSupport(name)
        result = OsSupport(release, end)
    elif family == "macos":
        major = (version or "").split(".")[0]
        if not major.isdigit():
            return OsSupport(name)
        supported = Version(major) >= Version(macos_min)
        return OsSupport(f"macOS {major}", status="ok" if supported else "ended")
    else:
        return OsSupport(name)
    if result.end:
        result.days = (date.fromisoformat(result.end) - today).days
        result.status = "ended" if result.days < 0 else "soon" if result.days <= warn_days else "ok"
    return result


def agent_outdated(host: Host, reference: str) -> bool:
    return bool(reference and host.wapt_version) and Version(host.wapt_version) < Version(reference)


def certificate_expiry(path: str, today: date, warn_days: int = 30) -> dict | None:
    """Expiry of a PEM certificate; None if it cannot be read."""
    if not path:
        return None
    try:
        # Private helper of CPython's ssl module: decodes a PEM certificate without third-party package
        info = ssl._ssl._test_decode_cert(str(Path(path).expanduser()))  # noqa: SLF001
        not_after = datetime.strptime(info["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    except (OSError, ValueError, KeyError, AttributeError, ssl.SSLError) as e:
        log.warning("Cannot read the signer certificate %s: %s", path, e)
        return None
    subject = dict(x[0] for x in info.get("subject", ()))
    days = (not_after.date() - today).days
    return {"path": str(path), "subject": subject.get("commonName", ""), "not_after": not_after.date().isoformat(),
            "days": days, "status": "ended" if days < 0 else "soon" if days <= warn_days else "ok"}


def add_to_report(data: dict, hosts: list[Host], *, agent_version: str = "", certificate: str = "",
                  today: date | None = None, os_warn_days: int = 90, cert_warn_days: int = 30,
                  macos_min: str = "15") -> None:
    """Report section « Santé » and its counters. ``agent_version``: reference version (the server's agent),
    else the newest one seen on the hosts."""
    today = today or date.today()
    reference = agent_version or max((h.wapt_version for h in hosts if h.wapt_version), key=Version, default="")
    rows = []
    for h in hosts:
        support = os_support(h, today, os_warn_days, macos_min)
        rows.append({"host": h.name, "uuid": h.uuid, "os": h.os_family, "os_name": h.os_name.strip(),
                     "os_version": h.os_version, "release": support.release, "end": support.end,
                     "os_status": support.status, "days": support.days, "agent": h.wapt_version,
                     "agent_outdated": agent_outdated(h, reference)})
    order = {"ended": 0, "soon": 1, "unknown": 2, "ok": 3}
    rows.sort(key=lambda r: (order[r["os_status"]], not r["agent_outdated"], r["host"].lower()))
    cert = certificate_expiry(certificate, today, cert_warn_days)
    data["health"] = {"agent_reference": reference, "os_warn_days": os_warn_days, "hosts": rows, "certificate": cert}
    data["summary"].update(
        health_os_ended=sum(r["os_status"] == "ended" for r in rows),
        health_os_soon=sum(r["os_status"] == "soon" for r in rows),
        health_agents_outdated=sum(r["agent_outdated"] for r in rows),
        health_issues=sum(r["os_status"] in ("ended", "soon") or r["agent_outdated"] for r in rows)
        + (1 if cert and cert["status"] != "ok" else 0),
    )
