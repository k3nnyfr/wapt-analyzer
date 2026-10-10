"""Parsing of WAPT repository indexes (the zipped ``Packages`` file) and version handling."""

from __future__ import annotations

import io
import logging
import re
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from functools import total_ordering

log = logging.getLogger(__name__)


@total_ordering
class Version:
    """WAPT package version: ``<upstream>-<packaging>`` (e.g. ``128.0.3-12``).

    Upstream parts are compared numerically when possible, as WAPT does.
    """

    _split = re.compile(r"[.\-_+~]")

    def __init__(self, text: str):
        self.text = (text or "").strip()
        upstream, _, packaging = self.text.rpartition("-")
        if not upstream:
            upstream, packaging = self.text, ""
        self.upstream = self._parts(upstream)
        self.key = (self.upstream, self._parts(packaging))

    @classmethod
    def _parts(cls, text: str) -> tuple:
        # (0, int) sorts before (1, str): "1.0" < "1.0a" is fine for our needs
        return tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in cls._split.split(text) if p)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Version) and self.key == other.key

    def __lt__(self, other: Version) -> bool:
        return self.key < other.key

    def __hash__(self) -> int:
        return hash(self.key)

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        return f"Version({self.text!r})"


def split_package_name(package: str) -> tuple[str, str]:
    """Split ``tis-firefox-esr`` into (``tis``, ``firefox-esr``).

    Names without a dash have no prefix.
    """
    prefix, sep, base = package.partition("-")
    if not sep:
        return "", package
    return prefix, base


@dataclass(eq=False)  # identity semantics: entries are hashable and unique
class PackageEntry:
    package: str
    version: Version
    fields: dict[str, str] = field(repr=False)

    @property
    def prefix(self) -> str:
        return split_package_name(self.package)[0]

    @property
    def base(self) -> str:
        return split_package_name(self.package)[1]

    def get(self, key: str, default: str = "") -> str:
        return self.fields.get(key, default) or default

    @property
    def name(self) -> str:
        return self.get("name")

    @property
    def section(self) -> str:
        return self.get("section", "base")

    @property
    def architecture(self) -> str:
        return self.get("architecture", "all")

    @property
    def maturity(self) -> str:
        return self.get("maturity")

    @property
    def locale(self) -> str:
        return self.get("locale")

    @property
    def target_os(self) -> str:
        return self.get("target_os")

    @property
    def filename(self) -> str:
        return self.get("filename")

    @property
    def licences(self) -> set[str]:
        return {v.strip().lower() for v in self.get("licence").split(",") if v.strip()}

    def restricted_by(self, restricted_licences) -> str:
        """First licence token of ``restricted_licences`` carried by the package, or ''."""
        return next((lic for lic in restricted_licences if lic.lower() in self.licences), "")

    def description(self, lang: str = "fr") -> str:
        return self.get(f"description_{lang}") or self.get("description")


def parse_control_blocks(text: str) -> Iterator[dict[str, str]]:
    """Parse concatenated control blocks separated by blank lines."""
    current: dict[str, str] = {}
    last_key = None
    for line in text.splitlines():
        if not line.strip():
            if current:
                yield current
            current, last_key = {}, None
            continue
        if line[0] in " \t" and last_key:
            current[last_key] += "\n" + line.strip()
            continue
        key, sep, value = line.partition(":")
        if not sep:
            log.debug("Ignoring malformed control line: %r", line)
            continue
        last_key = key.strip()
        current[last_key] = value.strip()
    if current:
        yield current


def parse_packages_text(text: str) -> list[PackageEntry]:
    entries = []
    for block in parse_control_blocks(text):
        name = block.get("package")
        if not name:
            continue
        entries.append(PackageEntry(package=name, version=Version(block.get("version", "")), fields=block))
    return entries


def parse_packages_index(data: bytes) -> list[PackageEntry]:
    """Parse the raw content of a repository ``Packages`` file (zip archive)."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        text = zf.read("Packages").decode("utf-8", errors="replace")
    return parse_packages_text(text)


# target_os values of each OS family; "all" / empty target_os means every family
OS_FAMILIES: dict[str, tuple[str, ...]] = {
    "windows": ("windows",),
    "macos": ("macos", "darwin", "mac"),
    "linux": ("linux", "debian_based", "redhat_based", "debian", "ubuntu", "redhat", "centos", "rocky",
              "almalinux", "rhel"),
}
OS_LABELS = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}
UNIVERSAL_OS = ("all", "")


def host_os_family(os_name: str) -> str:
    name = (os_name or "").lower()
    if "windows" in name:
        return "windows"
    if "mac" in name or "darwin" in name or "os x" in name:
        return "macos"
    return "linux"


def _values(text: str) -> list[str]:
    return [v.strip().split("(")[0].lower() for v in (text or "").split(",")] or [""]


def entry_os_families(entry: PackageEntry) -> set[str]:
    families = set()
    for value in _values(entry.target_os):
        if value in UNIVERSAL_OS:
            return set(OS_FAMILIES)
        families.update(f for f, names in OS_FAMILIES.items() if value in names)
    return families


@dataclass
class PackageFilters:
    """Restrict store entries to those relevant for the fleet, per OS family."""

    architectures: dict[str, tuple[str, ...]] = field(default_factory=lambda: {
        "windows": ("x64", "all", ""),
        "macos": ("arm", "arm64", "x64", "all", ""),
        "linux": ("x64", "all", ""),
    })
    maturities: tuple[str, ...] = ("PROD", "")
    locales: tuple[str, ...] = ("fr", "en", "all", "")

    @staticmethod
    def _match(value: str, allowed: tuple[str, ...]) -> bool:
        if not allowed:
            return True
        allowed_lower = {a.lower() for a in allowed}
        return any(v in allowed_lower for v in _values(value))

    def accept(self, entry: PackageEntry, family: str) -> bool:
        return (
            self._match(entry.architecture, self.architectures.get(family, ()))
            and self._match(entry.maturity, self.maturities)
            and self._match(entry.locale, self.locales)
        )


def index_by_family(entries: Iterable[PackageEntry], filters: PackageFilters | None = None,
                    families: Iterable[str] = tuple(OS_FAMILIES),
                    sections: tuple[str, ...] = ("base",)) -> dict[str, dict[str, PackageEntry]]:
    """For each OS family, keep the highest version of each package name passing the filters."""
    result: dict[str, dict[str, PackageEntry]] = {f: {} for f in families}
    for entry in entries:
        if sections and entry.section not in sections:
            continue
        for family in entry_os_families(entry) & result.keys():
            if filters and not filters.accept(entry, family):
                continue
            current = result[family].get(entry.package)
            if current is None or entry.version > current.version:
                result[family][entry.package] = entry
    return result
