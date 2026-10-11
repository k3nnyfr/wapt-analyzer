"""Render analysis results as HTML, JSON or CSV."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from . import __version__
from .analysis import AnalysisResult, MissingPackage, SoftwareGroup
from .packages import PackageEntry


def _package(entry: PackageEntry | None, lang: str, restricted: tuple[str, ...] = ()) -> dict | None:
    if entry is None:
        return None
    return {
        "restricted": entry.restricted_by(restricted),
        "package": entry.package,
        "base": entry.base,
        "version": str(entry.version),
        "name": entry.name,
        "description": entry.description(lang),
        "editor": entry.get("editor"),
        "architecture": entry.architecture,
        "target_os": entry.target_os,
        "licence": entry.get("licence"),
        "filename": entry.filename,
        "icon_sha256sum": entry.get("icon_sha256sum"),
    }


def _missing(item: MissingPackage, lang: str, r: tuple[str, ...]) -> dict:
    return {
        "base": item.base,
        "os": item.family,
        "other_os": item.other_os,
        "packages_seen": sorted(item.packages_seen),
        "versions_seen": sorted(item.versions_seen),
        "statuses": sorted(item.statuses),
        "host_count": len(item.hosts),
        "hosts": sorted(item.hosts),
        "store": _package(item.store, lang, r),
    }


def _software(group: SoftwareGroup, lang: str, r: tuple[str, ...]) -> dict:
    return {
        "key": group.key,
        "os": group.family,
        "names": sorted(group.names),
        "publishers": sorted(group.publishers),
        "versions": sorted(group.versions),
        "host_count": len(group.hosts),
        "hosts": sorted(group.hosts),
        "wapt_host_count": len(group.wapt_hosts),
        "match": _package(group.match, lang, r),
        "match_source": group.match_source,
        "score": round(group.score, 1),
        "alternatives": [a.package for a in group.alternatives],
        "other_os": group.other_os,
        "folded": group.folded,
        "editions": sorted(group.editions),
        "other_editions": [e.package for e in group.other_editions],
    }


def to_dict(result: AnalysisResult, context: dict, lang: str = "fr", restricted_licences=()) -> dict:
    r = tuple(restricted_licences)
    return {
        "generator": f"wapt-analyzer {__version__}",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "context": context,
        "summary": {
            "repo_packages": result.repo_count,
            "store_packages": result.store_count,
            "hosts": result.host_count,
            "hosts_by_os": result.hosts_by_family,
            "missing_packages": len(result.missing_packages),
            "software_to_import": len(result.software_to_import),
            "software_unmanaged": len(result.software_unmanaged),
            "software_unmatched": len(result.software_unmatched) - result.folded_count,
            "software_folded": result.folded_count,
            "outdated": len(result.outdated),
            "excluded_software_entries": result.excluded_count,
        },
        "missing_packages": [_missing(m, lang, r) for m in result.missing_packages],
        "software_to_import": [_software(s, lang, r) for s in result.software_to_import],
        "software_unmanaged": [_software(s, lang, r) for s in result.software_unmanaged],
        "software_unmatched": [_software(s, lang, r) for s in result.software_unmatched],
        "outdated": [
            {"os": o.family, "kind": o.kind, "local": _package(o.local, lang, r),
             "store": _package(o.store, lang, r)}
            for o in result.outdated
        ],
    }


def import_candidates(data: dict) -> list[dict]:
    """Store packages suggested for import (one entry per package file), without duplicates."""
    found: dict[str, dict] = {}
    for item, pkg in [(m, m["store"]) for m in data["missing_packages"]] + \
                     [(s, s["match"]) for s in data["software_to_import"]]:
        if not pkg:
            continue
        entry = found.setdefault(pkg["filename"], {
            "package": pkg["package"], "version": pkg["version"], "target_os": pkg["target_os"],
            "architecture": pkg["architecture"], "filename": pkg["filename"], "os": [], "host_count": 0,
            "restricted": pkg.get("restricted", ""),
        })
        if item["os"] not in entry["os"]:
            entry["os"].append(item["os"])
        entry["host_count"] = max(entry["host_count"], item["host_count"])
    return sorted(found.values(), key=lambda c: (-c["host_count"], c["package"]))


def write_json(data: dict, path: Path) -> None:
    data = dict(data, import_candidates=import_candidates(data))
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(data: dict, directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []

    def dump(name: str, header: list[str], rows: list[list]) -> None:
        path = directory / name
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(header)
            writer.writerows(rows)
        written.append(path)

    dump("missing_packages.csv",
         ["os", "base", "packages_seen", "versions_seen", "host_count", "store_package", "store_version"],
         [[m["os"], m["base"], " ".join(m["packages_seen"]), " ".join(m["versions_seen"]), m["host_count"],
           (m["store"] or {}).get("package", ""), (m["store"] or {}).get("version", "")]
          for m in data["missing_packages"]])
    for section in ("software_to_import", "software_unmanaged", "software_unmatched"):
        dump(f"{section}.csv",
             ["os", "software", "publisher", "versions", "host_count", "package", "package_version", "source",
              "score"],
             [[s["os"], " | ".join(s["names"]), " | ".join(s["publishers"]), " ".join(s["versions"]), s["host_count"],
               (s["match"] or {}).get("package", ""), (s["match"] or {}).get("version", ""),
               s["match_source"], s["score"]]
              for s in data[section]])
    dump("outdated.csv", ["os", "kind", "local_package", "local_version", "store_package", "store_version"],
         [[o["os"], o["kind"], o["local"]["package"], o["local"]["version"],
           o["store"]["package"], o["store"]["version"]]
          for o in data["outdated"]])
    if "deployments" in data:
        dump("deployments.csv", ["os", "host", "last_seen_on", "kind", "package", "installed", "version", "status",
                                 "date", "output", "since", "days"],
             [[h["os"], h["host"], h["last_seen_on"], i["kind"], i["package"], i["installed"], i["version"],
               i["status"], i["date"], i["output"], i.get("since", ""), i.get("days", "")]
              for h in data["deployments"]["hosts"] for i in h["errors"] + h["pending"]]
             + [[h["os"], h["host"], h["last_seen_on"], "silent", "", "", "", "", "", "", "", ""]
                for h in data["deployments"]["hosts"] if h["stale"]])
    return written


def render_html(data: dict) -> str:
    env = Environment(loader=PackageLoader("wapt_analyzer", "templates"),
                      autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)
    return env.get_template("report.html.j2").render(data=data, candidates=import_candidates(data))


def write_html(data: dict, path: Path) -> None:
    path.write_text(render_html(data), encoding="utf-8")
