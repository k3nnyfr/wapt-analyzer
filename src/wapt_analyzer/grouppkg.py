"""Group packages: recreate those deployed on hosts but gone from the repository, suggest new ones.

A group package (section ``group``, e.g. ``grp-base``) bundles packages in its ``depends``; host packages list
groups to install them as a whole. Two kinds of plans:

- ``recreate``: a group installed on hosts but absent from the repository, rebuilt from its highest installed
  version (the inventory keeps its ``depends``). Dependencies missing from the repository are left out unless
  asked otherwise, since hosts could not install them;
- ``suggested``: per OS family, a « common base » of the repository packages installed on most hosts, not
  already provided by an existing group.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from .hostpkg import RepoView, base_name
from .packages import OS_LABELS, PackageEntry, Version
from .server import Host


@dataclass
class GroupPlan:
    package: str
    kind: str                                         # recreate / suggested
    depends: list[str]
    version: str = "0"                                # version to publish
    family: str = ""                                  # suggested groups: OS family
    hosts: list[str] = field(default_factory=list)    # hosts having the group (recreate) or the packages
    missing: list[str] = field(default_factory=list)  # installed depends left out (absent from the repository)
    counts: dict[str, int] = field(default_factory=dict)  # suggested: hosts having each package
    control: dict = field(default_factory=dict)       # attributes kept from the installed group

    @property
    def changed(self) -> bool:
        return bool(self.missing)


KEPT_FIELDS = ("description", "architecture", "locale", "maturity", "target_os", "min_os_version", "max_os_version",
               "conflicts", "priority", "maintainer", "keywords", "editor", "licence")


def repo_groups(repo_entries: list[PackageEntry]) -> dict[str, PackageEntry]:
    groups: dict[str, PackageEntry] = {}
    for e in repo_entries:
        if e.section == "group" and (e.package not in groups or e.version > groups[e.package].version):
            groups[e.package] = e
    return groups


def plan_missing_groups(hosts: list[Host], repo_entries: list[PackageEntry], *,
                        keep_missing: bool = False) -> list[GroupPlan]:
    """Groups installed on hosts and absent from the repository, from their highest installed version."""
    existing = repo_groups(repo_entries)
    names = {e.package for e in repo_entries if e.section != "group"}
    installed: dict[str, list[tuple[Host, dict]]] = {}
    for host in hosts:
        for row in host.installed_packages:
            if row.get("section") == "group" and row.get("package") and row["package"] not in existing:
                installed.setdefault(row["package"], []).append((host, row))
    plans = []
    for name, rows in sorted(installed.items()):
        _, best = max(rows, key=lambda hr: Version(str(hr[1].get("version") or "0")))
        depends = list(best.get("depends") or [])
        missing = [d for d in depends if d.split("(")[0].strip() not in names]
        control = {k: best[k] for k in KEPT_FIELDS if best.get(k) not in (None, "", [])}
        if isinstance(control.get("conflicts"), list):
            control["conflicts"] = ",".join(control["conflicts"])
        plans.append(GroupPlan(
            package=name, kind="recreate", version=str(best.get("version") or "0"),
            depends=depends if keep_missing else [d for d in depends if d not in missing],
            missing=[] if keep_missing else missing,
            hosts=sorted(h.name for h, _ in rows), control=control))
    return plans


def suggest_groups(hosts: list[Host], repo_entries: list[PackageEntry], prefix: str, *,
                   extra_groups: list[GroupPlan] = (), min_share: float = 0.6, min_hosts: int = 3,
                   name: str = "grp-socle-{os}") -> list[GroupPlan]:
    """Per OS family, the repository packages installed on at least ``min_share`` of the hosts (and ``min_hosts``),
    minus those already in a group and those pulled by another one of them."""
    in_groups = {base_name(d) for g in repo_groups(repo_entries).values() for d in (g.get("depends") or "").split(",")
                 if d.strip()}
    in_groups |= {base_name(d) for g in extra_groups for d in g.depends}
    existing_names = {e.package for e in repo_entries}
    plans = []
    for family in sorted({h.os_family for h in hosts}):
        family_hosts = [h for h in hosts if h.os_family == family]
        repo = RepoView(repo_entries, family, prefix)
        counts: Counter[str] = Counter()
        for host in family_hosts:
            local = {repo.local(base_name(r["package"])) for r in host.installed_packages
                     if r.get("section") == "base" and r.get("package")}
            counts.update(e.package for e in local if e is not None)
        needed = max(min_hosts, math.ceil(min_share * len(family_hosts)))
        common = sorted(p for p, n in counts.items() if n >= needed and base_name(p) not in in_groups)
        pulled = repo.closure(common)
        common = [p for p in common if base_name(p) not in pulled]
        group_name = name.format(os=family)
        if len(common) < 2 or group_name in existing_names:
            continue
        plans.append(GroupPlan(package=group_name, kind="suggested", depends=common, family=family,
                               hosts=sorted(h.name for h in family_hosts), counts={p: counts[p] for p in common},
                               control={"description": f"Socle commun {OS_LABELS.get(family, family)} "
                                                       "(suggéré par wapt-analyzer)"}))
    return plans


def group_control(plan: GroupPlan) -> dict:
    """Control attributes for the WAPT helper; the version is incremented when the content changes."""
    return {**plan.control, "package": plan.package, "version": plan.version, "depends": ",".join(plan.depends)}


def add_to_report(data: dict, recreate: list[GroupPlan], suggested: list[GroupPlan]) -> None:
    """Report section « Paquets groupe » and its counter."""
    data["groups"] = plans_to_dict(recreate, suggested)
    data["summary"]["groups"] = len(recreate) + len(suggested)


def plans_to_dict(recreate: list[GroupPlan], suggested: list[GroupPlan]) -> dict:
    return {
        "recreate": [{"package": p.package, "version": p.version, "depends": p.depends, "missing": p.missing,
                      "hosts": p.hosts} for p in recreate],
        "suggested": [{"package": p.package, "os": p.family, "host_count": len(p.hosts),
                       "depends": [{"package": d, "hosts": p.counts.get(d, 0)} for d in p.depends]}
                      for p in suggested],
    }
