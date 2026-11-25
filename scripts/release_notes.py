"""Print one version's section of CHANGELOG.md, for a GitHub Release: `python scripts/release_notes.py 0.1.0`.

Exits 1, printing nothing, if the changelog has no section for the version.
"""

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def section(version: str, text: str) -> str | None:
    """The body of `## [version] - date` up to the next `## ` heading (or the link references), or None."""
    heading = re.search(rf"^## \[{re.escape(version)}\].*$", text, re.MULTILINE)
    if not heading:
        return None
    rest = text[heading.end():]
    end = re.search(r"^(## |\[[^\]]+\]: )", rest, re.MULTILINE)
    return (rest[:end.start()] if end else rest).strip() + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: release_notes.py VERSION", file=sys.stderr)
        return 2
    notes = section(argv[1].removeprefix("v"), CHANGELOG.read_text(encoding="utf-8"))
    if notes is None:
        print(f"CHANGELOG.md has no section for version {argv[1]}", file=sys.stderr)
        return 1
    print(notes, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
