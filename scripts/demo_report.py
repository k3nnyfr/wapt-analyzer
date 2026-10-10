"""Build a demo report from fictitious hosts and repository, against the public Tranquil IT store index.

Used for the README screenshot: no real host or server appears in the output.

    uv run python scripts/demo_report.py [-o demo-report.html] [--offline]

docs/report.png shows the "À importer" tab (demo-report.html#import) with its first four rows checked,
captured with headless Chrome at 1400x1000.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

from wapt_analyzer.analysis import analyze, find_updates
from wapt_analyzer.config import DEFAULTS
from wapt_analyzer.fetch import Cache, fetch_cached
from wapt_analyzer.packages import (
    PackageEntry,
    PackageFilters,
    Version,
    entry_os_families,
    index_by_family,
    parse_packages_index,
)
from wapt_analyzer.report import to_dict, write_html
from wapt_analyzer.server import Host

STORE_URL = "https://wapt.tranquil.it/wapt"
PREFIX = "demo"

# Repository packages: (store package, target_os, version published in the fictitious repository)
REPO = [
    ("tis-7zip", "windows", "24.08-3"),            # upstream update available
    ("tis-firefox", "windows", None),              # same version as the store
    ("tis-firefox", "darwin", None),
    ("tis-vlc", "windows", "3.0.21-10"),           # upstream update available
    ("tis-notepadplusplus", "windows", "8.9.8.1-10"),  # packaging update available
    ("tis-libreoffice-fresh", "windows", None),
    ("tis-greenshot", "windows", None),
]

# Software seen in the Windows inventory: (display name, publisher, version, share of hosts, WAPT package)
WINDOWS_SOFTWARE = [
    ("Mozilla Firefox (x64 fr)", "Mozilla", "157.0.1", 1.0, "firefox"),
    ("LibreOffice 26.8.0.2", "The Document Foundation", "26.8.0.2", 0.8, "libreoffice-fresh"),
    ("7-Zip 24.08 (x64)", "Igor Pavlov", "24.08", 0.9, None),
    ("VLC media player", "VideoLAN", "3.0.21", 0.6, None),
    ("Notepad++ (64-bit x64)", "Notepad++ Team", "8.9.8", 0.3, None),
    ("Greenshot 1.3.323", "Greenshot", "1.3.323", 0.2, None),
    ("GIMP 3.2.6", "The GIMP Team", "3.2.6", 0.25, None),
    ("KeePassXC", "KeePassXC Team", "2.7.10", 0.4, None),
    ("PuTTY release 0.83 (64-bit)", "Simon Tatham", "0.83.0.0", 0.15, None),
    ("WinSCP 6.5.3", "Martin Prikryl", "6.5.3", 0.15, None),
    ("Zoom Workplace (64-bit)", "Zoom Communications, Inc.", "6.4.10", 0.5, None),
    ("TeamViewer", "TeamViewer", "15.70.4", 0.2, None),
    ("Microsoft Teams", "Microsoft Corporation", "25153.1010", 0.7, None),
    ("Sumatra PDF", "Krzysztof Kowalczyk", "3.5.2", 0.2, None),
    ("Inkscape", "Inkscape", "1.4.2", 0.1, None),
    ("Paint.NET", "dotPDN LLC", "5.1.9", 0.1, None),
    ("Bitwarden 2026.8.0", "Bitwarden Inc.", "2026.8.0", 0.15, None),
    ("Gestion Commerciale Atelier", "ACME Logiciels", "12.4", 0.3, None),
    ("Paie Express 2026", "ACME Logiciels", "26.1", 0.1, None),
    ("HP Smart", "HP Inc.", "151.3.1092", 0.3, None),
    ("HP Universal Print Driver", "HP Inc.", "7.4.0", 0.4, None),
    ("Epson Scan 2", "Seiko Epson Corporation", "6.7.70", 0.1, None),
    ("Realtek Audio Console", "Realtek Semiconductor Corp.", "1.53.316", 0.5, None),
    ("Intel(R) Management Engine Components", "Intel Corporation", "2406.5.5", 0.6, None),
]

MAC_SOFTWARE = [
    ("Firefox", "mozilla", "157.0.1", 1.0, "firefox"),
    ("Visual Studio Code", "microsoft", "1.138.0", 0.7, None),
    ("GIMP", "gimp", "3.2.4", 0.5, None),
    ("Zoom", "zoom.us", "6.4.10", 1.0, None),
    ("Bitwarden", "bitwarden", "2026.8.0", 0.4, None),
    ("Logiciel Atelier", "acme", "3.2", 0.4, None),
]

# WAPT packages installed on hosts from another repository (missing in the fictitious one)
FOREIGN_PACKAGES = [("tis-keepassxc", "2.7.10-1", 0.4), ("tis-putty", "0.83.0.0-10", 0.15)]


def repo_entries(store_entries: list[PackageEntry], filters: PackageFilters) -> list[PackageEntry]:
    by_key = {}
    for e in store_entries:
        key = (e.package, e.target_os)
        if e.section != "base" or not any(filters.accept(e, f) for f in entry_os_families(e)):
            continue
        if key not in by_key or e.version > by_key[key].version:
            by_key[key] = e
    entries = []
    for package, target_os, version in REPO:
        src = by_key[(package, target_os)]
        name = f"{PREFIX}-{src.base}"
        version = version or str(src.version)
        entries.append(PackageEntry(package=name, version=Version(version), fields=dict(
            src.fields, package=name, version=version, filename=f"{name}_{version}_{target_os}.wapt")))
    return entries


def build_hosts(rng: random.Random) -> list[Host]:
    hosts = []
    sites = ["ACCUEIL", "COMPTA", "ATELIER", "DIRECTION", "COMMERCIAL"]
    windows = [f"PC-{sites[i % len(sites)]}-{i + 1:02d}" for i in range(18)]
    macs = [f"MAC-STUDIO-{i + 1:02d}" for i in range(4)]
    for name, software, os_name in [(n, WINDOWS_SOFTWARE, "Windows 11 Pro") for n in windows] + \
                                   [(n, MAC_SOFTWARE, "macOS 26.6") for n in macs]:
        host = Host(uuid=name, name=name, os_name=os_name)
        for display, publisher, version, share, wapt in software:
            if rng.random() > share:
                continue
            key = display if os_name.startswith("Windows") else f"/Applications/{display}.app"
            host.installed_softwares.append({"name": display, "publisher": publisher, "version": version,
                                             "key": key})
            if wapt:
                host.installed_packages.append({"package": f"{PREFIX}-{wapt}", "version": "", "section": "base",
                                                "install_status": "OK", "uninstall_key": [key]})
        if os_name.startswith("Windows"):
            for package, version, share in FOREIGN_PACKAGES:
                if rng.random() <= share:
                    host.installed_packages.append({"package": package, "version": version, "section": "base",
                                                    "install_status": "OK"})
        hosts.append(host)
    return hosts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-o", "--output", default="demo-report.html")
    parser.add_argument("--offline", action="store_true", help="Use the cached store index")
    args = parser.parse_args()

    cache = Cache(Path(DEFAULTS["cache"]["directory"]), offline=args.offline)
    store_entries = parse_packages_index(fetch_cached(f"{STORE_URL}/Packages", cache))
    filters = PackageFilters()
    repo = index_by_family(repo_entries(store_entries, filters))
    store = index_by_family(store_entries, filters)
    m = DEFAULTS["matching"]
    result = analyze(repo, store, build_hosts(random.Random(42)), exclude=m["exclude"],
                     exclude_keys=m["exclude_keys"], exclude_publishers=m["exclude_publishers"],
                     mappings=DEFAULTS["mappings"], updates=find_updates(repo, store_entries, filters),
                     fold_profiles=m["fold_profiles"])
    context = {
        "server_url": "https://wapt.example.org", "repo_url": "https://wapt.example.org/wapt",
        "store_url": STORE_URL, "prefix": PREFIX, "store_prefix": "tis", "icons_url": f"{STORE_URL}/icons",
        "store_page_url": "https://wapt.tranquil.it/store/fr",
    }
    write_html(to_dict(result, context, restricted_licences=DEFAULTS["store"]["restricted_licences"]),
               Path(args.output))
    print(f"Demo report: {args.output}")


if __name__ == "__main__":
    main()
