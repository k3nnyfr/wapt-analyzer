from datetime import date
from pathlib import Path

import pytest

from wapt_analyzer.health import add_to_report, agent_outdated, certificate_expiry, os_support
from wapt_analyzer.notify import report_items
from wapt_analyzer.server import Host

TODAY = date(2026, 10, 11)
CERT = Path(__file__).parent / "pin-test.crt"


def host(os_name, os_version, wapt="2.7.0.19598", name="pc"):
    return Host(uuid=f"u-{name}", name=name, os_name=os_name, os_version=os_version, wapt_version=wapt)


@pytest.mark.parametrize("os_name, version, release, end, status", [
    ("Windows 7 Professional", "6.1.7601", "Windows 7", "2020-01-14", "ended"),
    ("Windows 10 Pro", "10.0.19045", "Windows 10", "2025-10-14", "ended"),
    ("Windows 11 Pro", "10.0.22631", "Windows 11 23H2", "2025-11-11", "ended"),
    ("Windows 11 Enterprise", "10.0.22631", "Windows 11 23H2", "2026-11-10", "soon"),   # +1 year for Enterprise
    ("Windows 11 Home", "10.0.26100", "Windows 11 24H2", "2026-10-13", "soon"),
    ("Windows 11 Pro", "10.0.26200", "Windows 11 25H2", "2027-10-12", "ok"),
    ("Windows Server 2019 Standard", "10.0.17763", "Windows Server 2019", "2029-01-09", "ok"),
    ("Windows 11 Pro", "10.0.99999", "Windows 11 Pro", "", "unknown"),                  # future build
])
def test_windows_support(os_name, version, release, end, status):
    s = os_support(host(os_name, version), TODAY)
    assert (s.release, s.end, s.status) == (release, end, status)


def test_macos_support():
    assert os_support(host("macOS 26.7.1", "26.7.1"), TODAY).status == "ok"
    assert os_support(host("macOS 14.7", "14.7"), TODAY).status == "ended"
    assert os_support(host("macOS 14.7", "14.7"), TODAY, macos_min="14").status == "ok"


def test_agent_and_certificate():
    assert agent_outdated(host("Windows 11 Pro", "", wapt="2.6.1"), "2.7.0.19598")
    assert not agent_outdated(host("Windows 11 Pro", "", wapt="2.7.0.19598"), "2.7.0.19598")
    assert not agent_outdated(host("Windows 11 Pro", "", wapt=""), "2.7.0.19598")       # unknown
    cert = certificate_expiry(str(CERT), TODAY)
    assert cert and cert["status"] in ("ok", "soon", "ended") and cert["not_after"]
    assert certificate_expiry("/nonexistent.crt", TODAY) is None


def test_report_and_notification():
    hosts = [host("Windows 7 Professional", "6.1.7601", wapt="2.6.1", name="old"),
             host("Windows 11 Pro", "10.0.26200", name="new")]
    data = {"summary": {}}
    add_to_report(data, hosts, today=TODAY)                  # reference: newest agent seen
    assert [h["host"] for h in data["health"]["hosts"]] == ["old", "new"]
    assert data["summary"] == {"health_os_ended": 1, "health_os_soon": 0, "health_agents_outdated": 1,
                               "health_issues": 1}
    data.update(outdated=[], missing_packages=[], software_to_import=[])
    assert sorted(report_items(data)["health"].values()) == [
        "old : Windows 7, support terminé le 2020-01-14", "old : agent WAPT 2.6.1 (serveur : 2.7.0.19598)"]
