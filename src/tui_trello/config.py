"""Settings, read from the environment and then from `$XDG_CONFIG_HOME/tui-trello/config.toml`.

```toml
[trello]
default_board = "tK1afjyM"   # board id or short link; omit to pick a board at start-up
# Rarely needed:
# api_key = "..."            # use another app key instead of tui-trello's own
# oauth_port = 8765          # login callback port: http://127.0.0.1:<port>/callback
# token = "..."              # a token set by hand (scripts, CI); `tui-trello login` is the normal way

[ui]
layout = "browser"           # browser, triage, mywork or notifications
transparent = true           # draw on the terminal's own background (and its transparency); false paints the theme's

[notifications]
interval = 60                # check Trello for new notifications every this many seconds; 0 turns checking off
desktop = true               # raise a desktop notification for each new one, as well as the in-app toast
```

`TRELLO_API_KEY`, `TRELLO_TOKEN` and `TRELLO_BOARD` override the file.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

LAYOUTS = ("browser", "triage", "mywork", "notifications")


def config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "tui-trello" / "config.toml"


@dataclass
class Settings:
    api_key: str = ""
    oauth_port: int = 8765
    token: str = ""
    default_board: str | None = None
    layout: str = "browser"
    transparent: bool = True
    notify_interval: int = 60
    desktop_notifications: bool = True

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        path = path or config_path()
        data = tomllib.loads(path.read_text()) if path.exists() else {}
        trello, ui, notifications = data.get("trello", {}), data.get("ui", {}), data.get("notifications", {})
        settings = cls(
            api_key=os.environ.get("TRELLO_API_KEY") or trello.get("api_key", ""),
            oauth_port=int(trello.get("oauth_port", 8765)),
            token=os.environ.get("TRELLO_TOKEN") or trello.get("token", ""),
            default_board=os.environ.get("TRELLO_BOARD") or trello.get("default_board"),
            layout=ui.get("layout", "browser"),
            transparent=bool(ui.get("transparent", True)),
            notify_interval=int(notifications.get("interval", 60)),
            desktop_notifications=bool(notifications.get("desktop", True)),
        )
        if settings.layout not in LAYOUTS:
            raise ValueError(f"[ui] layout must be one of {', '.join(LAYOUTS)}, not {settings.layout!r}")
        return settings
