"""Desktop notifications for new Trello notifications, while the app runs.

On a local graphical Linux session `notify-send` raises them. Elsewhere (over SSH, on macOS) the terminal is asked
to: OSC 777 for VTE terminals (GNOME Terminal, Ptyxis, Tilix), foot and urxvt; OSC 9 for the rest (iTerm2, WezTerm,
Ghostty, kitty, Windows Terminal). A terminal that knows neither ignores the sequence. Under tmux the sequence is
wrapped for passthrough, which `bidi.explicit_mode` turns on for the app's pane.

The text comes from other people's comments, so control characters are stripped before it reaches the terminal.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable

from tui_trello.ui.bidi import tmux_wrap

CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]+")
OSC777_TERMS = ("foot", "rxvt")


def clean(text: str, limit: int = 200) -> str:
    text = CONTROL.sub(" ", text).strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def sequence(title: str, body: str, env: dict[str, str] | None = None) -> str:
    """The escape sequence that asks this terminal for a notification."""
    env = os.environ if env is None else env
    title, body = clean(title), clean(body)
    if env.get("VTE_VERSION") or env.get("TERM", "").startswith(OSC777_TERMS):
        seq = f"\x1b]777;notify;{title.replace(';', ',')};{body}\x1b\\"
    else:
        seq = f"\x1b]9;{title}: {body}\x1b\\"
    return tmux_wrap(seq) if env.get("TMUX") else seq


def use_notify_send(env: dict[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    local_desktop = (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")) and not env.get("SSH_CONNECTION")
    return bool(local_desktop and shutil.which("notify-send"))


def alert(title: str, body: str, write: Callable[[str], None]) -> None:
    """Raise a desktop notification; `write` sends a sequence to the terminal (the app's driver)."""
    if use_notify_send():
        try:
            subprocess.Popen(["notify-send", "--app-name=tui-trello", "--", clean(title), clean(body)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            pass
    write(sequence(title, body))
