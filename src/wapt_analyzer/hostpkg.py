"""Host packages: rebuild their dependencies from what is installed, and suggest packages to adopt.

A host package (section ``host``, named after the host uuid) lists in ``depends`` the packages the host must
have. Packages installed by hand (``wapt-get install``) or left over from an older setup are missing from it,
so WAPT does not keep them in its desired state. Two kinds of additions are proposed, never removals:

- ``installed``: WAPT packages installed on the host, available in the repository with your prefix, that are
  neither pulled by another package (dependency) nor provided by a group package;
- ``adopt``: software installed outside WAPT for which the repository has a package (report tab
  « Hors WAPT »): once in the host package, WAPT installs and then updates it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from .analysis import SoftwareGroup
from .packages import PackageEntry, Version, entry_os_families, split_package_name
from .server import Host


@dataclass
class Addition:
    package: str          # repository package added to the host package depends
    kind: str             # installed / adopt
    reason: str


@dataclass
class HostPlan:
    host: Host
    family: str
    current: list[str]                                   # current depends
    version: str = ""                                    # current host package version ("" if none)
    additions: list[Addition] = field(default_factory=list)
    not_in_repo: list[str] = field(default_factory=list)  # explicit installed packages missing from the repo
    on_server: bool | None = None                         # host package present on the server (None: unknown)

    @property
    def exists(self) -> bool:
        return bool(self.version) or bool(self.current)

    @property
    def missing_on_server(self) -> bool:
        """Installed on the host but gone from the server: recreated even with nothing to add."""
        return self.on_server is False and bool(self.current)

    @property
    def needs_upload(self) -> bool:
        return bool(self.additions) or self.missing_on_server

    @property
    def depends(self) -> list[str]:
        return self.current + [a.package for a in self.additions if a.package not in self.current]


def _base(name: str) -> str:
    """Package name without prefix and version constraint: ``tis-firefox(>=1.0)`` -> ``firefox``."""
    name = name.split("(")[0].strip()
    return split_package_name(name)[1] if "-" in name else name


def _depends(entry: PackageEntry) -> list[str]:
    return [d for d in (entry.get("depends") or "").split(",") if d.strip()]


class _Repo:
    """Repository packages of one OS family, by base name: your prefix first."""

    def __init__(self, entries: Iterable[PackageEntry], family: str, prefix: str,
                 installed: dict[str, list[str]] | None = None):
        self.prefix = prefix
        # depends of the packages installed on the host (inventory), for packages absent from the index
        self.installed: dict[str, list[str]] = {}
        for name, deps in (installed or {}).items():
            self.installed[name] = deps
            self.installed.setdefault(_base(name), deps)
        self.by_base: dict[str, PackageEntry] = {}
        self.groups: dict[str, PackageEntry] = {}
        for e in entries:
            if family not in entry_os_families(e):
                continue
            if e.section == "group":
                current = self.groups.get(e.package)
                if current is None or e.version > current.version:
                    self.groups[e.package] = e
                continue
            if e.section != "base":
                continue
            current = self.by_base.get(e.base)
            key = (e.prefix == prefix, e.version)
            if current is None or key > (current.prefix == prefix, current.version):
                self.by_base[e.base] = e

    def local(self, base: str) -> PackageEntry | None:
        e = self.by_base.get(base)
        return e if e is not None and e.prefix == self.prefix else None

    def closure(self, names: Iterable[str]) -> set[str]:
        """Bases of the dependencies of ``names`` (packages or groups), recursively, without ``names``."""
        seen: set[str] = set()
        stack = list(names)
        while stack:
            name = stack.pop()
            name = name.split("(")[0].strip()
            entry = self.groups.get(name) or self.by_base.get(_base(name))
            deps = _depends(entry) if entry else self.installed.get(name) or self.installed.get(_base(name)) or []
            for dep in deps:
                b = _base(dep)
                if b not in seen:
                    seen.add(b)
                    stack.append(dep)
        return seen


def plan_host(host: Host, repo_entries: list[PackageEntry], prefix: str, *, unmanaged: list[SoftwareGroup] = (),
              exclude: Iterable[str] = (), version: str = "", current: list[str] | None = None,
              on_server: bool | None = None) -> HostPlan:
    family = host.os_family
    installed_depends = {p["package"]: list(p.get("depends") or []) for p in host.installed_packages
                         if p.get("package") and p.get("section") in ("base", "group")}
    repo = _Repo(repo_entries, family, prefix, installed_depends)
    current = host.current_depends(current)
    installed = host.host_package
    if not version and installed:
        version = str(installed.get("version") or "")
    plan = HostPlan(host=host, family=family, current=current, version=version, on_server=on_server)
    excluded = set(exclude)

    base_rows = [p for p in host.installed_packages if p.get("section") == "base" and p.get("package")]
    groups = [p["package"] for p in host.installed_packages if p.get("section") == "group" and p.get("package")]
    # Already wanted: the current depends, what they pull, and what the installed groups provide
    covered = {_base(d) for d in current} | repo.closure(current) | repo.closure(groups)
    added: set[str] = set()

    for row in sorted(base_rows, key=lambda r: r["package"]):
        name, base = row["package"], _base(row["package"])
        others = [r["package"] for r in base_rows if r is not row]
        if base in covered or base in added or base in excluded or base in repo.closure(others):
            continue  # already wanted, or installed as a dependency of another package
        local = repo.local(base)
        if local is None:
            plan.not_in_repo.append(name)
            continue
        reason = "installé" if name == local.package else f"installé en tant que {name}"
        plan.additions.append(Addition(local.package, "installed", reason))
        added.add(base)

    for group in unmanaged:
        if group.family != family or host.name not in group.hosts or group.match is None:
            continue
        local = repo.local(group.match.base)
        base = group.match.base
        if local is None or base in covered or base in added or base in excluded:
            continue
        plan.additions.append(Addition(local.package, "adopt", f"hors WAPT : {sorted(group.names)[0]}"))
        added.add(base)
    return plan


def plan_hosts(hosts: list[Host], repo_entries: list[PackageEntry], prefix: str, *,
               unmanaged: list[SoftwareGroup] = (), exclude: Iterable[str] = (),
               server_packages: dict[str, dict] | None = None) -> list[HostPlan]:
    """One plan per host; ``server_packages`` (from the server API) gives the current version and depends.

    Without it, a host package is deemed missing from the server when the server lists no dependency for the
    host while its installed host package has some (the server syncs that list on every upload)."""
    plans = []
    for host in sorted(hosts, key=lambda h: h.name):
        stored = (server_packages or {}).get(host.uuid) or (server_packages or {}).get(host.name)
        installed_deps = (host.host_package or {}).get("depends")
        if server_packages is not None:
            on_server = stored is not None
        else:
            on_server = False if host.depends is None and installed_deps else None
        current = None
        version = ""
        if stored:
            deps = stored.get("depends") or []
            current = [d.strip() for d in deps.split(",") if d.strip()] if isinstance(deps, str) else list(deps)
            version = str(stored.get("version") or "")
        plans.append(plan_host(host, repo_entries, prefix, unmanaged=unmanaged, exclude=exclude,
                               version=version, current=current, on_server=on_server))
    return plans


# Control attributes kept from the existing host package when it is rebuilt
KEPT_FIELDS = ("description", "architecture", "locale", "maturity", "target_os", "min_os_version", "max_os_version",
               "conflicts", "priority", "maintainer", "keywords", "editor", "licence")


def control_for(plan: HostPlan, stored: dict | None, depends: list[str] | None = None) -> dict:
    """Control attributes of the rebuilt host package; the version is the higher of the server and installed
    ones, incremented by the WAPT helper."""
    stored = stored or {}
    source = stored or plan.host.host_package or {}   # a host package gone from the server: the installed one
    control = {k: source[k] for k in KEPT_FIELDS if source.get(k) not in (None, "", [])}
    control.setdefault("description", plan.host.name)
    for key in ("conflicts",):
        if isinstance(control.get(key), list):
            control[key] = ",".join(control[key])
    versions = [v for v in (str(stored.get("version") or ""), plan.version,
                            str((plan.host.host_package or {}).get("version") or "")) if v]
    control.update(package=stored.get("package") or plan.host.uuid,
                   version=max(versions, key=Version) if versions else "0",
                   depends=",".join(plan.depends if depends is None else depends))
    return control


def next_version(version: str) -> str:
    """Version the rebuilt host package will get (WAPT ``inc_build`` on a plain number)."""
    return str(int(version) + 1) if version.isdigit() else f"{version or '0'}+1"


def plans_to_dict(plans: list[HostPlan]) -> list[dict]:
    """Hosts whose host package can be completed, for the report."""
    return [{
        "host": p.host.name, "uuid": p.host.uuid, "os": p.family, "version": p.version, "exists": p.exists,
        "current": p.current,
        "installed": [{"package": a.package, "reason": a.reason} for a in p.additions if a.kind == "installed"],
        "adopt": [{"package": a.package, "reason": a.reason} for a in p.additions if a.kind == "adopt"],
        "not_in_repo": p.not_in_repo, "missing_on_server": p.missing_on_server,
    } for p in plans if p.needs_upload or p.not_in_repo]
