from wapt_analyzer.cleanup import covers, pinned_by, plan_cleanup
from wapt_analyzer.packages import PackageEntry, Version


def pkg(package, version, target_os="windows", architecture="x64", maturity="PROD", **fields):
    return PackageEntry(package=package, version=Version(version), fields={
        "package": package, "target_os": target_os, "architecture": architecture, "maturity": maturity,
        "section": "base", "package_uuid": f"{package}-{version}-{target_os}-{architecture}", **fields})


def test_covers_rules():
    old = pkg("tsi-vlc", "3.0.23-13", min_os_version="6.1")
    assert covers(pkg("tsi-vlc", "3.0.24-13", min_os_version="6.1"), old)
    assert covers(pkg("tsi-vlc", "3.0.24-13"), old)                                    # no lower bound
    assert not covers(pkg("tsi-vlc", "3.0.24-13", min_os_version="10.0"), old)         # Windows 7 hosts left
    assert covers(pkg("tsi-vlc", "3.0.24-13", architecture="all"), old)                # all covers x64
    assert not covers(pkg("tsi-vlc", "3.0.24-13"), pkg("tsi-vlc", "3.0.23-13", architecture="all"))
    assert not covers(pkg("tsi-vlc", "3.0.24-13", target_os="darwin"), old)            # other OS
    assert not covers(pkg("tsi-vlc", "3.0.24-13", maturity="DEV"), old)                # other maturity
    assert not covers(pkg("tsi-vlc", "3.0.24-13", locale="fr"), pkg("tsi-vlc", "3.0.23-13", locale="en"))
    assert covers(pkg("tsi-vlc", "3.0.24-13", locale="all"), pkg("tsi-vlc", "3.0.23-13", locale="fr"))
    assert not covers(pkg("tsi-vlc", "3.0.24-13", max_os_version="10.0"), old)        # upper bound added


def test_plan_cleanup_keeps_latest_per_line_and_os_ranges():
    entries = [
        pkg("tsi-firefox", "157.0.1-110"), pkg("tsi-firefox", "156.0.1-110"), pkg("tsi-firefox", "155.0-110"),
        pkg("tsi-firefox", "157.0.1-110", target_os="darwin", architecture="all"),
        pkg("tsi-firefox", "156.0.1-110", target_os="darwin", architecture="all"),
        # the newer vcredist needs Windows 10: the older one still serves Windows 7
        pkg("tsi-vcredist2015-2022", "14.51-31", architecture="all", min_os_version="10"),
        pkg("tsi-vcredist2015-2022", "14.44-29", architecture="all", min_os_version="6.0"),
    ]
    plan = plan_cleanup(entries)
    assert sorted((i.entry.package, str(i.entry.version), i.entry.target_os) for i in plan) == [
        ("tsi-firefox", "155.0-110", "windows"),
        ("tsi-firefox", "156.0.1-110", "darwin"),
        ("tsi-firefox", "156.0.1-110", "windows"),
    ]
    assert all(not i.skip for i in plan)
    kept = plan_cleanup(entries, keep=1)
    assert [(str(i.entry.version), i.entry.target_os) for i in kept] == [("155.0-110", "windows")]
    assert [str(i.entry.version) for i in plan_cleanup(entries, names=["vcredist2015-2022"])] == []


def test_plan_cleanup_safety_skips():
    entries = [
        pkg("tsi-java", "8.2-1"), pkg("tsi-java", "8.1-1"),
        pkg("tsi-app", "2.0-1", depends="tsi-java(=8.1-1)"),       # pins the old java
        pkg("tis-other", "2-1"), pkg("tis-other", "1-1"),           # not our prefix
        pkg("tsi-own", "2-1"), pkg("tsi-own", "1-1"),
    ]
    plan = {i.entry.package: i for i in plan_cleanup(entries, prefix="tsi", exclude=("own",))}
    assert plan["tsi-java"].skip == "pinned by tsi-app(=8.1-1)"
    assert plan["tis-other"].skip.startswith("prefix")
    assert plan["tsi-own"].skip == "excluded by configuration"
    assert pinned_by(entries[1], entries[0], entries) == ["tsi-app(=8.1-1)"]
    loose = [pkg("tsi-java", "8.2-1"), pkg("tsi-java", "8.1-1"), pkg("tsi-app", "2.0-1", depends="tsi-java(>=8.0)")]
    assert plan_cleanup(loose)[0].skip == ""                         # latest also satisfies >=8.0
