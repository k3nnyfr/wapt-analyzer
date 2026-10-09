"""Minimal client for the WAPT server REST API (read-only calls)."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests

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


class WaptServer:
    def __init__(self, url: str, user: str, password: str, verify=True, timeout: int = 60):
        self.url = url.rstrip("/")
        self.user = user
        self.password = password
        self.verify = verify
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.session.verify = verify

    def _call(self, method: str, path: str, **kwargs):
        resp = self.session.request(method, f"{self.url}/{path}", timeout=self.timeout, **kwargs)
        try:
            payload = resp.json()
        except ValueError as e:
            raise WaptServerError(f"{path}: HTTP {resp.status_code}, non-JSON answer") from e
        if resp.status_code != 200 or not payload.get("success", False):
            raise WaptServerError(f"{path}: HTTP {resp.status_code}: {payload.get('msg') or payload}")
        return payload.get("result")

    def login(self) -> None:
        resp = self.session.post(f"{self.url}/api/v3/login", json={"user": self.user, "password": self.password},
                                 timeout=self.timeout)
        if resp.status_code == 401 and "Missing TOTP" in resp.text:
            raise WaptServerError("This account requires TOTP (MFA), which is not supported yet.")
        try:
            ok = resp.status_code == 200 and resp.json().get("success", False)
        except ValueError:
            ok = False
        if not ok:
            raise WaptServerError(f"Login failed for {self.user!r} (HTTP {resp.status_code})")
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
