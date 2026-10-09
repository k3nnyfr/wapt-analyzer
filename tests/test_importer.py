import io
import json
import zipfile
from pathlib import Path

import pytest

from wapt_analyzer import importer
from wapt_analyzer.importer import (
    TRANQUIL_IT_FINGERPRINT,
    ImportFailed,
    PlannedImport,
    _MultipartFile,
    collect_trusted_certs,
    default_fingerprints,
    plan_imports,
    resolve_requests,
    sign_packages,
)
from wapt_analyzer.packages import PackageEntry, Version, index_by_family


def pkg(package, version="1.0-1", target_os="windows", **fields):
    return PackageEntry(package=package, version=Version(version),
                        fields={"package": package, "target_os": target_os, "section": "base",
                                "filename": f"{package}_{version}_{target_os}.wapt", **fields})


STORE_ENTRIES = [
    pkg("tis-dotnetfx", "4.8.1-24", depends="tis-dotnetfx4.8"),
    pkg("tis-dotnetfx4.8", "4.8.9-40"),
    pkg("tis-imageglass", "10.0-2", depends="tis-webview2(>=100),tis-dotnetfx"),
    pkg("tis-webview2", "154.0-12"),
    pkg("tis-firefox", "131.0-1"),
    pkg("tis-firefox", "131.0-1", target_os="darwin"),
    pkg("tis-waptupgrade", "2.7-1"),
]
STORE = index_by_family(STORE_ENTRIES)
REPO = index_by_family([pkg("tsi-webview2", "154.0-12"), pkg("tsi-firefox", "130.0-1")])


def test_plan_dependencies_first_and_skip_present():
    requested = resolve_requests(["imageglass", "tis-firefox"], [], STORE_ENTRIES, STORE, ["windows"])
    plan = plan_imports(requested, STORE, REPO, "tsi")
    names = [(p.entry.package, p.skip == "") for p in plan]
    # webview2 is already in the repo, dotnetfx4.8 must come before dotnetfx, both before imageglass
    assert names == [("tis-dotnetfx4.8", True), ("tis-dotnetfx", True), ("tis-imageglass", True),
                     ("tis-firefox", True)]
    assert plan[1].reason == "dependency of tis-imageglass"
    assert plan[2].target_name == "tsi-imageglass"


def test_plan_skips_up_to_date_excluded_and_force():
    requested = resolve_requests(["webview2", "waptupgrade"], [], STORE_ENTRIES, STORE, ["windows"])
    plan = plan_imports(requested, STORE, REPO, "tsi", excluded_bases=("waptupgrade",))
    assert plan[0].skip.startswith("already in repository")
    assert plan[1].skip == "excluded by configuration"
    forced = plan_imports(requested[:1], STORE, REPO, "tsi", force=True)
    assert forced[0].skip == ""


def test_plan_skips_restricted_licences():
    entries = STORE_ENTRIES + [pkg("tis-tailscale", licence="proprietary_restricted,wapt_enterprise")]
    store = index_by_family(entries)
    requested = resolve_requests(["tailscale"], [], entries, store, ["windows"])
    plan = plan_imports(requested, store, REPO, "tsi", restricted_licences=("wapt_enterprise", "wapt_entreprise"))
    assert plan[0].skip == "requires a subscription (licence wapt_enterprise)"
    assert plan_imports(requested, store, REPO, "tsi")[0].skip == ""


def test_plan_no_deps():
    requested = resolve_requests(["dotnetfx"], [], STORE_ENTRIES, STORE, ["windows"])
    assert [p.entry.package for p in plan_imports(requested, STORE, REPO, "tsi", with_deps=False)] == ["tis-dotnetfx"]


def test_resolve_from_report_candidates_per_os():
    candidates = [{"filename": "tis-firefox_131.0-1_darwin.wapt", "package": "tis-firefox", "os": ["macos"]},
                  {"filename": "gone.wapt", "package": "tis-gone", "os": ["windows"]}]
    requested = resolve_requests([], candidates, STORE_ENTRIES, STORE, ["windows", "macos"])
    assert [(e.filename, fams) for e, fams in requested] == [("tis-firefox_131.0-1_darwin.wapt", ["macos"])]
    plan = plan_imports(requested, STORE, REPO, "tsi")
    assert plan[0].skip == ""  # tsi-firefox exists for Windows only


PIN_CERT = Path(__file__).with_name("pin-test.crt")


def _index_with_cert() -> tuple[bytes, str]:
    import hashlib
    import ssl
    pem = PIN_CERT.read_text()
    fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Packages", "")
        zf.writestr(f"ssl/{fingerprint}.crt", pem)
    return buf.getvalue(), fingerprint


def test_trust_pinned_fingerprint_from_index(tmp_path):
    index, fingerprint = _index_with_cert()
    certs = collect_trusted_certs(index, tmp_path, fingerprints=[fingerprint.upper()], cert_paths=[])
    assert [c.stem for c in certs] == [fingerprint]
    with pytest.raises(ImportFailed, match="Pinned certificate"):
        collect_trusted_certs(index, tmp_path, fingerprints=["00" * 32], cert_paths=[])


def test_trust_nothing_configured_lists_index_certs(tmp_path):
    index, fingerprint = _index_with_cert()
    with pytest.raises(ImportFailed, match=fingerprint) as exc:
        collect_trusted_certs(index, tmp_path, fingerprints=[], cert_paths=[])
    assert "CN=pin-test" in str(exc.value) or "commonName=pin-test" in str(exc.value)


def test_trust_local_certificates(tmp_path):
    empty = io.BytesIO()
    with zipfile.ZipFile(empty, "w") as zf:
        zf.writestr("Packages", "")
    certs = collect_trusted_certs(empty.getvalue(), tmp_path / "t", fingerprints=[], cert_paths=[str(PIN_CERT)])
    assert len(certs) == 1
    by_dir = collect_trusted_certs(empty.getvalue(), tmp_path / "t", fingerprints=[],
                                   cert_paths=[str(PIN_CERT.parent)])
    assert [c.stem for c in by_dir] == [c.stem for c in certs]
    with pytest.raises(ImportFailed, match="not found"):
        collect_trusted_certs(empty.getvalue(), tmp_path / "t", fingerprints=[], cert_paths=["/nonexistent.crt"])


def test_default_fingerprints():
    assert default_fingerprints("https://wapt.tranquil.it/wapt") == [TRANQUIL_IT_FINGERPRINT]
    assert default_fingerprints("https://repo.internal.lan/wapt") == []


def test_multipart_body(tmp_path):
    f = tmp_path / "tsi-x_1.0-1_windows_PROD.wapt"
    f.write_bytes(b"PK" + b"x" * 5000)
    body = _MultipartFile(f)
    chunks = []
    while chunk := body.read(1000):
        chunks.append(chunk)
    data = b"".join(chunks)
    assert len(data) == len(body)
    assert b'name="tsi-x_1.0-1_windows_PROD.wapt"; filename="tsi-x_1.0-1_windows_PROD.wapt"' in data
    assert data.endswith(f"--{body.boundary}--\r\n".encode())
    assert b"PK" + b"x" * 5000 in data


def test_sign_packages_unlocks_key_once(tmp_path, monkeypatch):
    """All packages go to a single waptpython process: the key passphrase is sent (and the key decrypted) once."""
    calls = []

    class KeptStringIO(io.StringIO):
        def close(self):  # keep the written job readable
            pass

    class FakeProc:
        def __init__(self, cmd, **kw):
            calls.append(cmd)
            self.stdin = KeptStringIO()
            self.stderr = io.StringIO("")

            self.stdout = self._results()

        def _results(self):  # lazy: runs once the job has been written to stdin
            spec = json.loads(self.stdin.getvalue())
            assert spec["password"] == "secret"
            for j in spec["jobs"]:
                yield json.dumps({"source": j["source"], "ok": True,
                                  "filename": Path(j["source"]).name.replace("tis-", "tsi-")}) + "\n"

        def wait(self):
            return 0

    monkeypatch.setattr(importer.subprocess, "Popen", FakeProc)
    items = []
    for name in ("tis-a_1_windows.wapt", "tis-b_1_windows.wapt", "tis-c_1_windows.wapt"):
        path = tmp_path / name
        path.write_bytes(b"")
        items.append(PlannedImport(entry=pkg(name.split("_")[0]), families=["windows"], reason="requested",
                                   target_name="", download_path=path))
    sign_packages(items, wapt_python="/opt/wapt/waptpython", certificate="c.crt", private_key="c.pem",
                  password="secret", trusted_certs=[], prefix="tsi", output_dir=tmp_path / "out")
    assert len(calls) == 1
    assert [i.result["filename"] for i in items] == ["tsi-a_1_windows.wapt", "tsi-b_1_windows.wapt",
                                                     "tsi-c_1_windows.wapt"]


def test_default_work_dir(tmp_path, monkeypatch):
    from wapt_analyzer.importer import default_work_dir

    assert default_work_dir("/opt/wapt/waptpython", tmp_path) == tmp_path / "import"
    # Windows waptpython from WSL: work on the Windows filesystem, never on \\wsl.localhost
    monkeypatch.setattr(importer.os, "name", "posix")
    windows = Path("/mnt/c/Users/me/AppData/Local/wapt-analyzer/import")
    monkeypatch.setattr(importer, "windows_work_dir", lambda: windows)
    assert default_work_dir("/mnt/c/Program Files (x86)/wapt/waptpython.exe", tmp_path) == windows
    monkeypatch.setattr(importer, "windows_work_dir", lambda: None)
    assert default_work_dir("/mnt/c/Program Files (x86)/wapt/waptpython.exe", tmp_path) == tmp_path / "import"
