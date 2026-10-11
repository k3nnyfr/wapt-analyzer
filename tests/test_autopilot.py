import copy
from types import SimpleNamespace

import pytest

from wapt_analyzer import cli
from wapt_analyzer.config import DEFAULTS


@pytest.fixture
def cfg(tmp_path):
    cfg = copy.deepcopy(DEFAULTS)
    cfg["repo"]["prefix"] = "tsi"
    cfg["cache"]["directory"] = str(tmp_path)
    cfg["notify"]["webhook"] = [{"url": "https://hooks.example.org/x"}]
    return cfg


@pytest.fixture
def calls(monkeypatch):
    """Replace the report, the update planning and the actions; record what the autopilot runs."""
    calls = {"import": [], "upgrade": [], "notify": [], "updates": ["firefox", "7zip"]}

    def plan_imports(requested, *a, **kw):
        return [SimpleNamespace(skip="", entry=SimpleNamespace(base=b)) for b in calls["updates"]]

    monkeypatch.setattr(cli, "build_report", lambda cfg, args: ({"summary": {}}, "<html>", None))
    monkeypatch.setattr(cli, "load_indexes", lambda cfg, cache: SimpleNamespace(store={}, repo={}))
    monkeypatch.setattr(cli, "_update_requests", lambda *a, **kw: [])
    monkeypatch.setattr(cli, "plan_imports", plan_imports)
    monkeypatch.setattr(cli, "cmd_import", lambda cfg, args: calls["import"].append(args) or 0)
    monkeypatch.setattr(cli, "cmd_upgrade", lambda cfg, args: calls["upgrade"].append(args) or 0)
    monkeypatch.setattr(cli, "notify", lambda cfg, data, cache, html, autopilot, force:
                        calls["notify"].append((autopilot, force)) or 0)
    return calls


def run(cfg, *argv):
    args = cli.build_parser().parse_args(["autopilot", *argv])
    return cli.cmd_autopilot(cfg, args)


def test_apply_imports_cleans_upgrades_and_notifies(cfg, calls):
    assert run(cfg, "--apply") == 0
    [args] = calls["import"]
    assert (args.update, args.packages, args.apply, args.yes, args.cleanup, args.upgrade_hosts) == (
        True, ["7zip", "firefox"], True, True, True, True)
    [(summary, force)] = calls["notify"]
    assert force and summary[0].startswith("Mises à jour importées : 7zip, firefox")


def test_dry_run_changes_nothing(cfg, calls):
    assert run(cfg) == 0
    assert calls["import"] == [] and calls["notify"] == []


def test_too_many_updates_imports_nothing(cfg, calls):
    cfg["autopilot"]["max_updates"] = 1
    assert run(cfg, "--apply") == 1
    assert calls["import"] == []
    [(summary, force)] = calls["notify"]
    assert force and "plus que la limite de 1" in summary[0]


def test_upgrade_pending_hosts(cfg, calls):
    cfg["autopilot"].update(upgrade="pending", cleanup=False)
    calls["updates"] = []
    assert run(cfg, "--apply", "--no-notify") == 0
    assert calls["import"] == [] and calls["notify"] == []
    [args] = calls["upgrade"]
    assert args.apply and args.yes and not args.packages


def test_runs_never_overlap(cfg, calls, tmp_path):
    with cli._single_run(tmp_path / "autopilot.lock") as alone:
        assert alone
        assert run(cfg, "--apply") == 1          # the cron run of the next hour finds it locked
    assert calls["import"] == []
