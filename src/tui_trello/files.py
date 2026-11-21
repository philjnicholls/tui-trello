"""Local files for attachments: where downloads go, and how sizes read."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path


def download_dir(env: Mapping[str, str] | None = None) -> Path:
    """$XDG_DOWNLOAD_DIR, else ~/Downloads if there is one, else the home directory."""
    env = os.environ if env is None else env
    if configured := env.get("XDG_DOWNLOAD_DIR"):
        return Path(configured).expanduser()
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else Path.home()


def unique_path(directory: Path, name: str) -> Path:
    """`directory/name`, or `name (1)`, `name (2)`, ... before the extension if it's taken."""
    name = Path(name).name or "attachment"  # never a path out of `directory`
    path = directory / name
    stem, suffix = path.stem, path.suffix
    n = 1
    while path.exists():
        path = directory / f"{stem} ({n}){suffix}"
        n += 1
    return path


def human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    return f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} MB"
