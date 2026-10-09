"""Import store packages into the user's repository: plan, download, re-sign (via waptpython), upload."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import shutil
import ssl
import subprocess
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import requests

from .fetch import USER_AGENT
from .packages import PackageEntry, entry_os_families, split_package_name

log = logging.getLogger(__name__)

HELPER = Path(__file__).with_name("wapt_helper.py")

WAPT_PYTHON_CANDIDATES = [
    "/opt/wapt/waptpython",                                      # Linux agent
    "/opt/wapt/bin/waptpython",
    "/Applications/wapt/waptpython",                             # macOS agent
    "/mnt/c/Program Files (x86)/wapt/waptpython.exe",            # Windows agent seen from WSL
    "/mnt/c/Program Files/wapt/waptpython.exe",
    r"C:\Program Files (x86)\wapt\waptpython.exe",               # native Windows
    r"C:\Program Files\wapt\waptpython.exe",
]


class ImportFailed(RuntimeError):
    pass


@dataclass
class PlannedImport:
    entry: PackageEntry                  # store package
    families: list[str]
    reason: str                          # "requested" or "dependency of <pkg>"
    target_name: str                     # package name after the prefix change
    skip: str = ""                       # non-empty: why it is not imported
    download_path: Path | None = None
    result: dict = field(default_factory=dict)


def _dep_names(value: str) -> list[str]:
    """``tis-foo(>=1.0),tis-bar`` -> ``['tis-foo', 'tis-bar']``"""
    return [re.split(r"[\s(<>=]", d.strip(), maxsplit=1)[0] for d in (value or "").split(",") if d.strip()]


def plan_imports(
    requested: list[tuple[PackageEntry, list[str]]],
    store: dict[str, dict[str, PackageEntry]],
    repo: dict[str, dict[str, PackageEntry]],
    prefix: str,
    *,
    with_deps: bool = True,
    force: bool = False,
    excluded_bases: tuple[str, ...] = (),
    restricted_licences: tuple[str, ...] = (),
) -> list[PlannedImport]:
    """Build the ordered import list (dependencies first) from requested store entries."""
    repo_bases = {fam: {e.base: e for e in idx.values()} for fam, idx in repo.items()}
    plan: dict[str, PlannedImport] = {}
    order: list[str] = []

    def add(entry: PackageEntry, families: list[str], reason: str, stack: tuple[str, ...] = ()) -> None:
        key = entry.filename or f"{entry.package}_{entry.version}"
        if key in plan:
            for fam in families:
                if fam not in plan[key].families:
                    plan[key].families.append(fam)
            return
        item = PlannedImport(entry=entry, families=list(families), reason=reason,
                             target_name=f"{prefix}-{entry.base}" if prefix else entry.package)
        plan[key] = item
        restricted = entry.restricted_by(restricted_licences)
        if entry.base in excluded_bases:
            item.skip = "excluded by configuration"
        elif restricted:
            item.skip = f"requires a subscription (licence {restricted})"
        elif entry.section != "base":
            item.skip = f"section {entry.section} not supported"
        elif not force:
            present = [repo_bases.get(fam, {}).get(entry.base) for fam in families]
            if present and all(p is not None and p.version >= entry.version for p in present):
                item.skip = f"already in repository ({present[0].package} {present[0].version})"
        if with_deps and not item.skip:
            for dep in _dep_names(entry.get("depends")):
                _, base = split_package_name(dep)
                for fam in families:
                    if base in repo_bases.get(fam, {}) or base in stack:
                        continue
                    dep_entry = next((e for e in store.get(fam, {}).values() if e.base == base), None)
                    if dep_entry is None:
                        log.warning("%s depends on %s, not found in store for %s", entry.package, dep, fam)
                        continue
                    add(dep_entry, [fam], f"dependency of {entry.package}", stack + (entry.base,))
        order.append(key)  # appended after its dependencies

    for entry, families in requested:
        add(entry, families, "requested")
    return [plan[k] for k in order]


def resolve_requests(
    names: list[str],
    report_candidates: list[dict],
    store_entries: list[PackageEntry],
    store: dict[str, dict[str, PackageEntry]],
    families: list[str],
) -> list[tuple[PackageEntry, list[str]]]:
    """Turn package names and/or report candidates into (store entry, OS families) pairs."""
    by_filename = {e.filename: e for e in store_entries if e.filename}
    result: list[tuple[PackageEntry, list[str]]] = []
    for cand in report_candidates:
        entry = by_filename.get(cand.get("filename", ""))
        if entry is None:
            log.warning("%s is no longer in the store index, skipped", cand.get("filename"))
            continue
        fams = [f for f in cand.get("os") or sorted(entry_os_families(entry)) if not families or f in families]
        if fams:
            result.append((entry, fams))
    for name in names:
        _, base = split_package_name(name) if "-" in name else ("", name)
        found = False
        for fam in families:
            exact = store.get(fam, {}).get(name)
            entry = exact or next((e for e in store.get(fam, {}).values() if e.base in (base, name)), None)
            if entry is not None:
                result.append((entry, [fam]))
                found = True
        if not found:
            log.warning("%s: no eligible store package for %s", name, ", ".join(families))
    return result


# --- trust ----------------------------------------------------------------------------------------

# Certificate signing the packages of the public Tranquil IT store
TRANQUIL_IT_FINGERPRINT = "8c5127a75392be9cc9afd0dbae1222a673072c308c14d88ab246e23832e8c6bb"
TRANQUIL_IT_HOSTS = ("wapt.tranquil.it", "store.wapt.fr")

_PEM_CERT_RE = re.compile(r"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", re.S)


def _fingerprint(pem_block: str) -> str:
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem_block)).hexdigest()


def _normalize_fp(value: str) -> str:
    return value.lower().replace(":", "").strip()


def default_fingerprints(store_url: str) -> list[str]:
    """The Tranquil IT certificate is pinned by default only for the Tranquil IT store."""
    host = re.sub(r"^\w+://", "", store_url).split("/")[0].split(":")[0].lower()
    return [TRANQUIL_IT_FINGERPRINT] if host in TRANQUIL_IT_HOSTS else []


def index_certificates(index_data: bytes) -> dict[str, str]:
    """Certificates shipped in a repository index (``ssl/*.crt``): fingerprint -> PEM."""
    certs = {}
    with zipfile.ZipFile(io.BytesIO(index_data)) as zf:
        for name in zf.namelist():
            if name.startswith("ssl/") and name.endswith(".crt"):
                for block in _PEM_CERT_RE.findall(zf.read(name).decode("ascii", errors="replace")):
                    certs[_fingerprint(block)] = block
    return certs


def _local_certificates(paths: list[str]) -> dict[str, str]:
    certs = {}
    for raw in paths:
        path = Path(raw).expanduser()
        files = sorted(path.glob("*.crt")) + sorted(path.glob("*.pem")) if path.is_dir() else [path]
        if not files or not all(f.is_file() for f in files):
            raise ImportFailed(f"Trusted certificate not found: {path}")
        for f in files:
            blocks = _PEM_CERT_RE.findall(f.read_text(encoding="ascii", errors="replace"))
            if not blocks and not path.is_dir():
                raise ImportFailed(f"No PEM certificate in {f}")
            for block in blocks:
                certs[_fingerprint(block)] = block
    return certs


def collect_trusted_certs(index_data: bytes, directory: Path, *, fingerprints: list[str],
                          cert_paths: list[str]) -> list[Path]:
    """Certificates trusted to verify source packages.

    - local certificate files / directories (``cert_paths``) are trusted as given;
    - certificates shipped in the source index are trusted only if their SHA-256 fingerprint is pinned.
    """
    wanted = {_normalize_fp(f) for f in fingerprints}
    shipped = index_certificates(index_data)
    local = _local_certificates(cert_paths)
    trusted = dict(local)
    trusted.update({fp: pem for fp, pem in shipped.items() if fp in wanted})
    missing = wanted - set(trusted)
    if missing:
        raise ImportFailed("Pinned certificate(s) found neither in the source index nor in trusted_certs: "
                           + ", ".join(sorted(missing)) + _describe(shipped))
    if not trusted:
        raise ImportFailed("No trusted certificate configured for this source: set [store] trusted_fingerprints "
                           "or trusted_certs (or --trusted-fingerprint / --trusted-cert)." + _describe(shipped))
    directory.mkdir(parents=True, exist_ok=True)
    for old in directory.glob("*.crt"):
        old.unlink()
    paths = []
    for fp, pem in trusted.items():
        path = directory / f"{fp}.crt"
        path.write_text(pem + "\n", encoding="ascii")
        paths.append(path)
    return paths


def _describe(shipped: dict[str, str]) -> str:
    if not shipped:
        return "\nThe source index ships no certificate."
    lines = []
    for fp, pem in shipped.items():
        subject = _subject(pem)
        lines.append(f"  {fp}  {subject}")
    return "\nCertificates shipped in the source index (check them before pinning):\n" + "\n".join(lines)


def _subject(pem: str) -> str:
    """Best-effort certificate subject, for display only."""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".crt", delete=False) as f:
        f.write(pem)
    try:
        info = ssl._ssl._test_decode_cert(f.name)  # noqa: SLF001 - stdlib helper, display only
        return ", ".join(f"{k}={v}" for rdn in info.get("subject", ()) for k, v in rdn)
    except Exception:
        return ""
    finally:
        os.unlink(f.name)


# --- download -------------------------------------------------------------------------------------

def download_package(store_url: str, entry: PackageEntry, directory: Path, session: requests.Session,
                     on_progress: Callable[[int], None] | None = None) -> Path:
    """Download a package file; ``on_progress(n)`` is called with each number of bytes received."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / entry.filename
    expected = entry.get("md5sum")
    if target.exists() and expected and _md5(target) == expected:
        log.info("Using cached %s", entry.filename)
        if on_progress:
            on_progress(target.stat().st_size)
        return target
    tmp = target.with_suffix(".part")
    url = f"{store_url}/{entry.filename}"
    log.info("Downloading %s", url)
    md5 = hashlib.md5()
    with session.get(url, stream=True, timeout=120) as resp:
        if resp.status_code in (401, 403):
            raise ImportFailed(f"HTTP {resp.status_code}: {entry.filename} is not publicly downloadable "
                               f"(licence: {entry.get('licence') or '?'}), a subscription is probably required")
        resp.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in resp.iter_content(1 << 18):
                f.write(chunk)
                md5.update(chunk)
                if on_progress:
                    on_progress(len(chunk))
    if expected and md5.hexdigest() != expected:
        tmp.unlink()
        raise ImportFailed(f"{entry.filename}: MD5 mismatch with the store index")
    tmp.replace(target)
    return target


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --- signing through waptpython --------------------------------------------------------------------

def find_wapt_python(configured: str = "") -> str:
    if configured:
        if not Path(configured).exists():
            raise ImportFailed(f"waptpython not found: {configured}")
        return configured
    for candidate in WAPT_PYTHON_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    found = shutil.which("waptpython")
    if found:
        return found
    raise ImportFailed("waptpython not found: install a WAPT agent or set [signing] wapt_python")


def is_windows_python_from_wsl(wapt_python: str) -> bool:
    return os.name != "nt" and wapt_python.lower().endswith(".exe")


def windows_work_dir() -> Path | None:
    """``%LOCALAPPDATA%\\wapt-analyzer\\import`` seen from WSL, or None if it cannot be resolved."""
    try:
        out = subprocess.run(["cmd.exe", "/c", "echo %LOCALAPPDATA%"], capture_output=True, text=True,
                             timeout=30, cwd="/mnt/c").stdout.strip()
        if not out or "%" in out:
            return None
        local = subprocess.run(["wslpath", "-u", out], capture_output=True, text=True, timeout=30,
                               check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(local) / "wapt-analyzer" / "import"


def default_work_dir(wapt_python: str, cache_dir: Path) -> Path:
    """Where packages are downloaded and signed.

    A Windows waptpython launched from WSL must work on the Windows filesystem: large writes from Windows
    to ``\\\\wsl.localhost\\...`` can stall indefinitely (seen while unzipping a 280 MB package).
    """
    if is_windows_python_from_wsl(wapt_python):
        work = windows_work_dir()
        if work is not None:
            return work
        log.warning("Cannot resolve %%LOCALAPPDATA%%: large packages may stall on the WSL share; "
                    "set [import] work_dir to a /mnt/c/... directory")
    return cache_dir / "import"


def _path_converter(wapt_python: str):
    """A Windows waptpython.exe launched from WSL needs Windows paths."""
    if is_windows_python_from_wsl(wapt_python):
        def convert(p) -> str:
            return subprocess.run(["wslpath", "-w", str(p)], check=True, capture_output=True, text=True).stdout.strip()
        return convert
    return str


def sign_packages(items: list[PlannedImport], *, wapt_python: str, certificate: str, private_key: str,
                  password: str, trusted_certs: list[Path], prefix: str, output_dir: Path,
                  maturity: str = "", verify: str = "full",
                  on_start: Callable[[PlannedImport], None] | None = None,
                  on_done: Callable[[PlannedImport], None] | None = None,
                  on_stage: Callable[[PlannedImport, str], None] | None = None) -> None:
    """Run wapt_helper.py with waptpython (one process: the key is unlocked once).

    Fills ``item.result`` for each item; ``on_start`` / ``on_done`` report progress.
    """
    conv = _path_converter(wapt_python)
    output_dir.mkdir(parents=True, exist_ok=True)
    by_source = {conv(i.download_path): i for i in items}
    spec = {
        "certificate": conv(Path(certificate).expanduser()),
        "private_key": conv(Path(private_key).expanduser()),
        "password": password,
        "trusted_certs": [conv(p) for p in trusted_certs],
        "prefix": prefix,
        "maturity": maturity or None,
        "verify": verify,
        "jobs": [{"source": src, "output_dir": conv(output_dir)} for src in by_source],
    }
    proc = subprocess.Popen([wapt_python, conv(HELPER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8")
    assert proc.stdin and proc.stdout
    proc.stdin.write(json.dumps(spec))
    proc.stdin.close()
    for line in proc.stdout:
        line = line.strip()
        if not line.startswith("{"):
            continue
        res = json.loads(line)
        item = by_source.get(res.get("source"))
        if item is None:
            continue
        if res.get("event") == "start":
            if on_start:
                on_start(item)
            continue
        if res.get("event") == "stage":
            if on_stage:
                on_stage(item, res.get("stage", ""))
            continue
        item.result = res
        if on_done:
            on_done(item)
        if res.get("ok"):
            res["local_path"] = str(output_dir / res["filename"])
            log.info("Signed %s -> %s", item.entry.filename, res["filename"])
        else:
            log.debug("%s", res.get("trace"))
    stderr = proc.stderr.read() if proc.stderr else ""
    code = proc.wait()
    for line in stderr.splitlines():
        if "legacy provider" not in line:
            log.warning("waptpython: %s", line)
    if code != 0:
        last = stderr.strip().splitlines()[-1] if stderr.strip() else f"exit code {code}"
        raise ImportFailed(f"waptpython failed: {last}")


# --- upload ---------------------------------------------------------------------------------------

class _MultipartFile:
    """Streamed multipart/form-data body holding a single file (no full read in memory)."""

    def __init__(self, path: Path, on_progress: Callable[[int], None] | None = None):
        self.on_progress = on_progress
        self.boundary = uuid.uuid4().hex
        name = path.name.replace('"', "")
        head = (f"--{self.boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{name}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode()
        tail = f"\r\n--{self.boundary}--\r\n".encode()
        self._parts = [head, path, tail]
        self._len = len(head) + path.stat().st_size + len(tail)
        self._current = None
        self._index = 0

    @property
    def content_type(self) -> str:
        return f"multipart/form-data; boundary={self.boundary}"

    def __len__(self) -> int:
        return self._len

    def read(self, size: int = -1) -> bytes:
        out = b""
        while self._index < len(self._parts) and (size < 0 or len(out) < size):
            part = self._parts[self._index]
            if isinstance(part, bytes):
                out += part
                self._index += 1
                continue
            if self._current is None:
                self._current = part.open("rb")
            chunk = self._current.read(-1 if size < 0 else size - len(out))
            if chunk:
                out += chunk
                if self.on_progress:
                    self.on_progress(len(chunk))
            else:
                self._current.close()
                self._current = None
                self._index += 1
        return out


def upload_package(server, path: Path, on_progress: Callable[[int], None] | None = None) -> dict:
    """Upload one signed package with an authenticated ``WaptServer`` session."""
    body = _MultipartFile(path, on_progress)
    resp = server.session.post(f"{server.url}/api/v3/upload_packages", data=body,
                               headers={"Content-Type": body.content_type, "User-Agent": USER_AGENT},
                               timeout=(30, 3600))
    try:
        payload = resp.json()
    except ValueError as e:
        raise ImportFailed(f"upload {path.name}: HTTP {resp.status_code}, non-JSON answer") from e
    if resp.status_code != 200 or not payload.get("success"):
        raise ImportFailed(f"upload {path.name}: HTTP {resp.status_code}: {payload.get('msg') or payload}")
    result = payload.get("result") or {}
    errors = result.get("errors") if isinstance(result, dict) else None
    if errors:
        raise ImportFailed(f"upload {path.name}: {errors}")
    return payload
