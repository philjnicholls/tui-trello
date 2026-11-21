"""Choices made in the app that it keeps between runs, in `$XDG_STATE_HOME/tui-trello/prefs.json`.

Settings a user writes by hand live in config.toml (`tui_trello.config`); these are the ones a key toggles, such as
`u` hiding read notifications, written back as they change. A missing or unreadable file gives the defaults.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from tui_trello.config import state_dir


def prefs_path() -> Path:
    return state_dir() / "prefs.json"


class Prefs:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or prefs_path()
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            data = {}
        self._data: dict[str, Any] = data if isinstance(data, dict) else {}

    @property
    def hide_read_notifications(self) -> bool:
        return bool(self._data.get("hide_read_notifications", True))

    @hide_read_notifications.setter
    def hide_read_notifications(self, hide: bool) -> None:
        self._set("hide_read_notifications", hide)

    def _set(self, key: str, value: Any) -> None:
        if self._data.get(key) == value:
            return
        self._data[key] = value
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=1))
            os.replace(tmp, self.path)
        except OSError:
            pass  # still applies for this run; a read-only home shouldn't stop the app
