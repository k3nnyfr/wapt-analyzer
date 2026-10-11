"""Command line interface."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

from . import __version__
from .actions import Target, build_actions, host_rows_to_targets, sign_actions, wake_and_wait
from .analysis import AnalysisResult, analyze, find_updates
from .cleanup import delete_packages, missing_dependencies, plan_cleanup, plan_unused
from .config import load_config, resolve_client_key_password, resolve_key_password, resolve_password, resolve_totp
from .deploy import add_to_report as add_deployments_to_report
from .deploy import track_deployments
from .fetch import USER_AGENT, Cache, fetch_cached
from .grouppkg import GroupPlan, group_control, plan_missing_groups, suggest_groups
from .grouppkg import add_to_report as add_groups_to_report
from .hostpkg import add_to_report, control_for, next_version, plan_hosts
from .importer import (
    ImportFailed,
    collect_trusted_certs,
    default_fingerprints,
    default_work_dir,
    download_package,
    find_wapt_python,
    path_converter,
    plan_imports,
    resolve_requests,
    run_wapt_helper,
    sign_packages,
    upload_package,
)
from .notify import NotifyError, notify
from .packages import OS_FAMILIES, OS_LABELS, PackageEntry, PackageFilters, index_by_family, parse_packages_index
from .picker import Choice, pick
from .progress import console, phase_progress
from .report import import_candidates, render_html, to_dict, write_csv, write_json
from .server import WaptServer, WaptServerError, load_inventory, make_session

log = logging.getLogger("wapt_analyzer")


def _csv_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _common_options() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    srv = common.add_argument_group("server")
    srv.add_argument("--server", dest="server_url", help="WAPT server URL, e.g. https://wapt.example.org")
    srv.add_argument("--user", help="Admin user (password: $WAPT_PASSWORD, password_file or prompt)")
    srv.add_argument("--password-file", help="File containing the password (must be chmod 600)")
    srv.add_argument("--totp", help="TOTP code, when the account requires MFA (default: $WAPT_TOTP or prompt)")
    srv.add_argument("--client-certificate", help="TLS client certificate, when the server requires one")
    srv.add_argument("--client-private-key", help="Key of the client certificate (default: same path with .pem)")
    srv.add_argument("--client-key-password-file", help="File containing the client key passphrase (chmod 600)")
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


def _signing_options(parser: argparse.ArgumentParser) -> argparse._ArgumentGroup:
    sig = parser.add_argument_group("signing")
    sig.add_argument("--certificate", help="Signer certificate (.crt)")
    sig.add_argument("--private-key", help="Private key (.pem, default: certificate path with .pem)")
    sig.add_argument("--key-password-file", help="File containing the key passphrase (chmod 600)")
    sig.add_argument("--wapt-python", help="waptpython interpreter of a WAPT agent (default: auto-detect)")
    sig.add_argument("--keep-files", action="store_true", default=None,
                     help="Keep the downloaded and signed packages after the upload (default: deleted)")
    return sig


def _work_dir(cfg: dict, wapt_python: str) -> Path:
    if cfg["import"]["work_dir"]:
        return Path(cfg["import"]["work_dir"]).expanduser()
    return default_work_dir(wapt_python, Path(cfg["cache"]["directory"]).expanduser())


def _purge(*paths: Path | None) -> None:
    """Delete local package files once uploaded: downloads and signed packages fill the disk quickly."""
    for path in paths:
        if path is None:
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError as e:
            log.warning("Cannot delete %s: %s", path, e)


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
    out.add_argument("--notify", action="store_true",
                     help="Send the summary to the destinations of [notify] (e-mail, webhooks)")
    out.add_argument("-q", "--quiet", action="store_true", help="Print nothing but errors (for cron)")

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
    src.add_argument("-i", "--interactive", action="store_true",
                     help="Choose the packages in a checklist in the terminal")
    src.add_argument("--no-deps", action="store_true", help="Do not add missing dependencies")
    src.add_argument("--force", action="store_true", help="Import even if the repository has the same or newer")
    act = imp.add_argument_group("action")
    act.add_argument("--apply", action="store_true", help="Really download, sign and upload (default: dry run)")
    act.add_argument("--no-upload", action="store_true", help="Sign only, keep packages in --output-dir")
    act.add_argument("--output-dir", help="Where signed packages are written (default: <cache>/import/signed)")
    act.add_argument("-y", "--yes", action="store_true", help="Do not ask for confirmation")
    sig = _signing_options(imp)
    sig.add_argument("--set-maturity", help="Maturity of the imported packages (default: keep the store one)")
    act.add_argument("--cleanup", action="store_true",
                     help="After a successful upload, remove the versions superseded by the imported packages")
    act.add_argument("--upgrade-hosts", action="store_true",
                     help="After a successful upload, ask the connected hosts having these packages to upgrade now")
    trust = imp.add_argument_group("source verification")
    trust.add_argument("--verify", choices=["full", "control", "none"],
                       help="Source package verification: files + metadata (full, default), metadata only, or none")
    trust.add_argument("--trusted-cert", action="append", metavar="PATH",
                       help="Certificate file or directory trusted to verify source packages (repeatable)")
    trust.add_argument("--trusted-fingerprint", action="append", metavar="SHA256",
                       help="Trust the certificate with this SHA-256 fingerprint shipped in the source index "
                            "(repeatable; default: Tranquil IT for the Tranquil IT store)")

    hst = sub.add_parser(
        "hosts", parents=[common],
        help="Complete the host packages with the packages installed on each host (dry run by default)",
        description="Add to each host package the WAPT packages installed on the host that it does not list yet "
                    "(neither dependencies of another package nor provided by a group), and with --adopt the "
                    "repository packages of software installed outside WAPT. Nothing is ever removed.",
    )
    hst.add_argument("names", nargs="*", metavar="HOST", help="Restrict to these hosts (name, FQDN or uuid)")
    hst.add_argument("--adopt", action="store_true",
                     help="Also add the repository packages of software installed outside WAPT")
    hst.add_argument("--groups", action="store_true",
                     help="Also add the repository groups whose packages are mostly installed on the host")
    hst.add_argument("-i", "--interactive", action="store_true", help="Choose the additions in a checklist")
    hst.add_argument("--apply", action="store_true", help="Really sign and upload the host packages")
    hst.add_argument("--no-upload", action="store_true", help="Sign only, keep the host packages in --output-dir")
    hst.add_argument("-y", "--yes", action="store_true", help="Do not ask for confirmation")
    hst.add_argument("--output-dir", help="Where host packages are written (default: <cache>/import/hosts)")
    _signing_options(hst)

    grp = sub.add_parser(
        "groups", parents=[common],
        help="Recreate the group packages deployed on hosts but gone from the repository, suggest new ones",
        description="Rebuild each group package installed on hosts and absent from the repository from its highest "
                    "installed version, and suggest per OS family a common base group of the packages installed on "
                    "most hosts (--create-suggested to create it). Dry run by default.",
    )
    grp.add_argument("names", nargs="*", metavar="GROUP", help="Restrict to these groups")
    grp.add_argument("--create-suggested", action="store_true", help="Also create the suggested groups")
    grp.add_argument("--keep-missing", action="store_true",
                     help="Keep in recreated groups the dependencies absent from the repository")
    grp.add_argument("-i", "--interactive", action="store_true", help="Choose the groups in a checklist")
    grp.add_argument("--apply", action="store_true", help="Really sign and upload the group packages")
    grp.add_argument("--no-upload", action="store_true", help="Sign only, keep the packages in --output-dir")
    grp.add_argument("-y", "--yes", action="store_true", help="Do not ask for confirmation")
    grp.add_argument("--output-dir", help="Where group packages are written (default: <cache>/import/groups)")
    _signing_options(grp)

    cln = sub.add_parser(
        "cleanup", parents=[common],
        help="Remove from the repository the package versions no host can see any more (dry run by default)",
        description="A version is removed only when a newer version of the same package covers it entirely "
                    "(same maturity, OS, compatible architecture and locale, OS version range included), "
                    "and no dependency pins it.",
    )
    cln.add_argument("packages", nargs="*", help="Restrict to these packages (tsi-firefox or firefox)")
    cln.add_argument("--keep", type=int, help="Also keep this many previous versions (default: 0)")
    cln.add_argument("--all-prefixes", action="store_true",
                     help="Also clean packages that do not carry your prefix")
    cln.add_argument("--unused", action="store_true",
                     help="Remove instead the packages no host has installed, waits for or gets through a dependency, "
                          "and list the dependencies missing from the repository")
    cln.add_argument("--min-age", type=int, metavar="DAYS",
                     help="With --unused: keep the packages signed less than DAYS ago (default: 30)")
    cln.add_argument("--apply", action="store_true", help="Really delete (default: dry run)")
    cln.add_argument("-y", "--yes", action="store_true", help="Do not ask for confirmation")

    upg = sub.add_parser(
        "upgrade", parents=[common],
        help="Ask the agents to apply their pending upgrades now (dry run by default)",
        description="Send a signed upgrade (update, download, upgrade) or update action to the connected agents, "
                    "as the WAPT console does. Default targets: the hosts with pending installs or upgrades in the "
                    "inventory. Disconnected hosts are skipped unless --wake wakes them up first.",
    )
    upg.add_argument("names", nargs="*", metavar="HOST", help="Restrict to these hosts (name, FQDN or uuid)")
    tgt = upg.add_mutually_exclusive_group()
    tgt.add_argument("--all", action="store_true", help="Target every host, not only those with pending installs")
    tgt.add_argument("--packages", type=_csv_list,
                     help="Target the hosts having these packages (tsi-firefox or firefox, comma separated)")
    upg.add_argument("--update-only", action="store_true",
                     help="Only refresh the package index of the agents (no install)")
    upg.add_argument("--wake", action="store_true", help="Wake-on-LAN the disconnected targets, then wait for them")
    upg.add_argument("--wait", type=int, default=180, metavar="SECONDS",
                     help="With --wake: how long to wait for the hosts to connect (default: 180)")
    upg.add_argument("--apply", action="store_true", help="Really send the actions (default: dry run)")
    upg.add_argument("-y", "--yes", action="store_true", help="Do not ask for confirmation")
    _signing_options(upg)

    prg = sub.add_parser(
        "purge",
        help="Delete the downloaded and signed packages left in the work directory (dry run by default)",
        description="Empty the downloads/, signed/, hosts/ and groups/ subdirectories of the work directory "
                    "([import] work_dir). The trusted certificates are kept.",
    )
    prg.add_argument("--cache-dir", help="Cache directory")
    prg.add_argument("--wapt-python", help="waptpython interpreter of a WAPT agent (default: auto-detect)")
    prg.add_argument("--apply", action="store_true", help="Really delete (default: dry run)")
    prg.add_argument("-y", "--yes", action="store_true", help="Do not ask for confirmation")
    return parser


def apply_args(cfg: dict, args: argparse.Namespace) -> dict:
    mapping = {
        "server_url": ("server", "url"), "user": ("server", "user"), "password_file": ("server", "password_file"),
        "totp": ("server", "totp"), "client_certificate": ("server", "client_certificate"),
        "client_private_key": ("server", "client_private_key"),
        "client_key_password_file": ("server", "client_key_password_file"),
        "workers": ("server", "workers"), "prefix": ("repo", "prefix"), "repo_url": ("repo", "url"),
        "store_url": ("store", "url"), "store_prefix": ("store", "prefix"),
        "families": ("filters", "families"),
        "maturity": ("filters", "maturities"), "locale": ("filters", "locales"),
        "threshold": ("matching", "threshold"), "output": ("report", "output"), "json": ("report", "json"),
        "csv_dir": ("report", "csv_dir"), "lang": ("report", "language"), "cache_dir": ("cache", "directory"),
        "certificate": ("signing", "certificate"), "private_key": ("signing", "private_key"),
        "key_password_file": ("signing", "key_password_file"), "wapt_python": ("signing", "wapt_python"),
        "set_maturity": ("import", "maturity"), "verify": ("import", "verify"), "keep": ("cleanup", "keep"),
        "keep_files": ("import", "keep_files"), "min_age": ("cleanup", "unused_min_age"),
    }
    for attr, (section, key) in mapping.items():
        value = getattr(args, attr, None)
        if value is not None:
            cfg[section][key] = value
    if getattr(args, "trusted_cert", None):
        cfg["store"]["trusted_certs"] = args.trusted_cert
    if getattr(args, "trusted_fingerprint", None):
        cfg["store"]["trusted_fingerprints"] = args.trusted_fingerprint
    if getattr(args, "arch", None) is not None:
        cfg["filters"]["architectures"] = {f: args.arch for f in OS_FAMILIES}
    if getattr(args, "insecure", False):
        cfg["server"]["verify_ssl"] = False
    elif getattr(args, "ca_bundle", None):
        cfg["server"]["verify_ssl"] = args.ca_bundle
    client_cert = cfg["server"]["client_certificate"]
    if client_cert and not cfg["server"]["client_private_key"]:
        pem = Path(client_cert).expanduser().with_suffix(".pem")
        if pem.is_file() and pem != Path(client_cert).expanduser():
            cfg["server"]["client_private_key"] = str(pem)  # otherwise the key is in the certificate file
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
    repo_entries: list[PackageEntry]
    session: requests.Session | None = None   # WAPT server session (TLS settings, client certificate)


def server_session(cfg: dict) -> requests.Session:
    srv = cfg["server"]
    return make_session(srv["verify_ssl"], srv["client_certificate"], srv["client_private_key"],
                        key_password=lambda: resolve_client_key_password(cfg))


def connect(cfg: dict, idx: Indexes) -> WaptServer:
    """Server client on the shared session; the TOTP code is only asked if the account requires it."""
    return WaptServer(idx.server_url, cfg["server"]["user"], resolve_password(cfg), verify=cfg["server"]["verify_ssl"],
                      session=idx.session or server_session(cfg), totp=lambda: resolve_totp(cfg))


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
    session = None if cache.offline else server_session(cfg)
    repo_entries = parse_packages_index(fetch_cached(f"{repo_url}/Packages", cache, session=session,
                                                     verify=cfg["server"]["verify_ssl"]))
    store_data = fetch_cached(f"{store_url}/Packages", cache)
    store_entries = parse_packages_index(store_data)
    idx = Indexes(server_url, repo_url, store_url, index_by_family(repo_entries),
                  index_by_family(store_entries, filters), store_entries, store_data, filters, repo_entries, session)
    for fam in OS_FAMILIES:
        log.info("%s: %d packages in repository, %d eligible in store", fam, len(idx.repo[fam]), len(idx.store[fam]))
    return idx


def _cache(cfg: dict, offline: bool = False) -> Cache:
    return Cache(Path(cfg["cache"]["directory"]).expanduser(), offline=offline)


def run_analysis(cfg: dict, idx: Indexes, hosts: list) -> AnalysisResult:
    return analyze(
        idx.repo, idx.store, hosts,
        store_prefix=cfg["store"]["prefix"],
        threshold=float(cfg["matching"]["threshold"]),
        exclude=cfg["matching"]["exclude"],
        exclude_keys=cfg["matching"]["exclude_keys"],
        exclude_publishers=cfg["matching"]["exclude_publishers"],
        mappings=cfg["mappings"],
        ignore_system_components=cfg["matching"]["ignore_system_components"],
        updates=find_updates(idx.repo, idx.store_entries, idx.filters, cfg["store"]["prefix"]),
        fold_profiles=cfg["matching"]["fold_profiles"],
        fold_publishers=cfg["matching"]["fold_publishers"],
    )


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
        server = connect(cfg, idx)
    hosts = load_inventory(server, cache, workers=int(cfg["server"]["workers"]))
    families = cfg["filters"]["families"]
    if families:
        hosts = [h for h in hosts if h.os_family in families]

    result = run_analysis(cfg, idx, hosts)
    lang = cfg["report"]["language"]
    context = {
        "server_url": idx.server_url, "repo_url": idx.repo_url, "store_url": idx.store_url,
        "prefix": prefix, "store_prefix": cfg["store"]["prefix"],
        "icons_url": f"{idx.store_url}/icons",
        "store_page_url": f"https://wapt.tranquil.it/store/{lang}" if "wapt.tranquil.it" in idx.store_url else "",
    }
    data = to_dict(result, context, lang, restricted_licences=cfg["store"]["restricted_licences"])
    stale_days = int(cfg["deployments"]["stale_days"])
    add_deployments_to_report(data, track_deployments(hosts, stale_days), stale_days)
    if prefix:
        add_to_report(data, plan_hosts(hosts, idx.repo_entries, prefix, unmanaged=result.software_unmanaged,
                                       exclude=cfg["hosts"]["exclude"], assign_groups=True,
                                       assign_share=float(cfg["groups"]["assign_share"])))
        add_groups_to_report(data, *plan_groups(cfg, idx, hosts))

    say = (lambda *a: None) if args.quiet else print
    html = render_html(data)
    output = cfg["report"]["output"]
    if output and output != "-":
        Path(output).write_text(html, encoding="utf-8")
        say(f"HTML report: {output}")
    if cfg["report"]["json"]:
        write_json(data, Path(cfg["report"]["json"]))
        say(f"JSON report: {cfg['report']['json']}")
    if cfg["report"]["csv_dir"]:
        for p in write_csv(data, Path(cfg["report"]["csv_dir"])):
            say(f"CSV: {p}")

    sm = data["summary"]
    say(f"{sm['hosts']} hosts | {sm['missing_packages']} missing packages | "
        f"{sm['software_to_import']} software to import | {sm['software_unmanaged']} outside WAPT | "
        f"{sm['software_unmatched']} unmatched (+{sm['software_folded']} folded) | {sm['outdated']} outdated")
    say(f"Deployments: {sm['deploy_error_hosts']} host(s) in error ({sm['deploy_errors']} package(s)) | "
        f"{sm['deploy_pending_hosts']} with pending installs | {sm['stale_hosts']} silent for "
        f"{stale_days}+ days")
    if args.notify and notify(cfg, data, cache, html):
        return 1
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


def run_cleanup(cfg: dict, idx: Indexes, *, names: list[str], apply: bool, yes: bool,
                all_prefixes: bool = False, server: WaptServer | None = None) -> int:
    """Plan (and with ``apply``, perform) the removal of superseded versions."""
    prefix = "" if all_prefixes else cfg["repo"]["prefix"]
    plan = plan_cleanup(idx.repo_entries, keep=int(cfg["cleanup"]["keep"]), names=names,
                        exclude=tuple(cfg["cleanup"]["exclude"]), prefix=prefix)
    todo = [i for i in plan if not i.skip]
    if not plan:
        print("Nothing to clean: every package version is still the latest for some host.")
        return 0
    print(f"Cleanup plan ({len(todo)} to delete, {len(plan) - len(todo)} kept):")
    for item in plan:
        e = item.entry
        status = f"KEEP ({item.skip})" if item.skip else "DELETE"
        print(f"  {status:<8} {e.package} {e.version}  {e.target_os or 'all'} {e.architecture}"
              f"{' min_os=' + e.get('min_os_version') if e.get('min_os_version') else ''}"
              f"  [superseded by {item.latest.version}]")
    total = sum(int(i.entry.get("size") or 0) for i in todo)
    print(f"Space freed: {_human_size(total)}")
    if not todo:
        return 0
    if not apply:
        print("Dry run: nothing deleted. Add --apply to delete.")
        return 0
    if not yes and sys.stdin.isatty():
        if input(f"Delete {len(todo)} package version(s) from {idx.server_url}? This cannot be undone. [y/N] "
                 ).strip().lower() not in ("y", "yes", "o", "oui"):
            print("Aborted.")
            return 1
    own_session = server is None
    if own_session:
        server = connect(cfg, idx)
        server.login()
    try:
        result = delete_packages(server, [i.entry.get("package_uuid") for i in todo])
    finally:
        if own_session:
            server.logout()
    deleted, errors = result.get("deleted") or [], result.get("errors") or []
    print(f"{len(deleted)} deleted, {len(errors)} error(s).")
    for err in errors:
        print(f"  ERROR {err}")
    return 1 if errors or len(deleted) < len(todo) else 0


def run_unused(cfg: dict, args: argparse.Namespace, idx: Indexes, cache: Cache) -> int:
    """Plan (and with --apply, perform) the removal of the packages no host uses."""
    server = connect(cfg, idx)
    server.login()
    try:
        hosts = load_inventory(server, cache, workers=int(cfg["server"]["workers"]), session=False)
        c = cfg["cleanup"]
        plan = plan_unused(idx.repo_entries, hosts, prefix="" if args.all_prefixes else cfg["repo"]["prefix"],
                           names=args.packages, exclude=tuple(c["exclude"]) + tuple(cfg["import"]["exclude"]),
                           min_age_days=int(c["unused_min_age"]))
        missing = missing_dependencies(idx.repo_entries, hosts)
        if missing:
            print(f"Dependencies missing from the repository ({len(missing)}): hosts cannot install them")
            for dep, users in missing.items():
                print(f"  {dep}  <- {', '.join(users)}")
            print()
        todo = [i for i in plan if not i.skip]
        if not plan:
            print(f"No unused package: every package is installed on, or required by, one of the {len(hosts)} hosts.")
            return 0
        print(f"Unused packages ({len(todo)} to delete, {len(plan) - len(todo)} kept), on none of the "
              f"{len(hosts)} hosts:")
        for item in plan:
            latest = item.versions[0]
            status = f"KEEP ({item.skip})" if item.skip else "DELETE"
            print(f"  {status:<8} {item.package} {latest.version}  {latest.target_os or 'all'}"
                  f"{f'  (+{len(item.versions) - 1} older version(s))' if len(item.versions) > 1 else ''}")
        print(f"Space freed: {_human_size(sum(i.size for i in todo))}")
        if not todo:
            return 0
        if not args.apply:
            print("Dry run: nothing deleted. Add --apply to delete.")
            return 0
        uuids = [e.get("package_uuid") for i in todo for e in i.versions]
        if not args.yes and sys.stdin.isatty():
            answer = input(f"Delete {len(todo)} package(s) ({len(uuids)} version(s)) from {idx.server_url}? "
                           "This cannot be undone. [y/N] ").strip().lower()
            if answer not in ("y", "yes", "o", "oui"):
                print("Aborted.")
                return 1
        result = delete_packages(server, uuids)
    finally:
        server.logout()
    deleted, errors = result.get("deleted") or [], result.get("errors") or []
    print(f"{len(deleted)} version(s) deleted, {len(errors)} error(s).")
    for err in errors:
        print(f"  ERROR {err}")
    return 1 if errors or len(deleted) < len(uuids) else 0


def _host_matches(host, names: list[str]) -> bool:
    wanted = {n.lower() for n in names}
    return not wanted or bool({host.name.lower(), host.name.split(".")[0].lower(), host.uuid.lower()} & wanted)


def cmd_hosts(cfg: dict, args: argparse.Namespace) -> int:
    prefix = cfg["repo"]["prefix"]
    if not prefix:
        log.error("No prefix: use --prefix or [repo] prefix in the configuration")
        return 2
    if args.interactive and not sys.stdin.isatty():
        log.error("--interactive needs a terminal")
        return 2
    cache = _cache(cfg)
    idx = load_indexes(cfg, cache)
    server = connect(cfg, idx)
    server.login()
    try:
        hosts = [h for h in load_inventory(server, cache, workers=int(cfg["server"]["workers"]), session=False)
                 if _host_matches(h, args.names)]
        if not hosts:
            log.error("No host matches %s", " ".join(args.names))
            return 2
        try:
            stored = server.host_packages()
        except WaptServerError as e:   # e.g. encrypted host packages: fall back to the inventory
            log.warning("Cannot read the host packages from the server (%s): using the inventory", e)
            stored = {}
        unmanaged = run_analysis(cfg, idx, hosts).software_unmanaged if args.adopt else []
        plans = plan_hosts(hosts, idx.repo_entries, prefix, unmanaged=unmanaged, exclude=cfg["hosts"]["exclude"],
                           server_packages=stored, assign_groups=args.groups,
                           assign_share=float(cfg["groups"]["assign_share"]))
        return _run_hosts(cfg, args, idx, server, plans, stored)
    finally:
        server.logout()


def _run_hosts(cfg: dict, args: argparse.Namespace, idx: Indexes, server: WaptServer, plans: list,
               stored: dict) -> int:
    if args.interactive:
        choices = [Choice((i, a.package), plan.host.name, (a.package, a.reason), selected=True)
                   for i, plan in enumerate(plans) for a in plan.additions]
        if choices:
            picked = pick(choices, f"Dépendances à ajouter aux paquets machine ({len(choices)})")
            if picked is None:
                print("Aborted.")
                return 1
            keep = set(picked)
            for i, plan in enumerate(plans):
                plan.additions = [a for a in plan.additions if (i, a.package) in keep]

    todo = [p for p in plans if p.needs_upload]
    print(f"Host packages plan ({len(todo)} to upload, {len(plans) - len(todo)} unchanged):")
    for plan in plans:
        if not plan.needs_upload and not plan.not_in_repo and not plan.missing_groups:
            continue
        os_label = OS_LABELS.get(plan.family, plan.family)
        if not plan.needs_upload:
            print(f"  {plan.host.name} ({os_label}): nothing to add")
        else:
            if plan.missing_on_server:
                state = (f"missing from the server (installed v{plan.version}), "
                         f"recreated as v{next_version(plan.version)}")
            elif plan.exists:
                state = f"v{plan.version} -> v{next_version(plan.version)}"
            else:
                state = "absent, created"
            print(f"  {plan.host.name} ({os_label}): host package {state}, "
                  f"{len(plan.current)} -> {len(plan.depends)} dependencies")
        for a in plan.additions:
            print(f"    + {a.package:<32} {a.reason}")
        if plan.missing_groups:
            print(f"    ! installed groups missing from the repository (recreate them with the groups command): "
                  f"{', '.join(plan.missing_groups)}")
        if plan.not_in_repo:
            print(f"    ! installed but missing from the repository: {', '.join(plan.not_in_repo)}")
    if not todo:
        return 0
    if not args.apply:
        print("Dry run: nothing done. Add --apply to sign and upload the host packages.")
        return 0

    jobs = [ManagementJob(p.host.uuid, p.host.name, "host",
                          control_for(p, stored.get(p.host.uuid) or stored.get(p.host.name)))
            for p in todo]
    return publish_management(cfg, args, idx, server, jobs, kind="host", subdir="hosts",
                              endpoint="api/v3/upload_hosts")


@dataclass
class ManagementJob:
    """A host or group package to build from its control attributes."""
    source: str           # unique key (host uuid, group name)
    label: str
    section: str          # host / group
    control: dict
    inc: bool = True      # increment the version


def publish_management(cfg: dict, args: argparse.Namespace, idx: Indexes, server: WaptServer,
                       jobs: list[ManagementJob], *, kind: str, subdir: str, endpoint: str) -> int:
    """Build, sign (WAPT helper, key unlocked once) and upload host or group packages."""
    signing = cfg["signing"]
    if not signing["certificate"]:
        log.error("No signer certificate: use --certificate or [signing] certificate")
        return 2
    wapt_python = find_wapt_python(signing["wapt_python"])
    if not args.yes and sys.stdin.isatty():
        target = "Sign" if args.no_upload else f"Sign and upload to {idx.server_url}"
        if input(f"{target} {len(jobs)} {kind} package(s)? [y/N] ").strip().lower() not in ("y", "yes", "o", "oui"):
            print("Aborted.")
            return 1
    work_dir = _work_dir(cfg, wapt_python)
    output_dir = Path(args.output_dir or work_dir / subdir).expanduser()
    conv = path_converter(wapt_python)
    by_source = {j.source: j for j in jobs}
    spec = {"certificate": conv(Path(signing["certificate"]).expanduser()),
            "private_key": conv(Path(signing["private_key"]).expanduser()),
            "password": resolve_key_password(cfg),
            "jobs": [{"source": j.source, "section": j.section, "inc": j.inc, "control": j.control,
                      "output_dir": conv(output_dir)} for j in jobs]}
    failed = 0
    for res in run_wapt_helper(wapt_python, spec):
        job = by_source.get(res.get("source"))
        if job is None or "ok" not in res:
            continue
        if not res["ok"]:
            log.error("%s: %s", job.label, res.get("error"))
            log.debug("%s", res.get("trace"))
            failed += 1
            continue
        path = output_dir / res["filename"]
        if args.no_upload:
            print(f"  {job.label}: {kind} package v{res['version']} signed: {path}")
            continue
        try:
            upload_package(server, path, endpoint=endpoint)
            if not cfg["import"]["keep_files"]:
                _purge(path)
            deps = len([d for d in (res.get("depends") or "").split(",") if d])
            print(f"  {job.label}: {kind} package v{res['version']} uploaded ({deps} dependencies)")
        except (ImportFailed, requests.RequestException) as e:
            log.error("%s: %s", job.label, e)
            failed += 1
    print(f"{len(jobs) - failed} {kind} package(s) {'signed' if args.no_upload else 'uploaded'}, {failed} failed.")
    return 1 if failed else 0


def plan_groups(cfg: dict, idx: Indexes, hosts: list) -> tuple[list[GroupPlan], list[GroupPlan]]:
    g = cfg["groups"]
    recreate = plan_missing_groups(hosts, idx.repo_entries, keep_missing=bool(g["keep_missing"]))
    suggested = suggest_groups(hosts, idx.repo_entries, cfg["repo"]["prefix"], extra_groups=recreate,
                               min_share=float(g["suggest_share"]), min_hosts=int(g["suggest_min_hosts"]),
                               name=g["suggest_name"])
    return recreate, suggested


def cmd_groups(cfg: dict, args: argparse.Namespace) -> int:
    if not cfg["repo"]["prefix"]:
        log.error("No prefix: use --prefix or [repo] prefix in the configuration")
        return 2
    if args.interactive and not sys.stdin.isatty():
        log.error("--interactive needs a terminal")
        return 2
    if args.keep_missing:
        cfg["groups"]["keep_missing"] = True
    cache = _cache(cfg)
    idx = load_indexes(cfg, cache)
    server = connect(cfg, idx)
    server.login()
    try:
        hosts = load_inventory(server, cache, workers=int(cfg["server"]["workers"]), session=False)
        families = cfg["filters"]["families"]
        if families:
            hosts = [h for h in hosts if h.os_family in families]
        recreate, suggested = plan_groups(cfg, idx, hosts)
        if args.names:
            recreate = [p for p in recreate if p.package in args.names]
            suggested = [p for p in suggested if p.package in args.names]
        return _run_groups(cfg, args, idx, server, recreate, suggested)
    finally:
        server.logout()


def _run_groups(cfg: dict, args: argparse.Namespace, idx: Indexes, server: WaptServer,
                recreate: list[GroupPlan], suggested: list[GroupPlan]) -> int:
    print(f"Groups to recreate ({len(recreate)}): installed on hosts, absent from the repository")
    for p in recreate:
        version = f"v{p.version} -> v{next_version(p.version)}" if p.changed else f"v{p.version}"
        print(f"  {p.package} {version}, {len(p.depends)} dependencies, installed on {len(p.hosts)} host(s): "
              f"{', '.join(p.hosts)}")
        if p.missing:
            print(f"    ! left out, absent from the repository: {', '.join(p.missing)}")
    print(f"Suggested groups ({len(suggested)}): packages installed on most hosts of an OS family")
    for p in suggested:
        print(f"  {p.package} ({OS_LABELS.get(p.family, p.family)}, {len(p.hosts)} hosts):")
        for d in p.depends:
            print(f"    + {d:<32} {p.counts.get(d, 0)}/{len(p.hosts)} hosts")
    todo = recreate + (suggested if args.create_suggested else [])
    if args.interactive and todo:
        choices = [Choice(p.package, p.package,
                          ("à recréer" if p.kind == "recreate" else "suggéré", f"{len(p.depends)} dépendance(s)",
                           ", ".join(p.depends)), selected=True) for p in todo]
        picked = pick(choices, f"Paquets groupe à publier ({len(choices)})")
        if picked is None:
            print("Aborted.")
            return 1
        todo = [p for p in todo if p.package in picked]
    if not todo:
        return 0
    if not args.apply:
        print("Dry run: nothing done. Add --apply to sign and upload"
              + (" (and --create-suggested for the suggested groups)." if suggested and not args.create_suggested
                 else "."))
        return 0
    jobs = [ManagementJob(p.package, p.package, "group", group_control(p), inc=p.changed or p.kind == "suggested")
            for p in todo]
    code = publish_management(cfg, args, idx, server, jobs, kind="group", subdir="groups",
                              endpoint="api/v3/upload_packages")
    if suggested and args.create_suggested and not code and not args.no_upload:
        print("Assign the new groups to hosts with: uv run wapt-analyzer hosts --groups")
    return code


def cmd_cleanup(cfg: dict, args: argparse.Namespace) -> int:
    cache = _cache(cfg)
    idx = load_indexes(cfg, cache)
    if args.unused:
        return run_unused(cfg, args, idx, cache)
    return run_cleanup(cfg, idx, names=args.packages, apply=args.apply, yes=args.yes,
                       all_prefixes=args.all_prefixes)


def _package_names(cfg: dict, names: list[str]) -> list[str]:
    """Full package names: firefox -> tsi-firefox (names already carrying a prefix are kept)."""
    prefix = cfg["repo"]["prefix"]
    return [n if "-" in n and n.split("-", 1)[0] in (prefix, cfg["store"]["prefix"], "grp") or not prefix
            else f"{prefix}-{n}" for n in names]


def _pending_summary(packages: list[str], shown: int = 4) -> str:
    more = f" +{len(packages) - shown}" if len(packages) > shown else ""
    return f"{len(packages)} pending: {', '.join(packages[:shown])}{more}"


def cmd_upgrade(cfg: dict, args: argparse.Namespace) -> int:
    if args.wake and args.update_only:
        log.info("--wake with --update-only: the hosts will only refresh their index")
    cache = _cache(cfg)
    idx = load_indexes(cfg, cache)
    server = connect(cfg, idx)
    server.login()
    try:
        rows = server.hosts()
        if args.packages:
            names = _package_names(cfg, args.packages)
            reasons = dict.fromkeys(server.hosts_for_packages(names), ", ".join(names))
        elif args.all or args.names:
            reasons = {r["uuid"]: "" for r in rows}
        else:
            hosts = load_inventory(server, cache, workers=int(cfg["server"]["workers"]), session=False)
            reasons = {s.uuid: _pending_summary(["host package" if i.package.lower() == s.uuid.lower() else i.package
                                                 for i in s.pending])
                       for s in track_deployments(hosts) if s.pending}
        targets = [t for t in host_rows_to_targets(rows, reasons) if _host_matches(t, args.names)]
        return run_host_actions(cfg, args, server, targets, "update" if args.update_only else "upgrade",
                                wake=args.wake, wait=args.wait)
    finally:
        server.logout()


def run_host_actions(cfg: dict, args: argparse.Namespace, server: WaptServer, targets: list[Target], action: str,
                     *, wake: bool = False, wait: int = 0, key_password: str | None = None) -> int:
    """Plan, then with --apply sign and send the action to the connected targets."""
    if not targets:
        print("No host to upgrade.")
        return 0
    asleep = [t for t in targets if not t.reachable]
    print(f"Hosts to {action} ({len(targets) - len(asleep)} connected, {len(asleep)} disconnected):")
    for t in targets:
        state = "connected" if t.reachable else ("disconnected, to wake up" if wake else "disconnected, skipped")
        print(f"  {t.name} ({state})" + (f": {t.reason}" if t.reason else ""))
    if not args.apply:
        print(f"Dry run: nothing sent. Add --apply to send the {action} action.")
        return 0
    if not args.yes and sys.stdin.isatty():
        answer = input(f"Send the {action} action to {len(targets)} host(s)? [y/N] ").strip().lower()
        if answer not in ("y", "yes", "o", "oui"):
            print("Aborted.")
            return 1
    if wake and asleep:
        print(f"Wake-on-LAN sent to {len(asleep)} host(s), waiting up to {wait} s for them to connect…")
        wake_and_wait(server, targets, wait, on_wait=lambda n, total: log.info("%d/%d host(s) connected", n, total))
    ready = [t for t in targets if t.reachable]
    if not ready:
        print("No connected host: nothing sent.")
        return 1
    signing = cfg["signing"]
    if not signing["certificate"]:
        log.error("No signer certificate: use --certificate or [signing] certificate")
        return 2
    signed = sign_actions(build_actions(ready, action), wapt_python=find_wapt_python(signing["wapt_python"]),
                          certificate=signing["certificate"], private_key=signing["private_key"],
                          password=key_password if key_password is not None else resolve_key_password(cfg))
    server.trigger_host_action(signed)
    skipped = [t for t in targets if not t.reachable]
    print(f"{action.capitalize()} sent to {len(ready)} host(s)"
          + (f", {len(skipped)} disconnected host(s) skipped: {', '.join(t.name for t in skipped)}" if skipped else "")
          + ". Follow-up: the « Déploiements » tab of the next report.")
    return 0


PURGED_DIRS = ("downloads", "signed", "hosts", "groups")


def _tree_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def cmd_purge(cfg: dict, args: argparse.Namespace) -> int:
    """Delete the package files left in the work directory (failed uploads, --no-upload, --keep-files)."""
    try:
        wapt_python = find_wapt_python(cfg["signing"]["wapt_python"])
    except ImportFailed:
        wapt_python = ""  # no agent: nothing was signed through Windows, the work directory is in the cache
    work_dir = _work_dir(cfg, wapt_python)
    items: list[Path] = []
    total = 0
    for name in PURGED_DIRS:
        directory = work_dir / name
        if not directory.is_dir():
            continue
        entries = sorted(directory.iterdir())
        size = sum(_tree_size(e) for e in entries)
        if entries:
            print(f"  {directory}: {len(entries)} item(s), {_human_size(size)}")
        items += entries
        total += size
    if not items:
        print(f"Nothing to purge in {work_dir}.")
        return 0
    print(f"Space freed: {_human_size(total)}")
    if not args.apply:
        print("Dry run: nothing deleted. Add --apply to delete these files.")
        return 0
    if not args.yes and sys.stdin.isatty():
        answer = input(f"Delete {len(items)} item(s) from {work_dir}? [y/N] ").strip().lower()
        if answer not in ("y", "yes", "o", "oui"):
            print("Aborted.")
            return 1
    failed = 0
    for path in items:
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
        except OSError as e:
            log.error("Cannot delete %s: %s", path, e)
            failed += 1
    print(f"{len(items) - failed} item(s) deleted, {failed} failed.")
    return 1 if failed else 0


STAGES = {"verify": "vérification de la signature d'origine…", "sign": "signature…"}


def pick_requests(cfg: dict, idx: Indexes, requested: list, candidates: list[dict], preselect: bool):
    """Checklist of the import requests; None if cancelled. Packages already chosen are preselected,
    report candidates are not (a report often proposes many more packages than wanted)."""
    hosts = {c["filename"]: c["host_count"] for c in candidates}
    restricted = tuple(cfg["store"]["restricted_licences"])
    excluded = set(cfg["import"]["exclude"])
    choices = []
    for entry, fams in requested:
        local = next((idx.repo.get(f, {}).get(f"{cfg['repo']['prefix']}-{entry.base}") for f in fams), None)
        version = f"{local.version} → {entry.version}" if local else str(entry.version)
        detail = [version, ",".join(OS_LABELS.get(f, f) for f in fams), entry.architecture,
                  _human_size(int(entry.get("size") or 0))]
        detail.append(f"{hosts[entry.filename]} poste(s)" if entry.filename in hosts else "")
        detail.append(entry.name)
        lic = entry.restricted_by(restricted)
        disabled = (f"réservé aux abonnés : {lic}" if lic
                    else "exclu par la configuration" if entry.base in excluded else "")
        choices.append(Choice((entry, fams), entry.package, tuple(detail), selected=preselect and not disabled,
                              disabled=disabled))
    if not choices:
        return []
    return pick(choices, f"Paquets à importer depuis {idx.store_url} ({len(choices)})")


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
    if (args.cleanup or args.upgrade_hosts) and args.no_upload:
        log.error("--cleanup and --upgrade-hosts need the upload: they cannot be combined with --no-upload")
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
    if args.interactive:
        if not sys.stdin.isatty():
            log.error("--interactive needs a terminal")
            return 2
        requested = pick_requests(cfg, idx, requested, candidates, preselect=not args.from_report)
        if requested is None:
            print("Aborted.")
            return 1
        if not requested:
            print("Nothing selected.")
            return 0
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
        print("Dry run: nothing done. Add --apply to download, sign and upload."
              + (" The superseded versions will then be cleaned (--cleanup)." if args.cleanup else ""))
        return 0

    signing = cfg["signing"]
    if not signing["certificate"]:
        log.error("No signer certificate: use --certificate or [signing] certificate")
        return 2
    wapt_python = find_wapt_python(signing["wapt_python"])
    log.info("Using %s", wapt_python)

    # Trust is checked before asking anything: no point unlocking the key for an unverifiable source
    work_dir = _work_dir(cfg, wapt_python)
    log.info("Work directory: %s", work_dir)
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
        # Logged in before the long steps: a TOTP code is only valid for about 30 seconds
        server = connect(cfg, idx)
        server.login()
    try:
        return _run_import(cfg, args, idx, todo, server, key_password, wapt_python, work_dir, trusted)
    finally:
        if server:
            server.logout()


def _run_import(cfg: dict, args: argparse.Namespace, idx: Indexes, todo: list, server: WaptServer | None,
                key_password: str, wapt_python: str, work_dir: Path, trusted: list[Path]) -> int:
    """Download, sign, upload (and optionally clean) the planned packages."""
    signing, prefix = cfg["signing"], cfg["repo"]["prefix"]
    cleanup_code = upgrade_code = 0
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
                          on_stage=lambda item, stage: progress.update(
                              task, current=f"{item.entry.package}: {STAGES.get(stage, stage)}"),
                          on_done=signed_one)
            progress.update(task, current="")

    signed = [i for i in todo if i.result.get("ok")]
    if server and signed:
        paths = [Path(i.result["local_path"]) for i in signed]
        with phase_progress() as progress:
            task = progress.add_task("", total=sum(p.stat().st_size for p in paths), phase="Upload",
                                     current="")
            for item, path in zip(signed, paths, strict=True):
                progress.update(task, current=path.name)
                try:
                    upload_package(server, path, on_progress=lambda n: progress.advance(task, n))
                    item.result["uploaded"] = True
                    if not cfg["import"]["keep_files"]:
                        _purge(path, item.download_path)
                except (ImportFailed, requests.RequestException) as e:
                    item.result.update(ok=False, error=str(e))
                    log.error("%s: %s", path.name, e)
            progress.update(task, current="")

        uploaded = [i for i in signed if i.result.get("uploaded")]
        if args.cleanup and uploaded:
            # Fresh repository index: the server rebuilds it after each upload
            print("\nCleanup of the versions superseded by this import:")
            idx.repo_entries = parse_packages_index(fetch_cached(
                f"{idx.repo_url}/Packages", _cache(cfg), session=server.session, verify=cfg["server"]["verify_ssl"]))
            cleanup_code = run_cleanup(cfg, idx, names=[i.result["package"] for i in uploaded], apply=True,
                                       yes=args.yes, server=server)
        if args.upgrade_hosts and uploaded:
            names = sorted({i.result["package"] for i in uploaded})
            print("\nUpgrade of the hosts having the imported packages:")
            reasons = dict.fromkeys(server.hosts_for_packages(names), "")
            targets = host_rows_to_targets(server.hosts(), reasons)
            try:
                upgrade_code = run_host_actions(cfg, args, server, targets, "upgrade", key_password=key_password)
            except (ImportFailed, WaptServerError) as e:
                log.error("Host upgrade: %s", e)
                upgrade_code = 1

    failed = [i for i in todo if not i.result.get("ok")]
    kept = args.no_upload or cfg["import"]["keep_files"]
    print(f"\n{len(todo) - len(failed)} imported" + (" (signed only)" if args.no_upload else "")
          + f", {len(failed)} failed." + (f" Signed packages: {output_dir}" if kept else ""))
    for item in failed:
        print(f"  FAILED {item.entry.package}: {item.result.get('error', 'not processed')}")
    return 1 if failed or cleanup_code or upgrade_code else 0


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
        if args.command == "cleanup":
            return cmd_cleanup(cfg, args)
        if args.command == "hosts":
            return cmd_hosts(cfg, args)
        if args.command == "groups":
            return cmd_groups(cfg, args)
        if args.command == "upgrade":
            return cmd_upgrade(cfg, args)
        if args.command == "purge":
            return cmd_purge(cfg, args)
    except (WaptServerError, ImportFailed, NotifyError, RuntimeError, OSError, ValueError) as e:
        log.error("%s", e)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
