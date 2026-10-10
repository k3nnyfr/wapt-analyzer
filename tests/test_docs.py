"""Links between the documentation pages (README.md, docs/*.md) point to existing files and headings."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PAGES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]


def slug(heading: str) -> str:
    """Anchor of a heading, as GitHub and Gitea compute it."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def outside_code(path: Path):
    in_code = False
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code:
            yield n, line


def anchors(path: Path) -> set[str]:
    return {slug(m.group(1)) for _, line in outside_code(path) if (m := re.match(r"^#+ (.*)$", line))}


@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.relative_to(ROOT)))
def test_links(page):
    broken = []
    for n, line in outside_code(page):
        for target in re.findall(r"\]\(([^)\s]+)\)", line):
            if re.match(r"^(https?|mailto):", target):
                continue
            path, _, anchor = target.partition("#")
            dest = (page.parent / path).resolve() if path else page
            if not dest.exists():
                broken.append(f"{n}: {target} (missing file)")
            elif anchor and dest.suffix == ".md" and anchor not in anchors(dest):
                broken.append(f"{n}: {target} (missing heading)")
    assert not broken, broken
