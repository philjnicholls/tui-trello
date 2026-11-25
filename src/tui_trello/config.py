"""Settings, read from the environment and then from `$XDG_CONFIG_HOME/tui-trello/config.toml`.

```toml
[trello]
default_board = "AbCd1234"   # board id or short link; omit to pick a board at start-up
# Rarely needed:
# oauth_port = 8765          # login callback port: http://127.0.0.1:<port>/callback

[remote]
enabled = true               # false: make no request to GitHub for news

[ui]
layout = "browser"           # browser, triage, mywork or notifications
transparent = true           # draw on the terminal's own background (and its transparency); false paints the theme's

[notifications]
interval = 60                # check Trello for new notifications every this many seconds; 0 turns checking off
desktop = true               # raise a desktop notification for each new one, as well as the in-app toast

[keys]                       # change any key: `tui-trello keys` lists every action (id) and its key
card.delete = "ctrl+x"       # one key, or a list: ["f", "ctrl+f"], or "j,down"
chord.next_view = "g n"      # a two-key sequence
```

`TRELLO_BOARD` overrides `default_board`.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

LAYOUTS = ("browser", "triage", "mywork", "notifications")

# Settings from when tui-trello could log in with an API key and a pasted token. They do nothing now; a setting that
# is still there gets a warning, so nobody wonders why it has no effect.
RETIRED_KEYS = ("api_key", "token")  # in [trello]
RETIRED_ENV = ("TRELLO_API_KEY", "TRELLO_TOKEN")


def config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "tui-trello" / "config.toml"


def state_dir() -> Path:
    """Where the app keeps what it writes itself (drafts, remembered choices): `$XDG_STATE_HOME/tui-trello`."""
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "tui-trello"


def flatten_keys(table: dict, prefix: str = "") -> dict[str, object]:
    """`[keys]` with its nested tables as dotted ids: TOML reads `card.archive = "A"` as a table `card` holding
    `archive`, so that, `"card.archive" = "A"` and a `[keys.card]` table all give `{"card.archive": "A"}`."""
    flat: dict[str, object] = {}
    for name, value in table.items():
        if isinstance(value, dict):
            flat.update(flatten_keys(value, f"{prefix}{name}."))
        else:
            flat[f"{prefix}{name}"] = value
    return flat


@dataclass
class Settings:
    oauth_port: int = 8765
    default_board: str | None = None
    layout: str = "browser"
    transparent: bool = True
    notify_interval: int = 60
    desktop_notifications: bool = True
    remote: bool = True  # fetch the newsfeed from GitHub (tui_trello/remote.py); `[remote] enabled`, or `--no-remote`
    keys: dict[str, object] = field(default_factory=dict)  # `[keys]`, flattened to dotted ids; checked by ui/keymap.py
    warnings: list[str] = field(default_factory=list)  # problems with the file that didn't stop it being read
    retired: list[str] = field(default_factory=list)  # the part of `warnings` about settings that do nothing now

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        path = path or config_path()
        data = tomllib.loads(path.read_text()) if path.exists() else {}
        warnings: list[str] = []
        trello, ui = _table(data, "trello", warnings), _table(data, "ui", warnings)
        notifications = _table(data, "notifications", warnings)
        remote = _table(data, "remote", warnings, "fetching from GitHub is off", {"enabled": False})
        settings = cls(
            oauth_port=int(trello.get("oauth_port", 8765)),
            default_board=os.environ.get("TRELLO_BOARD") or trello.get("default_board"),
            layout=ui.get("layout", "browser"),
            transparent=bool(ui.get("transparent", True)),
            notify_interval=int(notifications.get("interval", 60)),
            desktop_notifications=bool(notifications.get("desktop", True)),
            keys=flatten_keys(_table(data, "keys", warnings)),
            warnings=warnings,
        )
        for key in RETIRED_KEYS:
            if key in trello:
                settings.retired.append(f"[trello] {key} is no longer used: tui-trello logs in with "
                                        "`tui-trello login` only. Remove it.")
        for name in RETIRED_ENV:
            if os.environ.get(name):
                settings.retired.append(f"{name} is set but no longer used: tui-trello logs in with "
                                        "`tui-trello login` only. Unset it.")
        warnings.extend(settings.retired)
        match remote.get("enabled", True):
            case bool() as enabled:
                settings.remote = enabled
            case other:  # a string like "false" is truthy: don't let a privacy opt-out be misread as consent
                settings.remote = False
                warnings.append(f"[remote] enabled must be true or false, not {other!r}; fetching from GitHub is off")
        if settings.layout not in LAYOUTS:
            raise ValueError(f"[ui] layout must be one of {', '.join(LAYOUTS)}, not {settings.layout!r}")
        return settings


def _table(data: dict, name: str, warnings: list[str], ignored: str = "ignored", fallback: dict | None = None) -> dict:
    """The `[name]` section of the file, as a dict. If it isn't a table (`ui = 1`), say so and use `fallback`."""
    match data.get(name, {}):
        case dict() as table:
            return table
        case _:
            warnings.append(f"[{name}] must be a table; {ignored}")
            return fallback or {}
