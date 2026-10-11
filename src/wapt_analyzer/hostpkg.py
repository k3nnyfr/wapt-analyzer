"""Host packages: rebuild their dependencies from what is installed, and suggest packages to adopt.

A host package (section ``host``, named after the host uuid) lists in ``depends`` the packages the host must
have. Packages installed by hand (``wapt-get install``) or left over from an older setup are missing from it,
so WAPT does not keep them in its desired state. Two kinds of additions are proposed, never removals:

- ``installed``: WAPT packages installed on the host, available in the repository with your prefix, that are
  neither pulled by another package (dependency) nor provided by a group package;
- ``adopt``: software installed outside WAPT for which the repository has a package (report tab
  « Hors WAPT »): once in the host package, WAPT installs and then updates it;
- ``group``: group packages installed on the host and present in the repository, and with ``assign_groups``
  the repository groups whose packages are mostly installed on the host already.
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
class Fix:
    """A host package dependency absent from the repository (``hosts --fix-missing``)."""
    package: str          # dependency name in the host package
    action: str           # import (from the store) / remove
    reason: str
    store: str = ""       # store package to import
    target: str = ""      # its name once imported (your prefix)


@dataclass
class HostPlan:
    host: Host
    family: str
    current: list[str]                                   # current depends
    version: str = ""                                    # current host package version ("" if none)
    additions: list[Addition] = field(default_factory=list)
    not_in_repo: list[str] = field(default_factory=list)  # explicit installed packages missing from the repo
    missing_groups: list[str] = field(default_factory=list)  # installed groups missing from the repo
    on_server: bool | None = None                         # host package present on the server (None: unknown)
    fixes: list[Fix] = field(default_factory=list)        # dependencies absent from the repository

    @property
    def exists(self) -> bool:
        return bool(self.version) or bool(self.current)

    @property
    def missing_on_server(self) -> bool:
        """Installed on the host but gone from the server: recreated even with nothing to add."""
        return self.on_server is False and bool(self.current)

    @property
    def needs_upload(self) -> bool:
        return bool(self.additions) or self.missing_on_server or any(f.target != f.package for f in self.fixes)

    @property
    def depends(self) -> list[str]:
        fixes = {f.package: f for f in self.fixes}
        current = []
        for dep in self.current:
            fix = fixes.get(dep.split("(")[0].strip())
            if fix is None:
                current.append(dep)
            elif fix.target and fix.target not in current:
                current.append(fix.target)          # imported under your prefix: renamed, constraint dropped
        return current + [a.package for a in self.additions if a.package not in current]


def base_name(name: str) -> str:
    """Package name without prefix and version constraint: ``tis-firefox(>=1.0)`` -> ``firefox``."""
    name = name.split("(")[0].strip()
    return split_package_name(name)[1] if "-" in name else name


def _depends(entry: PackageEntry) -> list[str]:
    return [d for d in (entry.get("depends") or "").split(",") if d.strip()]


class RepoView:
    """Repository packages of one OS family, by base name: your prefix first."""

    def __init__(self, entries: Iterable[PackageEntry], family: str, prefix: str,
                 installed: dict[str, list[str]] | None = None):
        self.prefix = prefix
        # depends of the packages installed on the host (inventory), for packages absent from the index
        self.installed: dict[str, list[str]] = {}
        for name, deps in (installed or {}).items():
            self.installed[name] = deps
            self.installed.setdefault(base_name(name), deps)
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
            entry = self.groups.get(name) or self.by_base.get(base_name(name))
            deps = _depends(entry) if entry else self.installed.get(name) or self.installed.get(base_name(name)) or []
            for dep in deps:
                b = base_name(dep)
                if b not in seen:
                    seen.add(b)
                    stack.append(dep)
        return seen


def plan_host(host: Host, repo_entries: list[PackageEntry], prefix: str, *, unmanaged: list[SoftwareGroup] = (),
              exclude: Iterable[str] = (), version: str = "", current: list[str] | None = None,
              on_server: bool | None = None, assign_groups: bool = False, assign_share: float = 0.8,
              store: dict[str, PackageEntry] | None = None, store_prefix: str = "tis",
              restricted: tuple[str, ...] = ()) -> HostPlan:
    """``store`` (store packages of the host family, by name) enables ``fix_missing``: the dependencies absent from
    the repository are imported from the store when it has them, removed otherwise."""
    family = host.os_family
    installed_depends = {p["package"]: list(p.get("depends") or []) for p in host.installed_packages
                         if p.get("package") and p.get("section") in ("base", "group")}
    repo = RepoView(repo_entries, family, prefix, installed_depends)
    current = host.current_depends(current)
    installed = host.host_package
    if not version and installed:
        version = str(installed.get("version") or "")
    plan = HostPlan(host=host, family=family, current=current, version=version, on_server=on_server)
    excluded = set(exclude)

    base_rows = [p for p in host.installed_packages if p.get("section") == "base" and p.get("package")]
    groups = [p["package"] for p in host.installed_packages if p.get("section") == "group" and p.get("package")]
    current_names = {d.split("(")[0].strip() for d in current}

    # Groups first: the packages they provide are not added one by one
    for name in sorted(set(groups) - current_names):
        if name in repo.groups:
            plan.additions.append(Addition(name, "group", "groupe installé"))
        else:
            plan.missing_groups.append(name)   # to recreate with the groups command first
    if assign_groups:
        installed_bases = {base_name(r["package"]) for r in base_rows}
        for name, entry in sorted(repo.groups.items()):
            deps = {base_name(d) for d in _depends(entry)}
            if name in current_names or name in groups or len(deps) < 2:
                continue
            have = len(deps & installed_bases)
            if have / len(deps) >= assign_share:
                plan.additions.append(Addition(name, "group", f"groupe suggéré : {have}/{len(deps)} de ses paquets "
                                                              "déjà installés"))
    added_groups = [a.package for a in plan.additions if a.kind == "group"]

    # Already wanted: the current depends, what they pull, and what the groups provide
    covered = ({base_name(d) for d in current} | repo.closure(current) | repo.closure(groups)
               | repo.closure(added_groups))
    added: set[str] = set()

    for row in sorted(base_rows, key=lambda r: r["package"]):
        name, base = row["package"], base_name(row["package"])
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
    if store is not None:
        plan.fixes = plan_fixes(plan, repo_entries, groups, store, prefix, store_prefix, restricted)
    return plan


def plan_fixes(plan: HostPlan, repo_entries: list[PackageEntry], installed_groups: list[str],
               store: dict[str, PackageEntry], prefix: str, store_prefix: str,
               restricted: tuple[str, ...]) -> list[Fix]:
    available = {e.package for e in repo_entries if plan.family in entry_os_families(e)}
    fixes = []
    for dep in plan.current:
        name = dep.split("(")[0].strip()
        if not name or name in available or name in installed_groups:   # missing groups: groups command
            continue
        entry = store.get(f"{store_prefix}-{base_name(name)}")
        licence = entry.restricted_by(restricted) if entry else ""
        if entry and not licence:
            fixes.append(Fix(name, "import", f"dans le store : {entry.package} {entry.version}",
                             store=entry.package, target=f"{prefix}-{entry.base}"))
        else:
            reason = (f"absent du dépôt, réservé aux abonnés dans le store ({licence})" if licence
                      else "absent du dépôt et du store")
            fixes.append(Fix(name, "remove", reason))
    return fixes


def plan_hosts(hosts: list[Host], repo_entries: list[PackageEntry], prefix: str, *,
               unmanaged: list[SoftwareGroup] = (), exclude: Iterable[str] = (),
               server_packages: dict[str, dict] | None = None, assign_groups: bool = False,
               assign_share: float = 0.8, store: dict[str, dict[str, PackageEntry]] | None = None,
               store_prefix: str = "tis", restricted: tuple[str, ...] = ()) -> list[HostPlan]:
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
                               version=version, current=current, on_server=on_server,
                               assign_groups=assign_groups, assign_share=assign_share,
                               store=None if store is None else store.get(host.os_family, {}),
                               store_prefix=store_prefix, restricted=restricted))
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


def add_to_report(data: dict, plans: list[HostPlan]) -> None:
    """Report section « Paquets machine » and its counter (hosts whose host package would be uploaded)."""
    data["host_packages"] = plans_to_dict(plans)
    data["summary"]["host_packages"] = sum(p.needs_upload for p in plans)


def plans_to_dict(plans: list[HostPlan]) -> list[dict]:
    """Hosts whose host package can be completed, for the report."""
    return [{
        "host": p.host.name, "uuid": p.host.uuid, "os": p.family, "version": p.version, "exists": p.exists,
        "current": p.current,
        "installed": [{"package": a.package, "reason": a.reason} for a in p.additions if a.kind == "installed"],
        "adopt": [{"package": a.package, "reason": a.reason} for a in p.additions if a.kind == "adopt"],
        "groups": [{"package": a.package, "reason": a.reason} for a in p.additions if a.kind == "group"],
        "not_in_repo": p.not_in_repo, "missing_groups": p.missing_groups, "missing_on_server": p.missing_on_server,
    } for p in plans if p.needs_upload or p.not_in_repo or p.missing_groups]
