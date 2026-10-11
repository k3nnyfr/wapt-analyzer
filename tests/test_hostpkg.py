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
        ("grp-base", "groupe installé"),                        # the installed group joins the host package
        ("tsi-keepassxc", "installé en tant que tis-keepassxc"),  # normalized to your prefix
        ("tsi-teams", "installé"),                              # webview2: dependency of teams, not added
    ]                                                           # 7zip: provided by grp-base
    assert plan.not_in_repo == ["tsi-meshagent"]
    assert plan.depends == ["tsi-firefox", "grp-base", "tsi-keepassxc", "tsi-teams"]


def test_group_absent_from_repo_uses_installed_depends():
    h = host(installed("tsi-vlc", "tsi-firefox") + installed("grp-old", section="group", depends=["tsi-vlc"]))
    plan = plan_host(h, REPO, "tsi")
    assert [a.package for a in plan.additions] == ["tsi-firefox"]
    assert plan.missing_groups == ["grp-old"]     # not added until the groups command recreates it


def test_assign_groups():
    repo = REPO + [pkg("grp-office", section="group", depends="tsi-firefox,tsi-vlc,tsi-7zip,tsi-keepassxc")]
    h = host(installed("tsi-firefox", "tsi-vlc", "tsi-7zip", "tsi-keepassxc"))
    assert not [a for a in plan_host(h, repo, "tsi").additions if a.kind == "group"]
    plan = plan_host(h, repo, "tsi", assign_groups=True)
    groups = [(a.package, a.reason) for a in plan.additions if a.kind == "group"]
    assert ("grp-office", "groupe suggéré : 4/4 de ses paquets déjà installés") in groups
    assert ("grp-base", "groupe suggéré : 1/1 de ses paquets déjà installés") not in groups   # too small
    assert not [a for a in plan.additions if a.kind == "installed"]   # all provided by grp-office
    h = host(installed("tsi-firefox", "tsi-vlc"))                         # 2/4: below 80 %
    assert not [a for a in plan_host(h, repo, "tsi", assign_groups=True).additions if a.kind == "group"]


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


def test_fix_missing_imports_from_store_or_removes():
    store = {"tis-obs-studio": pkg("tis-obs-studio", "32.2-31"), "tis-teamviewer": pkg("tis-teamviewer", "15.8-26"),
             "tis-acrobat": PackageEntry(package="tis-acrobat", version=Version("1-1"), fields={
                 "package": "tis-acrobat", "licence": "Enterprise", "target_os": "windows"})}
    current = ["tsi-firefox", "tsi-obs-studio(>=30)", "tis-teamviewer", "tsi-meshagent", "tsi-acrobat", "grp-gone"]
    h = host(installed("tsi-firefox") + installed("grp-gone", section="group")
             + installed("U1", section="host", depends=current), depends=current)
    plan = plan_host(h, REPO, "tsi", store=store, restricted=("enterprise",))
    assert [(f.package, f.action, f.store, f.target) for f in plan.fixes] == [
        ("tsi-obs-studio", "import", "tis-obs-studio", "tsi-obs-studio"),
        ("tis-teamviewer", "import", "tis-teamviewer", "tsi-teamviewer"),   # imported under your prefix
        ("tsi-meshagent", "remove", "", ""),
        ("tsi-acrobat", "remove", "", ""),                                  # subscribers only
    ]                                                                       # missing group: groups command
    assert plan.fixes[3].reason.startswith("absent du dépôt, réservé aux abonnés")
    assert plan.depends == ["tsi-firefox", "tsi-obs-studio", "tsi-teamviewer", "grp-gone"]
    assert plan.needs_upload


def test_fix_missing_same_name_import_needs_no_upload():
    current = ["tsi-firefox", "tsi-obs-studio"]
    h = host(installed("tsi-firefox") + installed("U1", section="host", depends=current), depends=current)
    plan = plan_host(h, REPO, "tsi", store={"tis-obs-studio": pkg("tis-obs-studio")})
    assert [f.action for f in plan.fixes] == ["import"] and not plan.needs_upload
    assert plan_host(h, REPO, "tsi").fixes == []                            # without --fix-missing
