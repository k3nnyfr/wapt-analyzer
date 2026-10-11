"""Remote actions on the agents: update their package index, apply pending upgrades, wake them up.

The server relays an action to an agent through its websocket only when the agent is connected
(``reachable = OK``), and only if the action is signed: the agent checks the signature against the certificates
it trusts, as for packages. Actions are signed by the WAPT helper (``sign_claim``), like the WAPT console does.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .importer import ImportFailed, path_converter, run_wapt_helper
from .server import WaptServer

log = logging.getLogger(__name__)

# action name -> agent action: "upgrade" also updates the index and downloads first
ACTIONS = {"upgrade": "trigger_host_upgrade", "update": "trigger_host_update"}


@dataclass
class Target:
    uuid: str
    name: str
    reachable: bool
    reason: str = ""


def host_rows_to_targets(rows: list[dict], reasons: dict[str, str]) -> list[Target]:
    """Targets among the ``api/v3/hosts`` rows, for the uuids of ``reasons``, sorted by name."""
    targets = []
    for row in rows:
        if row["uuid"] in reasons:
            name = "".join((row.get("computer_fqdn") or row.get("computer_name") or row["uuid"]).split())
            targets.append(Target(row["uuid"], name, row.get("reachable") == "OK", reasons[row["uuid"]]))
    return sorted(targets, key=lambda t: t.name.lower())


def build_actions(targets: list[Target], action: str = "upgrade") -> list[dict]:
    return [{"action": ACTIONS[action], "uuid": t.uuid, "notify_server": True, "notify_user": False, "force": False}
            for t in targets]


def sign_actions(actions: list[dict], *, wapt_python: str, certificate: str, private_key: str,
                 password: str) -> list[dict]:
    conv = path_converter(wapt_python)
    spec = {"certificate": conv(Path(certificate).expanduser()), "private_key": conv(Path(private_key).expanduser()),
            "password": password, "actions": actions}
    signed = []
    for res in run_wapt_helper(wapt_python, spec):
        if not res.get("ok"):
            raise ImportFailed(f"Cannot sign the action for {res.get('uuid')}: {res.get('error')}")
        signed.append(res["action"])
    return signed


def wake_and_wait(server: WaptServer, targets: list[Target], timeout: int, interval: int = 10,
                  on_wait: Callable[[int, int], None] | None = None) -> None:
    """Wake the disconnected targets up, then wait until they connect (or ``timeout`` seconds).

    ``on_wait(connected, expected)`` reports progress; ``reachable`` is updated in place."""
    asleep = [t for t in targets if not t.reachable]
    if not asleep:
        return
    server.wake_on_lan([t.uuid for t in asleep])
    log.info("Wake-on-LAN sent to %d host(s)", len(asleep))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(interval)
        reachable = {r["uuid"] for r in server.hosts() if r.get("reachable") == "OK"}
        for t in asleep:
            t.reachable = t.uuid in reachable
        woken = sum(t.reachable for t in asleep)
        if on_wait:
            on_wait(woken, len(asleep))
        if woken == len(asleep):
            return
