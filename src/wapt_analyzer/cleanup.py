"""Remove from the repository the package versions that no host can see any more, and the packages no host
uses at all."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .packages import PackageEntry, Version, entry_os_families

log = logging.getLogger(__name__)


def _archs(value: str) -> set[str]:
    return {a.strip().lower() for a in (value or "all").split(",") if a.strip()} or {"all"}


def _locales(value: str) -> set[str]:
    return {v.strip().lower() for v in (value or "").split(",") if v.strip()} or {"all"}


def _os_version(value: str) -> Version | None:
    value = (value or "").strip()
    return Version(value) if value else None


def covers(new: PackageEntry, old: PackageEntry) -> bool:
    """True when every host able to install ``old`` can also install ``new``.

    WAPT agents install the highest version among the entries matching their OS, architecture,
    locale, maturity and OS version: if ``new`` matches everywhere ``old`` does, ``old`` is never chosen.
    """
    if new.package != old.package or new.maturity != old.maturity:
        return False
    if not entry_os_families(old) <= entry_os_families(new):
        return False
    new_archs, old_archs = _archs(new.architecture), _archs(old.architecture)
    if "all" not in new_archs and ("all" in old_archs or not old_archs <= new_archs):
        return False
    new_loc, old_loc = _locales(new.locale), _locales(old.locale)
    if "all" not in new_loc and ("all" in old_loc or not old_loc <= new_loc):
        return False
    # OS version range: [min_os_version, max_os_version], empty bound = unbounded
    new_min, old_min = _os_version(new.get("min_os_version")), _os_version(old.get("min_os_version"))
    if new_min is not None and (old_min is None or new_min > old_min):
        return False
    new_max, old_max = _os_version(new.get("max_os_version")), _os_version(old.get("max_os_version"))
    if new_max is not None and (old_max is None or new_max < old_max):
        return False
    return True


_CONSTRAINT_RE = re.compile(r"^\s*([^\s(]+)\s*(?:\(\s*(==|=|>=|<=|>|<)\s*([^)\s]+)\s*\))?\s*$")


def _satisfies(version: Version, op: str, wanted: str) -> bool:
    target = Version(wanted)
    return {"=": version == target, "==": version == target, ">=": version >= target, "<=": version <= target,
            ">": version > target, "<": version < target}[op]


def pinned_by(entry: PackageEntry, latest: PackageEntry, all_entries: list[PackageEntry]) -> list[str]:
    """Packages whose dependency constraint accepts ``entry`` but not ``latest`` (e.g. ``foo(=1.2-3)``)."""
    pins = []
    for other in all_entries:
        for spec in (other.get("depends") or "").split(","):
            m = _CONSTRAINT_RE.match(spec)
            if not m or m.group(1) != entry.package or not m.group(2):
                continue
            op, wanted = m.group(2), m.group(3)
            if _satisfies(entry.version, op, wanted) and not _satisfies(latest.version, op, wanted):
                pins.append(f"{other.package}({op}{wanted})")
    return pins


@dataclass
class CleanupItem:
    entry: PackageEntry
    newer: list[PackageEntry]                 # newer versions covering this one, newest first
    skip: str = ""                            # non-empty: kept, with the reason
    result: dict = field(default_factory=dict)

    @property
    def latest(self) -> PackageEntry:
        return self.newer[0]


def plan_cleanup(entries: list[PackageEntry], *, keep: int = 0, names: list[str] | None = None,
                 exclude: tuple[str, ...] = (), prefix: str = "") -> list[CleanupItem]:
    """Repository entries superseded by at least ``keep + 1`` newer covering versions."""
    by_package: dict[str, list[PackageEntry]] = {}
    for e in entries:
        by_package.setdefault(e.package, []).append(e)

    def wanted(e: PackageEntry) -> bool:
        if not names:
            return True
        return e.package in names or e.base in names

    plan = []
    for _, versions in sorted(by_package.items()):
        versions.sort(key=lambda e: e.version, reverse=True)
        for i, old in enumerate(versions):
            newer = [n for n in versions[:i] if n.version > old.version and covers(n, old)]
            if len(newer) <= keep or not wanted(old):
                continue
            item = CleanupItem(entry=old, newer=newer)
            if old.base in exclude or old.package in exclude:
                item.skip = "excluded by configuration"
            elif prefix and old.prefix != prefix:
                item.skip = f"prefix {old.prefix!r} is not {prefix!r}"
            elif not old.get("package_uuid"):
                item.skip = "no package_uuid in the index"
            else:
                pins = pinned_by(old, newer[0], entries)
                if pins:
                    item.skip = "pinned by " + ", ".join(pins)
            plan.append(item)
    return plan


def dependency_names(entry_or_depends) -> list[str]:
    """Package names of a ``depends`` field (or of an entry's), without version constraints."""
    value = entry_or_depends.get("depends") if isinstance(entry_or_depends, PackageEntry) else entry_or_depends
    if isinstance(value, list):
        value = ",".join(value)
    return [m.group(1) for d in (value or "").split(",") if (m := _CONSTRAINT_RE.match(d))]


def used_packages(entries: list[PackageEntry], hosts) -> set[str]:
    """Names installed or pending on a host, listed by a host package, and their dependencies (transitively)."""
    roots: set[str] = set()
    for host in hosts:
        roots |= {p["package"] for p in host.installed_packages if p.get("package")}
        roots |= set(dependency_names(host.current_depends()))
    depends: dict[str, set[str]] = {}
    for e in entries:
        depends.setdefault(e.package, set()).update(dependency_names(e))
    used, todo = set(), list(roots)
    while todo:
        name = todo.pop()
        if name not in used:
            used.add(name)
            todo += depends.get(name, ())
    return used


@dataclass
class UnusedPackage:
    package: str
    versions: list[PackageEntry]              # every version in the repository, newest first
    skip: str = ""

    @property
    def size(self) -> int:
        return sum(int(e.get("size") or 0) for e in self.versions)


def _signed_on(entry: PackageEntry) -> datetime | None:
    try:
        return datetime.fromisoformat((entry.get("signature_date") or "")[:19])
    except ValueError:
        return None


def plan_unused(entries: list[PackageEntry], hosts, *, prefix: str = "", names: list[str] | None = None,
                exclude: tuple[str, ...] = (), min_age_days: int = 30,
                now: datetime | None = None) -> list[UnusedPackage]:
    """Base and group packages of the repository that no host has installed, waits for or gets through a
    dependency. Recently signed packages (imported but maybe not deployed yet) are kept."""
    used = used_packages(entries, hosts)
    now = now or datetime.now()
    by_package: dict[str, list[PackageEntry]] = {}
    for e in entries:
        if e.section in ("base", "group") and e.package not in used:
            by_package.setdefault(e.package, []).append(e)
    plan = []
    for package, versions in sorted(by_package.items()):
        versions.sort(key=lambda e: e.version, reverse=True)
        latest = versions[0]
        if names and package not in names and latest.base not in names:
            continue
        item = UnusedPackage(package, versions)
        signed = max((d for d in map(_signed_on, versions) if d), default=None)
        if latest.base in exclude or package in exclude:
            item.skip = "excluded by configuration"
        elif prefix and latest.prefix != prefix and latest.section != "group":
            item.skip = f"prefix {latest.prefix!r} is not {prefix!r}"
        elif signed and now - signed < timedelta(days=min_age_days):
            item.skip = f"signed {(now - signed).days} day(s) ago, less than {min_age_days}"
        elif not all(e.get("package_uuid") for e in versions):
            item.skip = "no package_uuid in the index"
        plan.append(item)
    return plan


def missing_dependencies(entries: list[PackageEntry], hosts) -> dict[str, list[str]]:
    """Dependency -> packages (latest versions, host packages) depending on it, for those absent from the
    repository: hosts cannot install them."""
    available = {e.package for e in entries}
    latest: dict[str, PackageEntry] = {}
    for e in entries:
        if e.package not in latest or e.version > latest[e.package].version:
            latest[e.package] = e
    found: dict[str, set[str]] = {}
    for e in latest.values():
        for dep in dependency_names(e):
            if dep not in available:
                found.setdefault(dep, set()).add(e.package)
    for host in hosts:
        for dep in dependency_names(host.depends or []):
            if dep not in available:
                found.setdefault(dep, set()).add(f"{host.name} (host package)")
    return {dep: sorted(users) for dep, users in sorted(found.items())}


def delete_packages(server, uuids: list[str]) -> dict:
    """Delete repository packages by uuid with an authenticated ``WaptServer`` session."""
    resp = server.session.post(f"{server.url}/api/v3/packages_delete_by_uuid", json={"package_uuids": uuids},
                               timeout=120)
    try:
        payload = resp.json()
    except ValueError as e:
        raise RuntimeError(f"packages_delete_by_uuid: HTTP {resp.status_code}, non-JSON answer") from e
    if resp.status_code != 200 or not payload.get("success"):
        raise RuntimeError(f"packages_delete_by_uuid: HTTP {resp.status_code}: {payload.get('msg') or payload}")
    return payload.get("result") or {}
