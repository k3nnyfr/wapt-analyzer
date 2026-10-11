import copy

import pytest

from wapt_analyzer import actions
from wapt_analyzer.actions import Target, build_actions, host_rows_to_targets, wake_and_wait
from wapt_analyzer.cli import _package_names, build_parser, run_host_actions
from wapt_analyzer.config import DEFAULTS

ROWS = [{"uuid": "u1", "computer_fqdn": "pc1.lan", "reachable": "OK"},
        {"uuid": "u2", "computer_name": "PC2", "reachable": "DISCONNECTED"},
        {"uuid": "u3", "computer_fqdn": "pc3.lan", "reachable": "OK"}]


class FakeServer:
    def __init__(self, connected_after: int = 1):
        self.polls, self.connected_after = 0, connected_after
        self.woken, self.sent = [], []

    def wake_on_lan(self, uuids):
        self.woken += uuids

    def hosts(self):
        self.polls += 1
        return [dict(r, reachable="OK") if self.polls >= self.connected_after else r for r in ROWS]

    def trigger_host_action(self, signed):
        self.sent += signed


@pytest.fixture
def cfg():
    cfg = copy.deepcopy(DEFAULTS)
    cfg["repo"]["prefix"] = "tsi"
    cfg["signing"].update(certificate="/k/signer.crt", private_key="/k/signer.pem")
    return cfg


def test_targets_and_actions():
    targets = host_rows_to_targets(ROWS, {"u2": "3 pending", "u1": ""})
    assert [(t.name, t.reachable, t.reason) for t in targets] == [("pc1.lan", True, ""), ("PC2", False, "3 pending")]
    assert build_actions(targets[:1], "update") == [{"action": "trigger_host_update", "uuid": "u1",
                                                     "notify_server": True, "notify_user": False, "force": False}]


def test_package_names(cfg):
    assert _package_names(cfg, ["firefox", "tsi-7zip", "tis-vlc", "grp-base", "vc-redist"]) == [
        "tsi-firefox", "tsi-7zip", "tis-vlc", "grp-base", "tsi-vc-redist"]


def test_wake_and_wait(monkeypatch):
    monkeypatch.setattr(actions.time, "sleep", lambda s: None)
    server = FakeServer(connected_after=2)
    targets = host_rows_to_targets(ROWS, {"u1": "", "u2": ""})
    wake_and_wait(server, targets, timeout=60)
    assert server.woken == ["u2"] and server.polls == 2 and all(t.reachable for t in targets)


@pytest.mark.parametrize("apply", [False, True])
def test_run_host_actions_sends_to_connected_hosts_only(cfg, monkeypatch, capsys, apply):
    monkeypatch.setattr("wapt_analyzer.cli.find_wapt_python", lambda configured: "waptpython")
    monkeypatch.setattr("wapt_analyzer.cli.sign_actions", lambda acts, **kw: [dict(a, signature="sig") for a in acts])
    server = FakeServer()
    args = build_parser().parse_args(["upgrade", "-y", *(["--apply"] if apply else [])])
    targets = [Target("u1", "pc1", True), Target("u2", "pc2", False)]
    assert run_host_actions(cfg, args, server, targets, "upgrade", key_password="") == 0
    out = capsys.readouterr().out
    assert "pc2 (disconnected, skipped)" in out
    assert [a["uuid"] for a in server.sent] == (["u1"] if apply else [])
