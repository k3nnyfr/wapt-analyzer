"""Command line interface."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

from . import __version__
from .analysis import analyze, find_updates
from .config import load_config, resolve_key_password, resolve_password
from .fetch import USER_AGENT, Cache, fetch_cached
from .importer import (
    ImportFailed,
    collect_trusted_certs,
    default_fingerprints,
    download_package,
    find_wapt_python,
    plan_imports,
    resolve_requests,
    sign_packages,
    upload_package,
)
from .packages import OS_FAMILIES, PackageEntry, PackageFilters, index_by_family, parse_packages_index
from .progress import console, phase_progress
from .report import import_candidates, to_dict, write_csv, write_html, write_json
from .server import WaptServer, WaptServerError, load_inventory

log = logging.getLogger("wapt_analyzer")


def _csv_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _common_options() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    srv = common.add_argument_group("server")
    srv.add_argument("--server", dest="server_url", help="WAPT server URL, e.g. https://wapt.example.org")
    srv.add_argument("--user", help="Admin user (password: $WAPT_PASSWORD, password_file or prompt)")
    srv.add_argument("--password-file", help="File containing the password (must be chmod 600)")
    srv.add_argument("--insecure", action="store_true", help="Do not verify TLS certificates")
    srv.add_argument("--ca-bundle", help="CA bundle used to verify the server certificate")

    repo = common.add_argument_group("repositories")
    repo.add_argument("--prefix", help="Prefix of your own packages (e.g. tsi)")
    repo.add_argument("--repo-url", help="Repository URL (default: <server>/wapt)")
    repo.add_argument("--store-url", help="Store repository URL (default: Tranquil IT)")
    repo.add_argument("--store-prefix", help="Store package prefix (default: tis)")

    flt = common.add_argument_group("filters")
    flt.add_argument("--os", dest="families", type=_csv_list,
                     help=f"OS families, among {','.join(OS_FAMILIES)} (default: those of the hosts)")
    flt.add_argument("--arch", type=_csv_list, help="Accepted store architectures for every OS (comma separated)")
    flt.add_argument("--maturity", type=_csv_list, help="Accepted store maturities (comma separated)")
    flt.add_argument("--locale", type=_csv_list, help="Accepted locales (comma separated)")
    flt.add_argument("--cache-dir", help="Cache directory")
    return common


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wapt-analyzer",
        description="Suggest WAPT packages missing from your server, based on host inventories "
                    "and the Tranquil IT store, and import them signed with your key.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-c", "--config", help="TOML configuration file "
                        "(default: ./wapt-analyzer.toml, then ~/.config/wapt-analyzer/config.toml)")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    sub = parser.add_subparsers(dest="command", required=True)
    common = _common_options()

    rep = sub.add_parser("report", parents=[common], help="Analyse and write the report")
    rep.add_argument("--workers", type=int, help="Parallel requests for host data")
    rep.add_argument("--threshold", type=float, help="Minimum fuzzy match score (0-100)")
    out = rep.add_argument_group("output")
    out.add_argument("-o", "--output", help="HTML report path ('-' to disable)")
    out.add_argument("--json", help="Also write a JSON report")
    out.add_argument("--csv-dir", help="Also write CSV files in this directory")
    out.add_argument("--lang", help="Language for package descriptions (default: fr)")
    out.add_argument("--offline", action="store_true", help="Only use cached indexes and inventory")

    imp = sub.add_parser(
        "import", parents=[common],
        help="Import store packages into your repository, re-signed with your key (dry run by default)",
        description="Plan the import of store packages, then with --apply: download, verify the Tranquil IT "
                    "signature, rename to your prefix, sign with your key (unlocked once) and upload.",
    )
    src = imp.add_argument_group("packages to import")
    src.add_argument("packages", nargs="*",
                     help="Store package names (tis-firefox or firefox); with --update: restrict to these")
    src.add_argument("--update", action="store_true",
                     help="Update the repository packages for which the store has a newer version")
    src.add_argument("--from-report", metavar="JSON", help="Import the candidates of a JSON report")
    src.add_argument("--only", type=_csv_list, help="With --from-report: only these packages (comma separated)")
    src.add_argument("--no-deps", action="store_true", help="Do not add missing dependencies")
    src.add_argument("--force", action="store_true", help="Import even if the repository has the same or newer")
    act = imp.add_argument_group("action")
    act.add_argument("--apply", action="store_true", help="Really download, sign and upload (default: dry run)")
    act.add_argument("--no-upload", action="store_true", help="Sign only, keep packages in --output-dir")
    act.add_argument("--output-dir", help="Where signed packages are written (default: <cache>/import/signed)")
    act.add_argument("-y", "--yes", action="store_true", help="Do not ask for confirmation")
    sig = imp.add_argument_group("signing")
    sig.add_argument("--certificate", help="Signer certificate (.crt)")
    sig.add_argument("--private-key", help="Private key (.pem, default: certificate path with .pem)")
    sig.add_argument("--key-password-file", help="File containing the key passphrase (chmod 600)")
    sig.add_argument("--wapt-python", help="waptpython interpreter of a WAPT agent (default: auto-detect)")
    sig.add_argument("--set-maturity", help="Maturity of the imported packages (default: keep the store one)")
    trust = imp.add_argument_group("source verification")
    trust.add_argument("--verify", choices=["full", "control", "none"],
                       help="Source package verification: files + metadata (full, default), metadata only, or none")
    trust.add_argument("--trusted-cert", action="append", metavar="PATH",
                       help="Certificate file or directory trusted to verify source packages (repeatable)")
    trust.add_argument("--trusted-fingerprint", action="append", metavar="SHA256",
                       help="Trust the certificate with this SHA-256 fingerprint shipped in the source index "
                            "(repeatable; default: Tranquil IT for the Tranquil IT store)")
    return parser


def apply_args(cfg: dict, args: argparse.Namespace) -> dict:
    mapping = {
        "server_url": ("server", "url"), "user": ("server", "user"), "password_file": ("server", "password_file"),
        "workers": ("server", "workers"), "prefix": ("repo", "prefix"), "repo_url": ("repo", "url"),
        "store_url": ("store", "url"), "store_prefix": ("store", "prefix"),
        "families": ("filters", "families"),
        "maturity": ("filters", "maturities"), "locale": ("filters", "locales"),
        "threshold": ("matching", "threshold"), "output": ("report", "output"), "json": ("report", "json"),
        "csv_dir": ("report", "csv_dir"), "lang": ("report", "language"), "cache_dir": ("cache", "directory"),
        "certificate": ("signing", "certificate"), "private_key": ("signing", "private_key"),
        "key_password_file": ("signing", "key_password_file"), "wapt_python": ("signing", "wapt_python"),
        "set_maturity": ("import", "maturity"), "verify": ("import", "verify"),
    }
    for attr, (section, key) in mapping.items():
        value = getattr(args, attr, None)
        if value is not None:
            cfg[section][key] = value
    if getattr(args, "trusted_cert", None):
        cfg["store"]["trusted_certs"] = args.trusted_cert
    if getattr(args, "trusted_fingerprint", None):
        cfg["store"]["trusted_fingerprints"] = args.trusted_fingerprint
    if args.arch is not None:
        cfg["filters"]["architectures"] = {f: args.arch for f in OS_FAMILIES}
    if args.insecure:
        cfg["server"]["verify_ssl"] = False
    elif args.ca_bundle:
        cfg["server"]["verify_ssl"] = args.ca_bundle
    if cfg["signing"]["certificate"] and not cfg["signing"]["private_key"]:
        cfg["signing"]["private_key"] = str(Path(cfg["signing"]["certificate"]).with_suffix(".pem"))
    return cfg


@dataclass
class Indexes:
    server_url: str
    repo_url: str
    store_url: str
    repo: dict[str, dict[str, PackageEntry]]
    store: dict[str, dict[str, PackageEntry]]
    store_entries: list[PackageEntry]
    store_index_data: bytes
    filters: PackageFilters


def load_indexes(cfg: dict, cache: Cache) -> Indexes:
    server_url = cfg["server"]["url"].rstrip("/")
    repo_url = (cfg["repo"]["url"] or f"{server_url}/wapt").rstrip("/")
    if not server_url and not cfg["repo"]["url"]:
        raise RuntimeError("No server URL: use --server or [server] url in the configuration")
    store_url = cfg["store"]["url"].rstrip("/")
    unknown = set(cfg["filters"]["families"]) - set(OS_FAMILIES)
    if unknown:
        raise RuntimeError(f"Unknown OS families: {', '.join(sorted(unknown))} (expected {', '.join(OS_FAMILIES)})")
    filters = PackageFilters(
        architectures={f: tuple(v) for f, v in cfg["filters"]["architectures"].items()},
        maturities=tuple(cfg["filters"]["maturities"]), locales=tuple(cfg["filters"]["locales"]),
    )
    repo_entries = parse_packages_index(fetch_cached(f"{repo_url}/Packages", cache, verify=cfg["server"]["verify_ssl"]))
    store_data = fetch_cached(f"{store_url}/Packages", cache)
    store_entries = parse_packages_index(store_data)
    idx = Indexes(server_url, repo_url, store_url, index_by_family(repo_entries),
                  index_by_family(store_entries, filters), store_entries, store_data, filters)
    for fam in OS_FAMILIES:
        log.info("%s: %d packages in repository, %d eligible in store", fam, len(idx.repo[fam]), len(idx.store[fam]))
    return idx


def _cache(cfg: dict, offline: bool = False) -> Cache:
    return Cache(Path(cfg["cache"]["directory"]).expanduser(), offline=offline)


def cmd_report(cfg: dict, args: argparse.Namespace) -> int:
    cache = _cache(cfg, args.offline)
    idx = load_indexes(cfg, cache)
    prefix = cfg["repo"]["prefix"]
    if prefix:
        foreign = sorted({e.prefix for fam in idx.repo.values() for e in fam.values()} - {prefix})
        if foreign:
            log.info("Repository also contains prefixes: %s", ", ".join(foreign))

    server = None
    if not args.offline:
        server = WaptServer(idx.server_url, cfg["server"]["user"], resolve_password(cfg),
                            verify=cfg["server"]["verify_ssl"])
    hosts = load_inventory(server, cache, workers=int(cfg["server"]["workers"]))
    families = cfg["filters"]["families"]
    if families:
        hosts = [h for h in hosts if h.os_family in families]

    result = analyze(
        idx.repo, idx.store, hosts,
        store_prefix=cfg["store"]["prefix"],
        threshold=float(cfg["matching"]["threshold"]),
        exclude=cfg["matching"]["exclude"],
        exclude_keys=cfg["matching"]["exclude_keys"],
        exclude_publishers=cfg["matching"]["exclude_publishers"],
        mappings=cfg["mappings"],
        ignore_system_components=cfg["matching"]["ignore_system_components"],
        updates=find_updates(idx.repo, idx.store_entries, idx.filters, cfg["store"]["prefix"]),
    )
    lang = cfg["report"]["language"]
    context = {
        "server_url": idx.server_url, "repo_url": idx.repo_url, "store_url": idx.store_url,
        "prefix": prefix, "store_prefix": cfg["store"]["prefix"],
        "icons_url": f"{idx.store_url}/icons",
        "store_page_url": f"https://wapt.tranquil.it/store/{lang}" if "wapt.tranquil.it" in idx.store_url else "",
    }
    data = to_dict(result, context, lang, restricted_licences=cfg["store"]["restricted_licences"])

    output = cfg["report"]["output"]
    if output and output != "-":
        write_html(data, Path(output))
        print(f"HTML report: {output}")
    if cfg["report"]["json"]:
        write_json(data, Path(cfg["report"]["json"]))
        print(f"JSON report: {cfg['report']['json']}")
    if cfg["report"]["csv_dir"]:
        for p in write_csv(data, Path(cfg["report"]["csv_dir"])):
            print(f"CSV: {p}")

    sm = data["summary"]
    print(f"{sm['hosts']} hosts | {sm['missing_packages']} missing packages | "
          f"{sm['software_to_import']} software to import | {sm['software_unmanaged']} outside WAPT | "
          f"{sm['software_unmatched']} unmatched | {sm['outdated']} outdated")
    return 0


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def _update_requests(cfg: dict, idx: Indexes, families: list[str], names: list[str]):
    """Store entries newer than the repository packages, as (entry, [family]) import requests."""
    updates = find_updates(idx.repo, idx.store_entries, idx.filters, cfg["store"]["prefix"])
    wanted = {n.split("-", 1)[1] if n.split("-", 1)[0] in (cfg["store"]["prefix"], cfg["repo"]["prefix"]) else n
              for n in names}
    excluded = set(cfg["import"]["update_exclude"])
    requests_ = []
    for upd in updates:
        if upd.family not in families or (wanted and upd.local.base not in wanted):
            continue
        if upd.local.base in excluded:
            log.info("%s: excluded from updates by configuration", upd.local.package)
            continue
        log.info("%s (%s) %s -> %s %s", upd.local.package, upd.family, upd.local.version, upd.store.package,
                 upd.store.version)
        requests_.append((upd.store, [upd.family]))
    if not requests_:
        print("Everything is up to date.")
    return requests_


def cmd_import(cfg: dict, args: argparse.Namespace) -> int:
    prefix = cfg["repo"]["prefix"]
    if not prefix:
        log.error("No prefix: use --prefix or [repo] prefix in the configuration")
        return 2
    if not args.packages and not args.from_report and not args.update:
        log.error("Nothing to import: give package names, --from-report or --update")
        return 2
    if args.update and args.from_report:
        log.error("--update and --from-report cannot be combined")
        return 2
    cache = _cache(cfg)
    idx = load_indexes(cfg, cache)

    candidates = []
    if args.from_report:
        data = json.loads(Path(args.from_report).read_text(encoding="utf-8"))
        candidates = data.get("import_candidates") or import_candidates(data)
        if args.only:
            wanted = set(args.only)
            candidates = [c for c in candidates if c["package"] in wanted or c["package"].split("-", 1)[-1] in wanted]
    families = cfg["filters"]["families"] or (["windows"] if args.packages and not args.update else list(OS_FAMILIES))
    if args.update:
        requested = _update_requests(cfg, idx, families, names=args.packages + (args.only or []))
    else:
        requested = resolve_requests(args.packages, candidates, idx.store_entries, idx.store, families)
    plan = plan_imports(requested, idx.store, idx.repo, prefix, with_deps=cfg["import"]["dependencies"]
                        and not args.no_deps, force=args.force, excluded_bases=tuple(cfg["import"]["exclude"]),
                        restricted_licences=tuple(cfg["store"]["restricted_licences"]))
    todo = [p for p in plan if not p.skip]

    print(f"Import plan ({len(todo)} to import, {len(plan) - len(todo)} skipped):")
    for item in plan:
        e = item.entry
        status = f"SKIP ({item.skip})" if item.skip else "IMPORT"
        reason = "" if item.reason == "requested" else f" [{item.reason}]"
        print(f"  {status:<8} {e.package} {e.version} -> {item.target_name}  "
              f"{','.join(item.families)} {e.architecture} {_human_size(int(e.get('size') or 0))}{reason}")
    total = sum(int(p.entry.get("size") or 0) for p in todo)
    print(f"Total download: {_human_size(total)}")
    if not todo:
        return 0
    if not args.apply:
        print("Dry run: nothing done. Add --apply to download, sign and upload.")
        return 0

    signing = cfg["signing"]
    if not signing["certificate"]:
        log.error("No signer certificate: use --certificate or [signing] certificate")
        return 2
    wapt_python = find_wapt_python(signing["wapt_python"])
    log.info("Using %s", wapt_python)

    # Trust is checked before asking anything: no point unlocking the key for an unverifiable source
    work_dir = Path(cfg["import"]["work_dir"] or Path(cfg["cache"]["directory"]) / "import").expanduser()
    trusted: list[Path] = []
    if cfg["import"]["verify"] == "none":
        log.warning("Source package verification DISABLED (--verify none): packages from %s will be signed "
                    "with your key without any authenticity check", idx.store_url)
    else:
        fingerprints = cfg["store"]["trusted_fingerprints"]
        if fingerprints is None:
            fingerprints = default_fingerprints(idx.store_url)
        trusted = collect_trusted_certs(idx.store_index_data, work_dir / "trusted", fingerprints=fingerprints,
                                        cert_paths=cfg["store"]["trusted_certs"])
        log.info("Source packages verified against %d trusted certificate(s)", len(trusted))
    if not args.yes and sys.stdin.isatty():
        target = "sign only" if args.no_upload else f"sign and upload to {idx.server_url}"
        if input(f"Download, {target} {len(todo)} package(s)? [y/N] ").strip().lower() not in ("y", "yes", "o", "oui"):
            print("Aborted.")
            return 1

    # Secrets are asked once, before the long steps
    key_password = resolve_key_password(cfg)
    server = None
    if not args.no_upload:
        server = WaptServer(idx.server_url, cfg["server"]["user"], resolve_password(cfg),
                            verify=cfg["server"]["verify_ssl"])

    output_dir = Path(args.output_dir or work_dir / "signed").expanduser()

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    total_bytes = sum(int(i.entry.get("size") or 0) for i in todo)
    with phase_progress() as progress:
        task = progress.add_task("", total=total_bytes or None, phase="Download", current="")
        for item in todo:
            progress.update(task, current=item.entry.filename)
            try:
                item.download_path = download_package(idx.store_url, item.entry, work_dir / "downloads", session,
                                                      on_progress=lambda n: progress.advance(task, n))
            except (ImportFailed, requests.RequestException) as e:
                item.result = {"ok": False, "error": str(e)}
                log.error("%s: %s", item.entry.filename, e)
        progress.update(task, current="")
    downloaded = [i for i in todo if i.download_path]

    if downloaded:
        with phase_progress(transfer=False) as progress:
            task = progress.add_task("", total=len(downloaded), phase="Signature", current="unlocking key")

            def signed_one(item):
                progress.advance(task)
                if not item.result.get("ok"):
                    log.error("%s: %s", item.entry.filename, item.result.get("error"))

            sign_packages(downloaded, wapt_python=wapt_python, certificate=signing["certificate"],
                          private_key=signing["private_key"], password=key_password, trusted_certs=trusted,
                          prefix=prefix, output_dir=output_dir, maturity=cfg["import"]["maturity"],
                          verify=cfg["import"]["verify"],
                          on_start=lambda item: progress.update(task, current=f"{item.entry.package} -> "
                                                                               f"{item.target_name}"),
                          on_done=signed_one)
            progress.update(task, current="")
    del key_password

    signed = [i for i in todo if i.result.get("ok")]
    if server and signed:
        server.login()
        try:
            paths = [Path(i.result["local_path"]) for i in signed]
            with phase_progress() as progress:
                task = progress.add_task("", total=sum(p.stat().st_size for p in paths), phase="Upload",
                                         current="")
                for item, path in zip(signed, paths, strict=True):
                    progress.update(task, current=path.name)
                    try:
                        upload_package(server, path, on_progress=lambda n: progress.advance(task, n))
                        item.result["uploaded"] = True
                    except (ImportFailed, requests.RequestException) as e:
                        item.result.update(ok=False, error=str(e))
                        log.error("%s: %s", path.name, e)
                progress.update(task, current="")
        finally:
            server.logout()

    failed = [i for i in todo if not i.result.get("ok")]
    print(f"\n{len(todo) - len(failed)} imported" + (" (signed only)" if args.no_upload else "")
          + f", {len(failed)} failed. Signed packages: {output_dir}")
    for item in failed:
        print(f"  FAILED {item.entry.package}: {item.result.get('error', 'not processed')}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    level = logging.WARNING - 10 * min(args.verbose, 2)
    if console.is_terminal:
        # Log lines are printed above the progress bars instead of breaking them
        from rich.logging import RichHandler
        logging.basicConfig(level=level, format="%(name)s: %(message)s",
                            handlers=[RichHandler(console=console, show_time=False, show_path=False)])
    else:
        logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    try:
        cfg = apply_args(load_config(args.config), args)
        if args.command == "report":
            return cmd_report(cfg, args)
        if args.command == "import":
            return cmd_import(cfg, args)
    except (WaptServerError, ImportFailed, RuntimeError, OSError) as e:
        log.error("%s", e)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
