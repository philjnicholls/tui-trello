"""The release helpers: the changelog has a section for the version being released, and `scripts/release_notes.py`
prints just that section."""

import subprocess
import sys
from pathlib import Path

from tui_trello import __version__

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "release_notes.py"


def notes(version: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), version], capture_output=True, text=True, check=False)


def test_changelog_has_a_section_for_the_current_version() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text()
    assert "## [Unreleased]" in changelog
    result = notes(__version__)
    assert result.returncode == 0 and result.stdout.strip(), result.stderr


def test_release_notes_prints_only_that_section() -> None:
    result = notes("0.1.0")
    assert result.returncode == 0
    assert result.stdout.startswith("First public release.") and "### Added" in result.stdout
    assert "## [" not in result.stdout and "[Unreleased]:" not in result.stdout
    assert notes("v0.1.0").stdout == result.stdout  # a tag name works too


def test_release_notes_fails_for_an_unknown_version() -> None:
    result = notes("9.9.9")
    assert result.returncode == 1 and result.stdout == "" and "9.9.9" in result.stderr
