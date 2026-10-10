from wapt_analyzer.grouppkg import group_control, plan_missing_groups, plans_to_dict, suggest_groups
from wapt_analyzer.packages import PackageEntry, Version
from wapt_analyzer.server import Host


def pkg(package, version="1.0-1", section="base", depends=""):
    return PackageEntry(package=package, version=Version(version), fields={
        "package": package, "version": version, "target_os": "windows", "section": section, "depends": depends})


REPO = [pkg("tsi-7zip"), pkg("tsi-firefox"), pkg("tsi-vlc"), pkg("tsi-chrome"), pkg("tsi-webview2"),
        pkg("tsi-teams", depends="tsi-webview2"), pkg("grp-office", section="group", depends="tsi-chrome")]


def host(name, packages=(), groups=()):
    rows = [{"package": p, "version": "1", "section": "base"} for p in packages]
    rows += [{"package": g, "version": v, "section": "group", "depends": d, "maturity": "PROD"} for g, v, d in groups]
    return Host(uuid=name, name=name, os_name="Windows 11 Pro", installed_packages=rows)


def test_recreate_missing_groups():
    hosts = [host("pc1", groups=[("grp-base", "16", ["tsi-7zip"])]),
             host("pc2", groups=[("grp-base", "17", ["tsi-7zip", "tsi-flashplayer"]), ("grp-office", "3", [])])]
    (plan,) = plan_missing_groups(hosts, REPO)                  # grp-office is in the repository
    assert (plan.package, plan.version, plan.hosts) == ("grp-base", "17", ["pc1", "pc2"])
    assert plan.depends == ["tsi-7zip"] and plan.missing == ["tsi-flashplayer"] and plan.changed
    assert group_control(plan) == {"maturity": "PROD", "package": "grp-base", "version": "17",
                                   "depends": "tsi-7zip"}
    (kept,) = plan_missing_groups(hosts, REPO, keep_missing=True)
    assert kept.depends == ["tsi-7zip", "tsi-flashplayer"] and not kept.changed   # identical: same version


def test_suggest_common_base():
    hosts = [host(f"pc{i}", ["tsi-7zip", "tsi-firefox", "tsi-teams", "tsi-webview2", "tsi-chrome"]
                  + (["tsi-vlc"] if i < 2 else [])) for i in range(4)]
    recreate = plan_missing_groups([host("pc0", groups=[("grp-base", "1", ["tsi-7zip"])])], REPO)
    (plan,) = suggest_groups(hosts, REPO, "tsi", extra_groups=recreate)
    assert plan.package == "grp-socle-windows" and plan.family == "windows"
    # 7zip: in the recreated grp-base; chrome: in grp-office; webview2: pulled by teams; vlc: 2/4 hosts only
    assert plan.depends == ["tsi-firefox", "tsi-teams"] and plan.counts == {"tsi-firefox": 4, "tsi-teams": 4}
    assert plans_to_dict([], [plan])["suggested"][0]["depends"][0] == {"package": "tsi-firefox", "hosts": 4}
    # Too few hosts, or a group with that name already exists: no suggestion
    assert not suggest_groups(hosts[:2], REPO, "tsi")
    assert not suggest_groups(hosts, REPO + [pkg("grp-socle-windows", section="group")], "tsi")
