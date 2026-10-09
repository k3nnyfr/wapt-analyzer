from wapt_analyzer.analysis import analyze, normalize
from wapt_analyzer.packages import PackageEntry, Version, index_by_family
from wapt_analyzer.report import import_candidates, to_dict
from wapt_analyzer.server import Host


def pkg(package, version="1.0-1", target_os="windows", **fields):
    return PackageEntry(package=package, version=Version(version),
                        fields={"package": package, "target_os": target_os, "section": "base",
                                "filename": f"{package}_{version}_{target_os}.wapt", **fields})


def soft(name, publisher="", key=None):
    return {"name": name, "publisher": publisher, "version": "1", "key": key or name}


REPO = index_by_family([
    pkg("tsi-7zip", "24.07-1", name="7-Zip"),
    pkg("tsi-firefox", "130.0-1", name="Mozilla Firefox"),
    pkg("tsi-firefox", "130.0-1", target_os="darwin", name="Mozilla Firefox"),
])
STORE = index_by_family([
    pkg("tis-7zip", "24.08-3", name="7-Zip", editor="Igor Pavlov"),
    pkg("tis-firefox", "130.0-5", name="Mozilla Firefox"),
    pkg("tis-firefox-esr", "128.0-5", name="Mozilla Firefox ESR"),
    pkg("tis-keepassxc", "2.7.9-1", name="KeePassXC"),
    pkg("tis-gimp", "2.10.38-1", name="GIMP"),
    pkg("tis-gimp", "2.10.38-1", target_os="darwin", name="GIMP"),
    pkg("tis-java8", "10.0-2", name="Java 8 JRE"),
    pkg("tis-libreoffice-fresh", "26.8.0-37", name="LibreOffice Fresh"),
    pkg("tis-libreoffice-still", "26.2.5-43", name="LibreOffice Still"),
    pkg("tis-remove-copilot", name="Remove Copilot"),
    pkg("tis-microsoft-teams", name="Microsoft Teams classic"),
    pkg("tis-microsoft-teams-uwp", name="Microsoft Teams (work or school)"),
    pkg("tis-xcode", target_os="darwin", name="Xcode"),
    pkg("tis-vscode", target_os="darwin", name="Visual Studio Code"),
    pkg("tis-obsidian", name="Obsidian"),
])


def hosts():
    return [
        Host(uuid="U1", name="pc1", os_name="Windows 11 Pro",
             installed_packages=[
                 {"package": "tis-keepassxc", "version": "2.7.9-1", "section": "base", "install_status": "OK"},
                 {"package": "tis-firefox", "version": "130.0-5", "section": "base", "uninstall_key": ["FF"]},
                 {"package": "U1", "section": "host"},
                 {"package": "grp-compta", "section": "group"},
             ],
             installed_softwares=[
                 soft("Mozilla Firefox (x64 fr)", key="FF"),
                 soft("Mozilla Firefox ESR (x64 fr)"),
                 soft("7-Zip 24.08 (x64)"),
                 soft("GIMP 2.10.38"),
                 soft("Security Update for Microsoft Excel (KB5002000)"),
                 soft("ACME internal tool"),
                 soft("Microsoft Teams"),
                 soft("Java 8 Update 311"),
                 soft("LibreOffice 25.2.5.2"),
                 soft("Copilot"),
             ]),
        Host(uuid="U2", name="pc2", os_name="Windows 10 Pro",
             installed_packages=[{"package": "tsi-keepassxc", "version": "2.7.8-1", "section": "base"}],
             installed_softwares=[soft("GIMP 2.10.36"), soft("Ignored thing")]),
        Host(uuid="M1", name="mac1", os_name="macOS 26.6.2 ",
             installed_packages=[
                 {"package": "tsi-firefox", "version": "130.0-1", "section": "base", "uninstall_key": []},
                 {"package": "tsi-vscode", "version": "1.120.0-44", "section": "base", "uninstall_key": []},
                 {"package": "tsi-7zip", "version": "26.3-44", "section": "base", "uninstall_key": []},
             ],
             installed_softwares=[
                 soft("Firefox", "mozilla", "/Applications/Firefox.app"),
                 soft("Code", "microsoft", "/Applications/Visual Studio Code.app"),
                 soft("GIMP", "gimp", "/Applications/GIMP.app"),
                 soft("Obsidian", "obsidian", "/Applications/Obsidian.app"),
                 soft("Mail", "apple", "/System/Applications/Mail.app"),
                 soft("com.apple.pkg.CLTools_SDK_macOS13", key="pkgid:com.apple.pkg.CLTools_SDK_macOS13"),
             ]),
    ]


def run(**kw):
    kw.setdefault("mappings", {r"^Code$": "vscode"})
    return analyze(REPO, STORE, hosts(), exclude=[r"\bKB\d+"], exclude_keys=[r"^/System/", r"^pkgid:"],
                   exclude_publishers=[r"^apple$"], **kw)


def test_normalize():
    assert normalize("Mozilla Firefox (x64 fr)") == "mozilla firefox"
    assert normalize("7-Zip 24.08 (x64)") == "7 zip"
    assert normalize("Notepad++ (64-bit x64)") == "notepad++"
    office = "Microsoft Office LTSC Professionnel Plus 2021 - fr-fr"
    assert normalize(office) == "microsoft office ltsc professionnel plus"
    assert normalize("PuTTY release 0.83 (64-bit)") == "putty"


def test_missing_packages_per_os():
    result = run()
    missing = {(m.family, m.base): m for m in result.missing_packages}
    assert set(missing) == {("windows", "keepassxc"), ("macos", "vscode"), ("macos", "7zip")}
    kp = missing[("windows", "keepassxc")]
    assert kp.hosts == {"pc1", "pc2"}
    assert kp.packages_seen == {"tis-keepassxc", "tsi-keepassxc"}
    assert kp.store.package == "tis-keepassxc"
    # tsi-7zip exists in the repo for Windows only
    assert missing[("macos", "7zip")].other_os == ["windows"]
    assert missing[("macos", "vscode")].store.package == "tis-vscode"


def test_software_classification_windows():
    result = run()
    to_import = {g.key: g for g in result.software_to_import if g.family == "windows"}
    assert to_import["gimp"].match.package == "tis-gimp"
    assert to_import["gimp"].hosts == {"pc1", "pc2"}
    teams = to_import["microsoft teams"]
    assert teams.match.package == "tis-microsoft-teams"
    assert [a.package for a in teams.alternatives] == ["tis-microsoft-teams-uwp"]
    assert to_import["java 8 311"].match.package == "tis-java8"                        # compact form
    assert to_import["mozilla firefox esr"].match.package == "tis-firefox-esr"     # store exact beats repo fuzzy
    libre = to_import["libreoffice"]
    assert libre.match.package == "tis-libreoffice-fresh" and libre.score == 90  # subset of the name
    assert "copilot" not in to_import                                            # not "tis-remove-copilot"
    assert "mozilla firefox" not in to_import                                    # installed by WAPT (uninstall key)
    assert [g.match.package for g in result.software_unmanaged] == ["tsi-7zip"]
    unmatched = {g.key for g in result.software_unmatched if g.family == "windows"}
    assert unmatched == {"acme internal tool", "ignored thing", "copilot"}


def test_software_classification_macos():
    result = run()
    to_import = {g.key: g for g in result.software_to_import if g.family == "macos"}
    unmatched = {g.key: g for g in result.software_unmatched if g.family == "macos"}
    unmanaged = {g.key for g in result.software_unmanaged if g.family == "macos"}
    # Firefox and VS Code are installed by WAPT packages without uninstall keys
    assert "firefox" not in unmanaged and "code" not in to_import and "code" not in unmatched
    assert to_import["gimp"].match.target_os == "darwin"
    assert unmatched["obsidian"].other_os == ["windows"]
    assert result.excluded_count == 3  # KB update, /System app, pkgid receipt


def test_mappings():
    result = run(mappings={"^ACME": "gimp", "^Ignored": ""})
    acme = next(g for g in result.software_to_import if g.key == "acme internal tool")
    assert acme.match.package == "tis-gimp" and acme.match_source == "mapping"
    assert not {g.key for g in result.software_unmatched} & {"acme internal tool", "ignored thing"}


def test_outdated_and_candidates():
    result = run()
    assert [(o.family, o.local.package, o.store.package, o.kind) for o in result.outdated] == [
        ("windows", "tsi-7zip", "tis-7zip", "upstream"),        # 24.07 -> 24.08
        ("windows", "tsi-firefox", "tis-firefox", "packaging"),  # 130.0-1 -> 130.0-5
    ]  # the macOS tsi-firefox has no newer store variant
    candidates = import_candidates(to_dict(result, {}))
    by_file = {c["filename"]: c for c in candidates}
    assert by_file["tis-gimp_2.10.38-1_windows.wapt"]["host_count"] == 2
    assert by_file["tis-gimp_2.10.38-1_darwin.wapt"]["os"] == ["macos"]
    assert candidates[0]["package"] == "tis-gimp"


def test_find_updates_matches_os_and_architecture():
    from wapt_analyzer.analysis import find_updates
    from wapt_analyzer.packages import PackageFilters

    repo = index_by_family([
        pkg("tsi-vlc", "3.0.23-13", architecture="x64"),
        pkg("tsi-vlc", "3.0.23-15", target_os="darwin", architecture="all"),
        pkg("tsi-own", "1.0-1"),
    ])
    store_entries = [
        pkg("tis-vlc", "3.0.24-13", architecture="x64"),
        pkg("tis-vlc", "3.0.30-1", architecture="x86"),              # other architecture: ignored
        pkg("tis-vlc", "3.0.40-1", architecture="x64", maturity="BETA"),  # filtered maturity
        pkg("tis-vlc", "3.0.24-16", target_os="darwin", architecture="arm"),
        pkg("tis-own", "0.9-1"),                                      # older: no update
    ]
    updates = find_updates(repo, store_entries, PackageFilters(maturities=("PROD", "")))
    found = {(u.family, u.local.package): (str(u.store.version), u.kind) for u in updates}
    assert found == {
        ("windows", "tsi-vlc"): ("3.0.24-13", "upstream"),
        ("macos", "tsi-vlc"): ("3.0.24-16", "upstream"),   # local "all" accepts any architecture
    }


def test_editions():
    from wapt_analyzer.analysis import editions, editions_compatible

    assert editions("Microsoft Office Professionnel Plus 2016 - fr-fr") == {"2016"}
    assert editions("Microsoft 365 Apps for enterprise - en-us") == {"365"}
    assert editions("Microsoft Visual C++ v14 Redistributable (x64) - 14.50.35719") == {"14"}
    assert editions("vcredist2015-2022") == {"2015", "2022"}
    assert editions("Java 8 Update 311") == {"8"}             # update number is not an edition
    assert editions("Mp3tag v3.33.1") == set()                 # dotted version
    assert editions("OpenVPN 2.5.7-I602 amd64") == set()       # build code
    assert editions("Notepad++ (64-bit x64)") == set()         # architecture
    assert editions_compatible(frozenset({"14"}), frozenset())  # "TeamViewer 14" -> tis-teamviewer
    assert not editions_compatible(frozenset({"2016"}), frozenset({"2024"}))


def test_office_editions_are_not_mixed():
    store = index_by_family([
        pkg("tis-microsoft-office-2019-professional", name="Office Professional Plus 2019"),
        pkg("tis-microsoft-office-2021-professional", name="Office LTSC Professional Plus 2021"),
        pkg("tis-microsoft-office-2024-professional", name="Office LTSC Professional Plus 2024"),
        pkg("tis-teamviewer", name="TeamViewer"),
    ])
    host = Host(uuid="U9", name="pc9", os_name="Windows 11 Pro", installed_softwares=[
        soft("Microsoft Office Professional Plus 2019 - fr-fr"),
        soft("Microsoft Office Professionnel Plus 2016 - fr-fr"),
        soft("Microsoft Office LTSC Professional Plus 2021"),
        soft("TeamViewer 14"),
    ])
    result = analyze(index_by_family([]), store, [host])
    matched = {g.editions: g.match.package for g in result.software_to_import if g.key.startswith("microsoft office")}
    assert matched == {frozenset({"2019"}): "tis-microsoft-office-2019-professional",
                       frozenset({"2021"}): "tis-microsoft-office-2021-professional"}
    office_2016 = next(g for g in result.software_unmatched if g.editions == {"2016"})
    assert {e.package for e in office_2016.other_editions} >= {"tis-microsoft-office-2024-professional"}
    assert any(g.match.package == "tis-teamviewer" for g in result.software_to_import)
