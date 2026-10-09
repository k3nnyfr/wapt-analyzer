import io
import zipfile

from wapt_analyzer.packages import (
    PackageFilters,
    Version,
    entry_os_families,
    host_os_family,
    index_by_family,
    parse_packages_index,
    parse_packages_text,
    split_package_name,
)

INDEX = """package           : tis-firefox
version           : 130.0-10
architecture      : x64
section           : base
name              : Mozilla Firefox
maturity          : PROD
locale            : all
target_os         : windows
description       : Web browser
  second line

package           : tis-firefox
version           : 131.0-1
architecture      : x64
section           : base
name              : Mozilla Firefox
maturity          : PROD
locale            : all
target_os         : windows

package           : tis-firefox
version           : 132.0-1
architecture      : x64
section           : base
maturity          : BETA
target_os         : windows

package           : tis-firefox-mac
version           : 131.0-1
architecture      : all
section           : base
maturity          : PROD
target_os         : macos

package           : 0ad3d7b2-host
version           : 1-1
section           : host
"""


def test_version_ordering():
    assert Version("1.10-1") > Version("1.9-3")
    assert Version("128.0.3-12") > Version("128.0-40")
    assert Version("2.0-1") > Version("2.0-0")
    assert Version("8.9.8.1-12").upstream > Version("8.9.8-12").upstream
    assert Version("1.0-1") == Version("1.0-1")


def test_split_package_name():
    assert split_package_name("tis-firefox-esr") == ("tis", "firefox-esr")
    assert split_package_name("standalone") == ("", "standalone")


def test_parse_and_continuation():
    entries = parse_packages_text(INDEX)
    assert len(entries) == 5
    assert entries[0].description() == "Web browser\nsecond line"
    assert entries[0].base == "firefox"


def test_parse_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Packages", INDEX)
    assert len(parse_packages_index(buf.getvalue())) == 5


def test_index_by_family():
    index = index_by_family(parse_packages_text(INDEX), PackageFilters())
    assert set(index["windows"]) == {"tis-firefox"}  # host section filtered
    assert str(index["windows"]["tis-firefox"].version) == "131.0-1"  # BETA ignored
    assert set(index["macos"]) == {"tis-firefox-mac"}
    assert index["linux"] == {}


def test_os_families():
    entries = {e.package: e for e in parse_packages_text(INDEX)}
    assert entry_os_families(entries["tis-firefox-mac"]) == {"macos"}
    assert host_os_family("macOS 26.6.2 ") == "macos"
    assert host_os_family("Windows 11 Pro") == "windows"
    assert host_os_family("Debian GNU/Linux 12") == "linux"
    multi = parse_packages_text("package : tis-x\ntarget_os : debian(>8),ubuntu,windows\n")[0]
    assert entry_os_families(multi) == {"linux", "windows"}
    universal = parse_packages_text("package : tis-y\ntarget_os : all\n")[0]
    assert entry_os_families(universal) == {"windows", "macos", "linux"}
