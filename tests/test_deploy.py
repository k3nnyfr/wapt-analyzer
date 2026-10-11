from datetime import datetime, timezone

from wapt_analyzer.deploy import add_to_report, by_package, track_deployments
from wapt_analyzer.notify import report_items
from wapt_analyzer.server import Host

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


def host(name, seen="2026-10-11T08:00:00+00:00", packages=()):
    return Host(uuid=f"uuid-{name}", name=name, os_name="Windows 11 Pro", last_seen_on=seen,
                installed_packages=list(packages))


def pkg(package, version, status="OK", audit=None, **extra):
    return {"package": package, "version": version, "install_status": status, "last_audit_status": audit, **extra}


def test_pending_upgrade_pairs_installed_and_target():
    h = host("pc1", packages=[pkg("tsi-7zip", "26.3-46", "NEED-UPGRADE", "OK"),
                              pkg("tsi-7zip", "26.4-46", "NEED-INSTALL"),
                              pkg("tsi-vlc", "3.0.24-13", "NEED-INSTALL"), pkg("tsi-firefox", "157-1")])
    [state] = track_deployments([h], now=NOW)
    assert not state.errors and not state.stale
    assert [(i.package, i.kind, i.installed, i.version) for i in state.pending] == [
        ("tsi-vlc", "install", "", "3.0.24-13"), ("tsi-7zip", "upgrade", "26.3-46", "26.4-46")]


def test_errors_audit_and_stale_hosts():
    hosts = [host("ok"),
             host("bad", packages=[pkg("tsi-skype", "8.92", "OK", "ERROR", last_audit_output="x" * 1000),
                                   pkg("tsi-chrome", "155", "ERROR", install_output="Traceback…")]),
             host("old", seen="2026-10-01T08:00:00+00:00"), host("never", seen="")]
    states = track_deployments(hosts, stale_days=7, now=NOW)
    assert [s.host for s in states] == ["bad", "never", "old", "ok"]
    bad = states[0]
    assert [(i.package, i.kind) for i in bad.errors] == [("tsi-skype", "audit"), ("tsi-chrome", "error")]
    assert len(bad.errors[0].output) == 401  # tail of a long output
    assert (states[1].stale, states[1].silent_days) == (True, None)
    assert (states[2].stale, states[2].silent_days) == (True, 10)
    assert not states[3].has_issue


def test_report_section_and_notification_items():
    hosts = [host("a", packages=[pkg("tsi-chrome", "155", "ERROR"), pkg("tsi-vlc", "3", "NEED-INSTALL")]),
             host("b", packages=[pkg("tsi-chrome", "155", "ERROR")]), host("c")]
    states = track_deployments(hosts, now=NOW)
    assert by_package(states)[0] == {"package": "tsi-chrome", "errors": ["a", "b"], "pending": [], "versions": []}
    data = {"summary": {}, "outdated": [], "missing_packages": [], "software_to_import": []}
    add_to_report(data, states, 7)
    assert [h["host"] for h in data["deployments"]["hosts"]] == ["a", "b"]
    assert data["summary"] == {"deploy_hosts": 2, "deploy_errors": 2, "deploy_error_hosts": 2,
                               "deploy_pending_hosts": 1, "stale_hosts": 0}
    assert sorted(report_items(data)["deploy_errors"].values()) == [
        "a : tsi-chrome 155 (installation en erreur)", "b : tsi-chrome 155 (installation en erreur)"]
