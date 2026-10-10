import copy

import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from wapt_analyzer.cli import Indexes, pick_requests
from wapt_analyzer.config import DEFAULTS
from wapt_analyzer.packages import PackageEntry, PackageFilters, Version, index_by_family
from wapt_analyzer.picker import Choice, pick

DOWN, ENTER, ESC, CTRL_A, CTRL_D, BACKSPACE = "\x1b[B", "\r", "\x1b", "\x01", "\x04", "\x7f"


def choices():
    return [Choice("firefox", "tis-firefox", ("130.0-1", "Windows")),
            Choice("gimp", "tis-gimp", ("2.10-1", "macOS"), selected=True),
            Choice("acrobat", "tis-adobe-acrobat", ("2026-1", "Windows"), disabled="réservé aux abonnés"),
            Choice("vlc", "tis-vlc", ("3.0-1", "Windows"))]


def run(keys: list[str], items=None):
    with create_pipe_input() as inp:
        for k in keys:
            inp.send_text(k)
        return pick(items or choices(), "Test", input=inp, output=DummyOutput())


@pytest.mark.parametrize("keys, expected", [
    ([ENTER], ["gimp"]),                                     # preselection kept
    ([" ", ENTER], ["firefox", "gimp"]),                     # toggle the first entry
    ([DOWN, " ", ENTER], []),                                # untoggle gimp
    ([DOWN, DOWN, " ", ENTER], ["gimp"]),                    # disabled entry: cannot be checked
    ([CTRL_A, ENTER], ["firefox", "gimp", "vlc"]),           # all but the disabled one
    ([CTRL_A, CTRL_D, ENTER], []),
    (["vlc", " ", ENTER], ["gimp", "vlc"]),                  # filter, then toggle the only visible entry
    (["windows", CTRL_A, ENTER], ["firefox", "gimp", "vlc"]),  # filter on a column, select the visible ones
    (["zzz", " ", BACKSPACE * 3, ENTER], ["gimp"]),          # nothing visible: space does nothing
    ([" ", ESC], None),                                      # cancelled
])
def test_pick(keys, expected):
    assert run(keys) == expected


def pkg(package, version, target_os="windows", **fields):
    return PackageEntry(package=package, version=Version(version), fields={
        "package": package, "version": version, "target_os": target_os, "architecture": "x64", "section": "base",
        "filename": f"{package}_{version}_{target_os}.wapt", "size": "2048", **fields})


def test_pick_requests(monkeypatch):
    cfg = copy.deepcopy(DEFAULTS)
    cfg["repo"]["prefix"] = "tsi"
    repo = index_by_family([pkg("tsi-firefox", "130.0-1")])
    store = [pkg("tis-firefox", "131.0-1"), pkg("tis-acrobat", "1-1", licence="wapt_enterprise"),
             pkg("tis-waptupgrade", "2.7-1")]
    idx = Indexes("https://wapt", "https://wapt/wapt", "https://store", repo, index_by_family(store), store, b"",
                  PackageFilters(), [])
    captured = {}

    def fake_pick(items, title):
        captured.update(items=items, title=title)
        return [items[0].value]

    monkeypatch.setattr("wapt_analyzer.cli.pick", fake_pick)
    requested = [(e, ["windows"]) for e in store]
    candidates = [{"filename": store[0].filename, "host_count": 3}]
    assert pick_requests(cfg, idx, requested, candidates, preselect=True) == [requested[0]]

    firefox, acrobat, upgrade = captured["items"]
    assert firefox.columns[:2] == ("130.0-1 → 131.0-1", "Windows") and "3 poste(s)" in firefox.columns
    assert firefox.selected
    assert acrobat.disabled.startswith("réservé aux abonnés") and not acrobat.selected
    assert upgrade.disabled == "exclu par la configuration"
    assert captured["title"] == "Paquets à importer depuis https://store (3)"
