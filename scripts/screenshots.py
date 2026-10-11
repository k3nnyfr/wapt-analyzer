"""Regenerate the documentation screenshots from the demo report, with headless Chrome or Chromium.

    uv run python scripts/screenshots.py [--offline]

Chrome is looked up in $CHROME, then in the PATH, then on the Windows side when run from WSL.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "docs" / "images"
WINDOWS_CHROME = [
    "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
    "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
]

# image name -> (tab anchor, script run once the page is loaded)
SHOTS = {
    "report-import.png": ("import", "document.querySelectorAll('#import input.pick:not(:disabled)')"
                                    ".forEach((c, i) => { if (i < 4) { c.checked = true;"
                                    " c.dispatchEvent(new Event('change')); } });"),
    "report-hosts.png": ("hostpkgs", ""),
    "report-groups.png": ("groups", ""),
    "report-health.png": ("health", ""),
    "report-deploy.png": ("deploy", "document.querySelector('#t-deploy details')?.setAttribute('open', '');"),
}


def find_chrome() -> str:
    for candidate in [os.environ.get("CHROME"), shutil.which("chromium"), shutil.which("chromium-browser"),
                      shutil.which("google-chrome"), *WINDOWS_CHROME]:
        if candidate and Path(candidate).exists():
            return candidate
    sys.exit("Chrome or Chromium not found: set $CHROME")


def windows_path(path: Path) -> str:
    return subprocess.run(["wslpath", "-w", str(path)], check=True, capture_output=True, text=True).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true", help="Use the cached store index")
    args = parser.parse_args()
    chrome = find_chrome()
    on_windows = chrome.endswith(".exe")
    # A Windows browser cannot read the WSL filesystem reliably: work in the Windows temporary directory
    if on_windows:
        temp = subprocess.run(["cmd.exe", "/c", "echo %TEMP%"], capture_output=True, text=True, cwd="/mnt/c")
        base = Path(subprocess.run(["wslpath", "-u", temp.stdout.strip()], capture_output=True, text=True)
                    .stdout.strip())
    else:
        base = Path(tempfile.gettempdir())
    work = Path(tempfile.mkdtemp(prefix="wapt-shots-", dir=base))
    try:
        demo = work / "demo.html"
        subprocess.run([sys.executable, str(ROOT / "scripts" / "demo_report.py"), "-o", str(demo),
                        *(["--offline"] if args.offline else [])], check=True)
        html = demo.read_text(encoding="utf-8")
        IMAGES.mkdir(parents=True, exist_ok=True)
        for name, (tab, script) in SHOTS.items():
            page = work / f"{tab}.html"
            # The tab is selected by the URL anchor, which also scrolls the page down to it: back to the top
            page.write_text(html.replace("</body>", f"<script>addEventListener('load', () => {{ {script} "
                                                    "setTimeout(() => scrollTo(0, 0), 300); });</script></body>"),
                            encoding="utf-8")
            shot = work / name
            target = windows_path(shot) if on_windows else str(shot)
            url = ("file:///" + windows_path(page).replace("\\", "/") if on_windows else page.as_uri()) + f"#{tab}"
            subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1400,1000",
                            "--virtual-time-budget=8000", f"--screenshot={target}", url],
                           check=True, capture_output=True, cwd="/mnt/c" if on_windows else None, timeout=120)
            shutil.copyfile(shot, IMAGES / name)
            print(f"{IMAGES / name}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
