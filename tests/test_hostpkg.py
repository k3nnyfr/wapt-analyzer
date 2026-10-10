from wapt_analyzer.analysis import SoftwareGroup
from wapt_analyzer.hostpkg import control_for, next_version, plan_host, plan_hosts, plans_to_dict
from wapt_analyzer.packages import PackageEntry, Version
from wapt_analyzer.server import Host


def pkg(package, version="1.0-1", target_os="windows", section="base", depends=""):
    return PackageEntry(package=package, version=Version(version), fields={
        "package": package, "version": version, "target_os": target_os, "section": section, "depends": depends})


REPO = [
    pkg("tsi-firefox"), pkg("tsi-firefox", target_os="darwin"), pkg("tsi-7zip"), pkg("tsi-keepassxc"),
    pkg("tsi-teams", depends="tsi-webview2"), pkg("tsi-webview2"), pkg("tsi-vlc"), pkg("tsi-waptupgrade"),
    pkg("abc-other"),                                       # another prefix: never proposed
    pkg("grp-base", section="group", depends="tsi-7zip"),
]


def installed(*names, section="base", depends=None):
    return [{"package": n, "version": "1", "section": section, "depends": depends or []} for n in names]


def host(packages, name="pc1", uuid="U1", os_name="Windows 11 Pro", depends=None):
    return Host(uuid=uuid, name=name, os_name=os_name, installed_packages=packages, depends=depends)


def test_rebuild_from_installed():
    h = host(installed("tsi-firefox", "tis-keepassxc", "tsi-teams", "tsi-webview2", "tsi-7zip", "tsi-meshagent")
             + installed("grp-base", section="group")
             + installed("U1", section="host", depends=["tsi-firefox"]), depends=["tsi-firefox"])
    plan = plan_host(h, REPO, "tsi")
    assert plan.current == ["tsi-firefox"] and plan.version == "1"
    assert [(a.package, a.reason) for a in plan.additions] == [
        ("tsi-keepassxc", "installé en tant que tis-keepassxc"),  # normalized to your prefix
        ("tsi-teams", "installé"),                              # webview2: dependency of teams, not added
    ]                                                           # 7zip: provided by grp-base
    assert plan.not_in_repo == ["tsi-meshagent"]
    assert plan.depends == ["tsi-firefox", "tsi-keepassxc", "tsi-teams"]


def test_group_absent_from_repo_uses_installed_depends():
    h = host(installed("tsi-vlc", "tsi-firefox") + installed("grp-old", section="group", depends=["tsi-vlc"]))
    assert [a.package for a in plan_host(h, REPO, "tsi").additions] == ["tsi-firefox"]


def test_adopt_and_exclude():
    unmanaged = [SoftwareGroup(key="vlc", family="windows", names={"VLC media player"}, hosts={"pc1"},
                               match=pkg("tsi-vlc")),
                 SoftwareGroup(key="firefox", family="macos", names={"Firefox"}, hosts={"pc1"},
                               match=pkg("tsi-firefox", target_os="darwin"))]
    h = host(installed("tsi-waptupgrade"))
    plan = plan_host(h, REPO, "tsi", unmanaged=unmanaged)
    assert [(a.package, a.kind) for a in plan.additions] == [("tsi-waptupgrade", "installed"), ("tsi-vlc", "adopt")]
    assert plan.additions[1].reason == "hors WAPT : VLC media player"   # macOS group ignored on Windows
    assert [a.package for a in plan_host(h, REPO, "tsi", unmanaged=unmanaged, exclude=["waptupgrade"]).additions] \
        == ["tsi-vlc"]


def test_missing_on_server_and_merge():
    h = host(installed("tsi-vlc") + installed("U1", section="host", depends=["tsi-firefox", "tsi-vlc"]))
    h.installed_packages[-1]["version"] = "7"
    # The server API lists no host package for this host: recreated with the installed depends
    plan = plan_hosts([h], REPO, "tsi", server_packages={})[0]
    assert plan.missing_on_server and plan.needs_upload and plan.current == ["tsi-firefox", "tsi-vlc"]
    assert not plan.additions
    # Server and installed depends are merged, nothing removed
    plan = plan_hosts([h], REPO, "tsi", server_packages={"U1": {"package": "U1", "version": "8",
                                                                  "depends": "tsi-7zip"}})[0]
    assert plan.current == ["tsi-7zip", "tsi-firefox", "tsi-vlc"] and not plan.missing_on_server
    assert not plan.needs_upload
    # Without the server list: missing when the server has no depends but the installed package has some
    assert plan_hosts([h], REPO, "tsi")[0].missing_on_server
    assert plans_to_dict(plan_hosts([h], REPO, "tsi"))[0]["missing_on_server"]


def test_control_for():
    h = host(installed("tsi-vlc") + installed("U1", section="host", depends=["tsi-firefox"]), name="pc1.lan")
    h.installed_packages[-1].update(version="7", maturity="PROD", conflicts=["tsi-old"])
    plan = plan_host(h, REPO, "tsi")
    control = control_for(plan, None)
    assert control == {"package": "U1", "version": "7", "description": "pc1.lan", "maturity": "PROD",
                       "conflicts": "tsi-old", "depends": "tsi-firefox,tsi-vlc"}
    # the server copy wins, and the higher version is kept (incremented by the WAPT helper)
    control = control_for(plan, {"package": "U1", "version": "9", "description": "Poste compta"})
    assert control["version"] == "9" and control["description"] == "Poste compta"
    assert next_version("7") == "8" and next_version("") == "0+1"
