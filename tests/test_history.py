from datetime import datetime, timedelta, timezone

from wapt_analyzer.deploy import add_to_report, track_deployments
from wapt_analyzer.history import DeployHistory
from wapt_analyzer.notify import report_items
from wapt_analyzer.server import Host

DAY1 = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)


def host(name, *packages, seen=None):
    return Host(uuid=f"uuid-{name}", name=name, os_name="Windows 11 Pro",
                last_seen_on=(seen or DAY1).isoformat(), installed_packages=list(packages))


def pending(package, version="2"):
    return {"package": package, "version": version, "install_status": "NEED-INSTALL"}


def failed(package, date=""):
    return {"package": package, "version": "1", "install_status": "ERROR", "install_date": date}


def record(db, at, *hosts):
    return db.record(track_deployments(list(hosts), now=at), at)


def test_issues_open_resolve_and_reopen(tmp_path):
    with DeployHistory(tmp_path / "h.sqlite") as db:
        assert db.runs() == 0
        record(db, DAY1, host("a", pending("tsi-vlc")), host("b", pending("tsi-vlc")))
        day3 = DAY1 + timedelta(days=2)
        when = record(db, day3, host("a", pending("tsi-vlc", "3")), host("b"))   # fixed on b
        assert db.open_since() == {("uuid-a", "tsi-vlc", "install"): DAY1.isoformat()}
        assert [(r["host"], r["package"]) for r in db.resolved_on(when)] == [("b", "tsi-vlc")]
        record(db, day3 + timedelta(days=1), host("a", pending("tsi-vlc")))     # b absent: kept as is
        day5 = DAY1 + timedelta(days=4)
        record(db, day5, host("b", pending("tsi-vlc")))                          # back on b: new issue
        assert db.open_since()[("uuid-b", "tsi-vlc", "install")] == day5.isoformat()
        assert db.open_since()[("uuid-a", "tsi-vlc", "install")] == DAY1.isoformat()
        assert db.runs() == 4


def test_report_ages_new_issues_and_lasting(tmp_path):
    with DeployHistory(tmp_path / "h.sqlite") as db:
        record(db, DAY1, host("a", pending("tsi-vlc")))
        now = DAY1 + timedelta(days=8)
        hosts = [host("a", pending("tsi-vlc"), seen=now),
                 host("b", failed("tsi-chrome", "2026-09-20T10:00:00"), seen=now)]
        states = track_deployments(hosts, now=now)
        run_at = db.record(states, now)
        data = {"summary": {}, "outdated": [], "missing_packages": [], "software_to_import": []}
        add_to_report(data, states, 7, since=db.open_since(), alert_days=7, run_at=run_at, now=now)
    issues = {i["package"]: i for h in data["deployments"]["hosts"] for i in h["errors"] + h["pending"]}
    assert (issues["tsi-vlc"]["days"], issues["tsi-vlc"]["new"]) == (8, False)
    # first seen now, but failed on 2026-09-20 according to the agent
    assert (issues["tsi-chrome"]["days"], issues["tsi-chrome"]["new"]) == (18, True)
    assert data["summary"]["deploy_lasting"] == 2
    assert sorted(report_items(data)["deploy_lasting"].values()) == [
        "a : tsi-vlc 2 (installation en attente depuis 8 j)", "b : tsi-chrome 1 (installation en erreur depuis 18 j)"]


def test_report_without_history_has_no_age():
    states = track_deployments([host("a", pending("tsi-vlc"))], now=DAY1)
    data = {"summary": {}}
    add_to_report(data, states, 7, alert_days=7, now=DAY1)
    assert "days" not in data["deployments"]["hosts"][0]["pending"][0]
    assert "deploy_lasting" not in data["summary"] and not data["deployments"]["history"]
