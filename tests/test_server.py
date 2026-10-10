import copy
import http.server
import json
import shutil
import ssl
import subprocess
import threading

import pytest
import requests

from wapt_analyzer.config import DEFAULTS, resolve_totp
from wapt_analyzer.server import WaptServer, WaptServerError, key_is_encrypted, make_session


class FakeResponse:
    def __init__(self, status: int, payload: dict | None = None, text: str = ""):
        self.status_code = status
        self._payload = payload
        self.text = text or json.dumps(payload or {})

    def json(self):
        if self._payload is None:
            raise ValueError
        return self._payload


class FakeSession:
    """Login endpoint asking for a TOTP code when ``totp`` is set."""

    def __init__(self, totp: str = ""):
        self.expected_totp = totp
        self.passwords = []

    def post(self, url, json=None, timeout=None):
        password = json["password"]
        self.passwords.append(password)
        if self.expected_totp and not password.endswith("}"):
            return FakeResponse(401, text='{"success": false, "msg": "Missing TOTP code"}')
        if password in ("s3cret", f"s3cret{{{self.expected_totp}}}"):
            return FakeResponse(200, {"success": True})
        return FakeResponse(401, {"success": False})


def test_login_without_totp():
    session = FakeSession()
    asked = []
    WaptServer("https://wapt", "admin", "s3cret", session=session, totp=lambda: asked.append(1) or "000000").login()
    assert session.passwords == ["s3cret"] and not asked     # code only asked when the server wants one


def test_login_with_totp():
    session = FakeSession(totp="123456")
    WaptServer("https://wapt", "admin", "s3cret", session=session, totp=lambda: "123456").login()
    assert session.passwords == ["s3cret", "s3cret{123456}"]

    with pytest.raises(WaptServerError, match="wrong or expired TOTP"):
        WaptServer("https://wapt", "admin", "s3cret", session=FakeSession("123456"), totp=lambda: "654321").login()
    with pytest.raises(WaptServerError, match="requires a TOTP"):
        WaptServer("https://wapt", "admin", "s3cret", session=FakeSession("123456")).login()


def test_resolve_totp(monkeypatch):
    cfg = copy.deepcopy(DEFAULTS)
    monkeypatch.delenv("WAPT_TOTP", raising=False)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(RuntimeError, match="--totp"):
        resolve_totp(cfg)
    monkeypatch.setenv("WAPT_TOTP", "112233")
    assert resolve_totp(cfg) == "112233"
    cfg["server"]["totp"] = " 445566 "                      # command line wins
    assert resolve_totp(cfg) == "445566"
    cfg["server"]["totp"] = "12345"
    with pytest.raises(ValueError, match="6 digits"):
        resolve_totp(cfg)


# --- TLS client certificate, against a local HTTPS server that requires one ---

def _openssl(*args, cwd):
    subprocess.run(["openssl", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    if not shutil.which("openssl"):
        pytest.skip("openssl not available")
    d = tmp_path_factory.mktemp("pki")
    _openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.crt",
             "-days", "2", "-subj", "/CN=test-ca", "-addext", "basicConstraints=critical,CA:TRUE",
             "-addext", "keyUsage=critical,keyCertSign,cRLSign", cwd=d)   # strict X.509 checks (Python 3.13+)
    (d / "server.ext").write_text("subjectAltName=DNS:localhost,IP:127.0.0.1\nauthorityKeyIdentifier=keyid\n"
                                  "extendedKeyUsage=serverAuth\n")
    (d / "client.ext").write_text("authorityKeyIdentifier=keyid\nextendedKeyUsage=clientAuth\n")
    for name in ("server", "client"):
        _openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", f"{name}.pem", "-out", f"{name}.csr",
                 "-subj", f"/CN={name}", cwd=d)
        _openssl("x509", "-req", "-in", f"{name}.csr", "-CA", "ca.crt", "-CAkey", "ca.key", "-CAcreateserial",
                 "-out", f"{name}.crt", "-days", "2", "-extfile", f"{name}.ext", cwd=d)
    _openssl("pkcs8", "-topk8", "-in", "client.pem", "-out", "client-enc.pem", "-passout", "pass:hunter2", cwd=d)
    return d


@pytest.fixture(scope="module")
def mtls_url(pki):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = json.dumps({"success": True, "client": self.connection.getpeercert()["subject"][0][0][1]})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args):
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(pki / "server.crt", pki / "server.pem")
    context.load_verify_locations(pki / "ca.crt")
    context.verify_mode = ssl.CERT_REQUIRED
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"https://127.0.0.1:{httpd.server_port}/"
    httpd.shutdown()


@pytest.mark.filterwarnings("ignore::urllib3.exceptions.InsecureRequestWarning")
def test_client_certificate(pki, mtls_url):
    ca = str(pki / "ca.crt")
    asked = []
    session = make_session(ca, str(pki / "client.crt"), str(pki / "client.pem"), key_password=lambda: asked.append(1))
    assert session.get(mtls_url, timeout=10).json()["client"] == "client"
    assert not asked                                         # key not encrypted: no passphrase asked

    session = make_session(ca, str(pki / "client.crt"), str(pki / "client-enc.pem"), key_password=lambda: "hunter2")
    assert session.get(mtls_url, timeout=10).json()["success"]

    session = make_session(False, str(pki / "client.crt"), str(pki / "client.pem"))   # --insecure
    assert session.get(mtls_url, timeout=10).json()["success"]


def test_client_certificate_errors(pki, mtls_url):
    assert key_is_encrypted(str(pki / "client-enc.pem")) and not key_is_encrypted(str(pki / "client.pem"))
    with pytest.raises(WaptServerError, match="client certificate"):
        make_session(True, str(pki / "client.crt"), str(pki / "client-enc.pem"), key_password=lambda: "wrong")
    with pytest.raises(requests.exceptions.SSLError):
        make_session(str(pki / "ca.crt")).get(mtls_url, timeout=10)        # no client certificate: refused
    with pytest.raises(requests.exceptions.SSLError, match="CERTIFICATE_VERIFY_FAILED"):
        # the client certificate does not weaken the server check: unknown CA refused
        make_session(True, str(pki / "client.crt"), str(pki / "client.pem")).get(mtls_url, timeout=10)
