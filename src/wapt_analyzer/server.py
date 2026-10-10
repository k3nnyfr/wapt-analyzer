"""Minimal client for the WAPT server REST API (read-only calls)."""

from __future__ import annotations

import logging
import ssl
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter

from .fetch import USER_AGENT, Cache
from .packages import host_os_family

log = logging.getLogger(__name__)

HOST_COLUMNS = ["uuid", "computer_fqdn", "computer_name", "os_name", "os_version", "last_seen_on",
                "reachable", "connected_users"]


class WaptServerError(RuntimeError):
    pass


@dataclass
class Host:
    uuid: str
    name: str
    os_name: str = ""
    last_seen_on: str = ""
    installed_packages: list[dict] = field(default_factory=list)
    installed_softwares: list[dict] = field(default_factory=list)

    @property
    def os_family(self) -> str:
        return host_os_family(self.os_name)

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, data: dict) -> Host:
        return cls(**data)


def key_is_encrypted(path: str) -> bool:
    """PEM private key protected by a passphrase (PKCS#8 or legacy OpenSSL format)."""
    text = Path(path).expanduser().read_text(encoding="ascii", errors="replace")
    return "-----BEGIN ENCRYPTED PRIVATE KEY-----" in text or "Proc-Type: 4,ENCRYPTED" in text


class _ClientCertAdapter(HTTPAdapter):
    """Present a client certificate whose key stays in memory once unlocked (never written decrypted)."""

    def __init__(self, context: ssl.SSLContext):
        self._context = context
        super().__init__()

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self._context
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        kwargs["ssl_context"] = self._context
        return super().proxy_manager_for(*args, **kwargs)


def make_session(verify=True, client_certificate: str = "", client_private_key: str = "",
                 key_password: Callable[[], str] | None = None) -> requests.Session:
    """HTTP session for the WAPT server: TLS verification and optional client certificate.

    ``key_password`` is only called when the client key is encrypted."""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    session.verify = verify
    if client_certificate:
        cert = str(Path(client_certificate).expanduser())
        key = str(Path(client_private_key).expanduser()) if client_private_key else None
        password = key_password() if key_password and key_is_encrypted(key or cert) else None
        context = ssl.create_default_context(cafile=verify if isinstance(verify, str) else None)
        if verify is False:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        try:
            context.load_cert_chain(cert, key, password=password)
        except ssl.SSLError as e:
            raise WaptServerError(f"Cannot load the client certificate {cert}: {e.reason or e}") from e
        session.mount("https://", _ClientCertAdapter(context))
        log.info("Using client certificate %s", cert)
    return session


class WaptServer:
    def __init__(self, url: str, user: str, password: str, verify=True, timeout: int = 60,
                 session: requests.Session | None = None, totp: Callable[[], str] | None = None):
        self.url = url.rstrip("/")
        self.user = user
        self.password = password
        self.verify = verify
        self.timeout = timeout
        self.totp = totp
        self.session = session or make_session(verify)

    def _call(self, method: str, path: str, **kwargs):
        resp = self.session.request(method, f"{self.url}/{path}", timeout=self.timeout, **kwargs)
        try:
            payload = resp.json()
        except ValueError as e:
            raise WaptServerError(f"{path}: HTTP {resp.status_code}, non-JSON answer") from e
        if resp.status_code != 200 or not payload.get("success", False):
            raise WaptServerError(f"{path}: HTTP {resp.status_code}: {payload.get('msg') or payload}")
        return payload.get("result")

    def _post_login(self, password: str) -> requests.Response:
        return self.session.post(f"{self.url}/api/v3/login", json={"user": self.user, "password": password},
                                 timeout=self.timeout)

    def login(self) -> None:
        resp = self._post_login(self.password)
        if resp.status_code == 401 and "Missing TOTP" in resp.text:
            # Same convention as the WAPT console and wapt-get: the code is appended to the password
            if self.totp is None:
                raise WaptServerError("This account requires a TOTP code (MFA)")
            resp = self._post_login(f"{self.password}{{{self.totp()}}}")
            hint = ": wrong or expired TOTP code?"
        else:
            hint = ""
        try:
            ok = resp.status_code == 200 and resp.json().get("success", False)
        except ValueError:
            ok = False
        if not ok:
            raise WaptServerError(f"Login failed for {self.user!r} (HTTP {resp.status_code}){hint}")
        log.info("Logged in to %s as %s", self.url, self.user)

    def logout(self) -> None:
        try:
            self.session.post(f"{self.url}/api/v3/logout", timeout=self.timeout)
        except requests.RequestException:
            pass

    def hosts(self) -> list[dict]:
        return self._call("GET", "api/v3/hosts", params={"columns": ",".join(HOST_COLUMNS), "limit": 100000})

    def host_data(self, uuid: str, field_name: str) -> list[dict]:
        return self._call("GET", "api/v3/host_data", params={"uuid": uuid, "field": field_name}) or []

    def collect_hosts(self, workers: int = 8) -> list[Host]:
        rows = self.hosts()
        log.info("%d hosts registered on the server", len(rows))

        def load(row: dict) -> Host:
            name = "".join((row.get("computer_fqdn") or row.get("computer_name") or row["uuid"]).split())
            host = Host(uuid=row["uuid"], name=name, os_name=(row.get("os_name") or "").strip(),
                        last_seen_on=row.get("last_seen_on") or "")
            host.installed_packages = self.host_data(host.uuid, "installed_packages")
            host.installed_softwares = self.host_data(host.uuid, "installed_softwares")
            return host

        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(load, rows))


def load_inventory(server: WaptServer | None, cache: Cache, workers: int = 8) -> list[Host]:
    """Fetch the host inventory from the server, or reuse the last snapshot in offline mode."""
    key = "inventory"
    if cache.offline or server is None:
        data = cache.read_json(key)
        if data is None:
            raise WaptServerError("Offline mode: no cached inventory, run once online first.")
        log.info("Using cached inventory (%d hosts)", len(data))
        return [Host.from_dict(d) for d in data]
    server.login()
    try:
        hosts = server.collect_hosts(workers=workers)
    finally:
        server.logout()
    cache.write_json(key, [h.to_dict() for h in hosts])
    return hosts
