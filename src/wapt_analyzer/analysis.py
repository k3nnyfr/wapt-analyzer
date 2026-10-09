"""Cross-reference the local repository, the store index and the host inventory, per OS family."""

from __future__ import annotations

import ast
import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from .packages import PackageEntry, PackageFilters, entry_os_families, split_package_name
from .server import Host

log = logging.getLogger(__name__)

NON_BASE_SECTIONS = {"host", "group", "unit", "profile", "wsus", "selfservice", "config", "restricted"}

_NOISE = [
    r"\(.*?\)",                                   # "(x64 fr)", "(64-bit)"
    r"\b\d+(?:[.,]\d+)+[a-z]?\b",                 # versions "24.08", "1.2.3b"
    r"\bv?\d{4,}\b",                              # builds / years
    r"\b(?:x64|x86|amd64|arm64|win64|win32|64[ -]?bits?|32[ -]?bits?)\b",
    r"\b[a-z]{2}-[a-z]{2}\b",                     # fr-fr, en-us
    r"\b(?:fran[cç]ais|french|english|anglais|multilingual|mui)\b",
    r"\b(?:version|release|build|update)\b",
]
_NOISE_RE = re.compile("|".join(_NOISE), re.IGNORECASE)


def normalize(name: str) -> str:
    text = _NOISE_RE.sub(" ", name or "").lower()
    text = re.sub(r"[^\w+]+", " ", text).replace("_", " ")
    return re.sub(r"\s+", " ", text).strip(" -")


_EDITION_NOISE_RE = re.compile("|".join([
    r"\(.*?\)",                                          # "(x64 fr)", "(64-bit)"
    r"(?:\b|(?<=v))\d+(?:[.,]\d+)+[a-z]?\b",                # dotted versions "24.08", "v3.33.1"
    r"\b(?:x64|x86|amd64|arm64|win64|win32|64[ -]?bits?|32[ -]?bits?)\b",
    r"\b(?:update|build|release|version|sp|service pack|rev)\s*\d+\b",  # "Update 311", "SP3"
    r"\b[a-z]{2}-[a-z]{2}\b",                             # fr-fr
]), re.IGNORECASE)
# a standalone number, or one glued after "v" or a word ("v14", "teamviewer11", "vcredist2015");
# not after a single other letter, which is usually a build code ("I602")
_EDITION_RE = re.compile(r"(?:\b|(?<=\bv)|(?<=[a-z]{3}))(\d{1,4})\b")


def editions(text: str) -> frozenset[str]:
    """Numbers identifying a product edition: "Office 2016" -> {2016}, "Microsoft 365" -> {365}.

    Dotted versions, architectures and update/build numbers are not editions.
    """
    cleaned = _EDITION_NOISE_RE.sub(" ", (text or "").lower()).replace("-", " ").replace("_", " ")
    return frozenset(str(int(n)) for n in _EDITION_RE.findall(cleaned))


def entry_editions(entry: PackageEntry) -> frozenset[str]:
    return editions(entry.name) | editions(entry.base)


def editions_compatible(software: frozenset[str], package: frozenset[str]) -> bool:
    """Incompatible only when both carry an edition number and none is shared."""
    return not software or not package or bool(software & package)


def _as_list(value) -> list[str]:
    """Inventory fields may come as a list, a JSON string or a Python repr."""
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str):
        for loader in (json.loads, ast.literal_eval):
            try:
                parsed = loader(value)
            except (ValueError, SyntaxError):
                continue
            if isinstance(parsed, list):
                return [str(v) for v in parsed if v]
            if isinstance(parsed, str):
                return [parsed]
        return [value]
    return [str(value)]


@dataclass
class MissingPackage:
    base: str
    family: str
    packages_seen: set[str] = field(default_factory=set)
    versions_seen: set[str] = field(default_factory=set)
    hosts: set[str] = field(default_factory=set)
    statuses: set[str] = field(default_factory=set)
    store: PackageEntry | None = None
    other_os: list[str] = field(default_factory=list)     # families for which the repo has this package


@dataclass
class SoftwareGroup:
    key: str
    family: str
    names: set[str] = field(default_factory=set)
    publishers: set[str] = field(default_factory=set)
    versions: set[str] = field(default_factory=set)
    hosts: set[str] = field(default_factory=set)          # installed outside WAPT
    wapt_hosts: set[str] = field(default_factory=set)     # installed through a WAPT package
    match: PackageEntry | None = None
    match_source: str = ""                                # local / store / mapping
    score: float = 0.0
    alternatives: list[PackageEntry] = field(default_factory=list)
    other_os: list[str] = field(default_factory=list)     # unmatched here, but a store package exists for these OS
    editions: frozenset[str] = frozenset()                 # edition numbers of the software ("2016")
    other_editions: list[PackageEntry] = field(default_factory=list)  # packages rejected: other edition
    # host name -> package bases installed by WAPT on it
    host_bases: dict[str, set[str]] = field(default_factory=dict, repr=False)


@dataclass
class OutdatedPackage:
    family: str
    local: PackageEntry
    store: PackageEntry

    @property
    def kind(self) -> str:
        """``upstream``: new software version; ``packaging``: new revision of the same version."""
        return "upstream" if self.store.version.upstream != self.local.version.upstream else "packaging"


@dataclass
class AnalysisResult:
    repo_count: int
    store_count: int
    host_count: int
    hosts_by_family: dict[str, int]
    missing_packages: list[MissingPackage]
    software_to_import: list[SoftwareGroup]
    software_unmanaged: list[SoftwareGroup]
    software_unmatched: list[SoftwareGroup]
    outdated: list[OutdatedPackage]
    excluded_count: int = 0


# Words too generic to identify a software on their own
GENERIC_WORDS = {
    "microsoft", "adobe", "google", "apple", "intel", "hp", "dell", "lenovo", "asus", "acer", "nvidia", "amd",
    "epson", "canon", "samsung", "oracle", "mozilla", "windows", "office", "for", "the", "and", "de", "pour",
    "client", "desktop", "app", "apps", "tools", "tool", "service", "software", "plugin", "add", "in", "player",
    "runtime", "pro", "professional", "free", "portable", "edition", "suite", "manager", "studio",
}


# Packages that configure or remove a software rather than install it
ACTION_WORDS = {"remove", "disable", "enable", "uninstall", "config", "configuration", "settings", "policy",
                "policies", "extension", "addon", "plugin", "language", "langpack", "dictionary"}


def _compact(key: str) -> str:
    return key.replace(" ", "")


class Matcher:
    """Find the packages best describing a software name."""

    def __init__(self, entries: dict[str, PackageEntry], threshold: float):
        self.threshold = threshold
        # alias -> candidates; packages whose *id* gives the alias come first
        self.by_alias: dict[str, list[PackageEntry]] = defaultdict(list)
        for entry in entries.values():
            alias = normalize(entry.base.replace("-", " "))
            if alias:
                self.by_alias[alias].append(entry)
        for entry in entries.values():
            alias = normalize(entry.name)
            if alias and entry not in self.by_alias[alias]:
                self.by_alias[alias].append(entry)
        self.by_compact: dict[str, list[PackageEntry]] = {}
        for alias, candidates in self.by_alias.items():
            self.by_compact.setdefault(_compact(alias), candidates)
        self.alias_tokens = {alias: set(alias.split()) for alias in self.by_alias}
        self.choices = list(self.by_alias)

    def _compatible(self, candidates: list[PackageEntry], eds: frozenset[str],
                    rejected: list[PackageEntry] | None) -> list[PackageEntry]:
        ok = [c for c in candidates if editions_compatible(eds, entry_editions(c))]
        if rejected is not None:
            rejected.extend(c for c in candidates if c not in ok and c not in rejected)
        return ok

    def exact(self, key: str, eds: frozenset[str] = frozenset(),
              rejected: list[PackageEntry] | None = None) -> list[PackageEntry]:
        """Exact match on the alias, its compact form, or without a trailing major version."""
        for candidate in (key, re.sub(r"\s+\d{1,3}$", "", key)):
            for found in (self.by_alias.get(candidate), self.by_compact.get(_compact(candidate))):
                if found:
                    ok = self._compatible(found, eds, rejected)
                    if ok:
                        return ok
        return []

    def fuzzy(self, key: str, publisher: str = "", eds: frozenset[str] = frozenset(),
              rejected: list[PackageEntry] | None = None) -> tuple[list[PackageEntry], float]:
        """Best approximate match: subset of a package name, or token similarity."""
        if len(key) < 5 or not self.choices:
            return [], 0.0
        tokens = set(key.split())
        best: tuple[list[PackageEntry], float] = ([], 0.0)

        # "libreoffice" -> "libreoffice fresh": every word of the software is in the package name
        if any(len(tok) >= 4 and tok not in GENERIC_WORDS for tok in tokens):
            subsets = [a for a, toks in self.alias_tokens.items()
                       if tokens < toks and not (toks - tokens) & ACTION_WORDS]
            if subsets:
                subsets.sort(key=lambda a: (len(a), a))
                candidates = list(dict.fromkeys(e for a in subsets for e in self.by_alias[a]))
                candidates = self._compatible(candidates, eds, rejected)
                if candidates:
                    best = (candidates, 90.0)

        for alias, score, _ in process.extract(key, self.choices, scorer=fuzz.token_sort_ratio,
                                               score_cutoff=self.threshold - 5, limit=10):
            candidates = self._compatible(self.by_alias[alias], eds, rejected)
            if not candidates:
                continue  # other edition: try the next closest name
            editor = normalize(candidates[0].get("editor"))
            if publisher and editor and set(normalize(publisher).split()) & set(editor.split()):
                score = min(100.0, score + 5)
            if score > best[1]:
                best = (candidates, score)
            break
        if best[1] < self.threshold:
            return [], best[1]
        return best


def _by_base(entries: dict[str, PackageEntry], preferred_prefix: str = "") -> dict[str, PackageEntry]:
    result: dict[str, PackageEntry] = {}
    for entry in entries.values():
        current = result.get(entry.base)
        if current is None or (entry.prefix == preferred_prefix and current.prefix != preferred_prefix):
            result[entry.base] = entry
    return result


def _key_variants(key: str) -> list[str]:
    """The key, and the key without a leading vendor name ("microsoft office x" -> "office x")."""
    first, _, rest = key.partition(" ")
    return [key, rest] if first in GENERIC_WORDS and rest else [key]


def _best_match(key: str, publisher: str, repo_matcher: Matcher, store_matcher: Matcher,
                eds: frozenset[str] = frozenset(), rejected: list[PackageEntry] | None = None):
    """Yield at most one (source, candidates, score): exact matches first, local repository first."""
    variants = _key_variants(key)
    for source, matcher in (("local", repo_matcher), ("store", store_matcher)):
        for variant in variants:
            candidates = matcher.exact(variant, eds, rejected)
            if candidates:
                yield source, candidates, 100.0
                return
    results = [(source, *matcher.fuzzy(variant, publisher, eds, rejected))
               for source, matcher in (("local", repo_matcher), ("store", store_matcher))
               for variant in variants]
    results = [r for r in results if r[1]]
    if results:
        yield max(results, key=lambda r: r[2])  # max keeps the first (local) on ties


def _archs(value: str) -> set[str]:
    return {a.strip() for a in (value or "all").split(",") if a.strip()} or {"all"}


def find_updates(
    repo: dict[str, dict[str, PackageEntry]],
    store_entries: list[PackageEntry],
    filters: PackageFilters | None = None,
    store_prefix: str = "tis",
) -> list[OutdatedPackage]:
    """Repository packages for which the store has a newer version, per OS family.

    The store package must have the same name without prefix, target the same OS family, pass the
    filters and match the local architecture (a local ``all`` package accepts any architecture).
    The full version is compared, so a new packaging revision (``-110`` -> ``-111``) counts too.
    """
    store_by_base: dict[str, list[PackageEntry]] = defaultdict(list)
    for entry in store_entries:
        if entry.section == "base":
            store_by_base[entry.base].append(entry)

    updates = []
    for fam in sorted(repo):
        for local in repo[fam].values():
            local_archs = _archs(local.architecture)
            candidates = []
            for entry in store_by_base.get(local.base, ()):
                if fam not in entry_os_families(entry):
                    continue
                if filters and not filters.accept(entry, fam):
                    continue
                if "all" not in local_archs and not (_archs(entry.architecture) & (local_archs | {"all"})):
                    continue
                candidates.append(entry)
            if not candidates:
                continue
            best = max(candidates, key=lambda e: (e.version, e.prefix == store_prefix))
            if best.version > local.version:
                updates.append(OutdatedPackage(family=fam, local=local, store=best))
    return sorted(updates, key=lambda o: (o.local.base, o.family))


def _is_true(value) -> bool:
    return str(value or "0").strip().lower() in ("1", "true", "yes")


def analyze(
    repo: dict[str, dict[str, PackageEntry]],
    store: dict[str, dict[str, PackageEntry]],
    hosts: list[Host],
    *,
    store_prefix: str = "tis",
    threshold: float = 88,
    exclude: list[str] | None = None,
    exclude_keys: list[str] | None = None,
    exclude_publishers: list[str] | None = None,
    mappings: dict[str, str] | None = None,
    ignore_system_components: bool = True,
    updates: list[OutdatedPackage] | None = None,
) -> AnalysisResult:
    """``repo`` and ``store`` are indexes per OS family, as built by ``index_by_family``.

    ``updates`` is the result of ``find_updates`` (computed from the store index when omitted).
    """
    families = sorted({h.os_family for h in hosts})
    repo_by_base = {f: _by_base(repo.get(f, {})) for f in set(repo) | set(families)}
    store_by_base = {f: _by_base(store.get(f, {}), store_prefix) for f in set(store) | set(families)}

    # 1. WAPT packages installed on hosts but absent from the local repository for the host OS
    missing: dict[tuple[str, str], MissingPackage] = {}
    host_keys: dict[str, set[str]] = {}
    host_bases: dict[str, set[str]] = {}
    for host in hosts:
        fam = host.os_family
        host_keys[host.uuid] = set()
        host_bases[host.uuid] = set()
        for pkg in host.installed_packages:
            name = pkg.get("package") or ""
            if not name or name == host.uuid or (pkg.get("section") or "base") in NON_BASE_SECTIONS:
                continue
            _, base = split_package_name(name)
            host_keys[host.uuid].update(_as_list(pkg.get("uninstall_key")))
            host_bases[host.uuid].add(base)
            if base in repo_by_base[fam]:
                continue
            item = missing.get((base, fam))
            if item is None:
                item = missing[(base, fam)] = MissingPackage(
                    base=base, family=fam, store=store_by_base[fam].get(base),
                    other_os=sorted(f for f, idx in repo_by_base.items() if base in idx))
            item.packages_seen.add(name)
            item.hosts.add(host.name)
            if pkg.get("version"):
                item.versions_seen.add(pkg["version"])
            if pkg.get("install_status"):
                item.statuses.add(pkg["install_status"])

    # 2. Software inventory, grouped per OS family and normalized name
    exclude_re = [re.compile(p, re.IGNORECASE) for p in (exclude or [])]
    key_re = [re.compile(p, re.IGNORECASE) for p in (exclude_keys or [])]
    publisher_re = [re.compile(p, re.IGNORECASE) for p in (exclude_publishers or [])]
    mapping_re = [(re.compile(k, re.IGNORECASE), v) for k, v in (mappings or {}).items()]
    groups: dict[tuple[str, str, frozenset[str]], SoftwareGroup] = {}
    excluded = 0
    for host in hosts:
        fam = host.os_family
        for soft in host.installed_softwares:
            sname = (soft.get("name") or "").strip()
            if not sname:
                continue
            skey, publisher = soft.get("key") or "", (soft.get("publisher") or "").strip()
            if ((ignore_system_components and _is_true(soft.get("system_component")))
                    or any(r.search(sname) for r in exclude_re)
                    or any(r.search(skey) for r in key_re)
                    or (publisher and any(r.search(publisher) for r in publisher_re))):
                excluded += 1
                continue
            key = normalize(sname)
            if not key:
                continue
            eds = editions(sname)
            group = groups.setdefault((fam, key, eds), SoftwareGroup(key=key, family=fam, editions=eds))
            group.names.add(sname)
            if publisher:
                group.publishers.add(publisher)
            if soft.get("version"):
                group.versions.add(str(soft["version"]))
            if skey and skey in host_keys[host.uuid]:
                group.wapt_hosts.add(host.name)
            else:
                group.hosts.add(host.name)
                group.host_bases[host.name] = host_bases[host.uuid]

    all_matchers = {
        fam: (Matcher(repo.get(fam, {}), threshold), Matcher(store.get(fam, {}), threshold))
        for fam in set(store) | set(families)
    }
    to_import, unmanaged, unmatched = [], [], []
    for (fam, _, _), group in groups.items():
        if not group.hosts:
            continue  # always installed by WAPT
        name = sorted(group.names)[0]
        publisher = sorted(group.publishers)[0] if group.publishers else ""

        mapped = next((target for rx, target in mapping_re if rx.search(name)), None)
        if mapped == "":
            continue
        if mapped:
            group.match = repo_by_base[fam].get(mapped) or store_by_base[fam].get(mapped)
            group.match_source, group.score = "mapping", 100.0
            if group.match is None:
                log.warning("Mapping %r -> %r: no %s package in repo or store", name, mapped, fam)
        else:
            repo_matcher, store_matcher = all_matchers[fam]
            rejected: list[PackageEntry] = []
            for source, candidates, score in _best_match(group.key, publisher, repo_matcher, store_matcher,
                                                         group.editions, rejected):
                group.match, group.alternatives = candidates[0], candidates[1:]
                group.match_source, group.score = source, score
            if group.match is None:
                group.other_editions = sorted(set(rejected), key=lambda e: e.package)
                group.other_os = sorted(f for f, (_, sm) in all_matchers.items()
                                        if f != fam and sm.exact(group.key, group.editions))

        if group.match is not None:
            # macOS / Linux packages rarely declare uninstall keys: the software counts as
            # managed when the matched package is installed by WAPT on that host.
            managed = {h for h in group.hosts if group.match.base in group.host_bases.get(h, ())}
            group.hosts -= managed
            group.wapt_hosts |= managed
            if not group.hosts:
                continue

        if group.match is None:
            unmatched.append(group)
        elif group.match.base in repo_by_base[fam]:
            unmanaged.append(group)
        else:
            to_import.append(group)

    # 3. Local packages older than the store version
    outdated = updates if updates is not None else find_updates(
        repo, [e for idx in store.values() for e in idx.values()], store_prefix=store_prefix)

    def by_hosts(items):
        return sorted(items, key=lambda i: (-len(i.hosts), i.family, getattr(i, "base", "") or getattr(i, "key", "")))

    hosts_by_family: dict[str, int] = defaultdict(int)
    for host in hosts:
        hosts_by_family[host.os_family] += 1

    return AnalysisResult(
        repo_count=len({p for idx in repo.values() for p in idx}),
        store_count=len({p for idx in store.values() for p in idx}),
        host_count=len(hosts),
        hosts_by_family=dict(sorted(hosts_by_family.items())),
        missing_packages=by_hosts(missing.values()),
        software_to_import=by_hosts(to_import),
        software_unmanaged=by_hosts(unmanaged),
        software_unmatched=by_hosts(unmatched),
        outdated=outdated,
        excluded_count=excluded,
    )
