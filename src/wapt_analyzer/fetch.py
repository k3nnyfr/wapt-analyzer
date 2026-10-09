"""HTTP downloads with a small on-disk cache (conditional GET on Last-Modified / ETag)."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import requests

from . import __version__

log = logging.getLogger(__name__)

USER_AGENT = f"wapt-analyzer/{__version__}"


class Cache:
    def __init__(self, directory: Path, offline: bool = False):
        self.directory = directory
        self.offline = offline
        directory.mkdir(parents=True, exist_ok=True)

    def path(self, key: str, suffix: str = "") -> Path:
        digest = hashlib.sha256(key.encode()).hexdigest()[:16]
        return self.directory / f"{digest}{suffix}"

    def read_json(self, key: str):
        p = self.path(key, ".json")
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return None

    def write_json(self, key: str, data) -> None:
        p = self.path(key, ".json")
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        p.chmod(0o600)


def fetch_cached(url: str, cache: Cache, session: requests.Session | None = None, verify=True,
                 timeout: int = 120) -> bytes:
    """Download ``url`` and keep a copy; reuse it when the server answers 304 or when offline."""
    data_path = cache.path(url, ".bin")
    meta_path = cache.path(url, ".meta.json")
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}

    if cache.offline:
        if not data_path.exists():
            raise RuntimeError(f"Offline mode: no cached copy of {url}")
        log.info("Using cached %s", url)
        return data_path.read_bytes()

    headers = {"User-Agent": USER_AGENT}
    if data_path.exists():
        if meta.get("etag"):
            headers["If-None-Match"] = meta["etag"]
        if meta.get("last_modified"):
            headers["If-Modified-Since"] = meta["last_modified"]

    http = session or requests
    log.info("Downloading %s", url)
    resp = http.get(url, headers=headers, timeout=timeout, verify=verify)
    if resp.status_code == 304 and data_path.exists():
        log.info("Not modified, using cached copy")
        return data_path.read_bytes()
    resp.raise_for_status()
    data_path.write_bytes(resp.content)
    meta_path.write_text(json.dumps({
        "url": url,
        "etag": resp.headers.get("ETag"),
        "last_modified": resp.headers.get("Last-Modified"),
    }))
    return resp.content
