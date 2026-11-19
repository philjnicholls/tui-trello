"""Copying links to the clipboard.

On a local graphical session the desktop's own tool does it: wl-copy on Wayland, xclip or xsel on X11, pbcopy on
macOS. Elsewhere (over SSH, or with none of them installed) the terminal is asked to, with OSC 52; most terminals do
(kitty, WezTerm, iTerm2, foot, Windows Terminal, tmux), but VTE ones (GNOME Terminal, Ptyxis, Tilix) don't.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping


def command(env: Mapping[str, str] | None = None, platform: str = sys.platform) -> list[str] | None:
    """The local clipboard tool to use, or None to ask the terminal."""
    env = os.environ if env is None else env
    if env.get("SSH_CONNECTION"):
        return None  # the tools would fill the remote machine's clipboard, not the user's
    candidates = []
    if platform == "darwin":
        candidates.append(["pbcopy"])
    if env.get("WAYLAND_DISPLAY"):
        candidates.append(["wl-copy"])
    if env.get("DISPLAY"):
        candidates += [["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
    return next((c for c in candidates if shutil.which(c[0])), None)


def copy(text: str, osc52: Callable[[str], None]) -> None:
    """Put `text` on the clipboard; `osc52` asks the terminal to (the app's `copy_to_clipboard`)."""
    if tool := command():
        try:
            subprocess.run(tool, input=text.encode(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=2, check=True)
            return
        except (OSError, subprocess.SubprocessError):
            pass
    osc52(text)
