"""Right-to-left text (Arabic, Persian, Urdu) in a full-screen terminal app.

Terminals that support bidi (VTE: GNOME Terminal, Ptyxis, Tilix, ...) reorder each *screen line* that contains RTL
characters. A TUI draws several panes on one screen line, so the terminal flips whole rows across pane borders. So
`cli.main` switches the terminal to explicit mode (BDSM off, `CSI 8 l`: "the application has already reordered"),
and the app reorders RTL text itself, one field at a time, with :func:`visual_order`.

Under tmux, the mode switch has to reach the real terminal outside it: tmux swallows unknown sequences, so it is
wrapped in tmux's passthrough sequence, and `allow-passthrough` is turned on for the app's own pane while it runs.

Order of operations matters: wrap or truncate in *logical* order first, then reorder each line; otherwise a long
Arabic name would lose its beginning instead of its end, and wrapped lines would read bottom-up.

:func:`visual_order` is a compact form of the Unicode Bidirectional Algorithm (UAX #9): strong types, weak-type
rules for numbers, neutrals, implicit levels and reordering (L1, L2, L4), without explicit embeddings or isolates,
which card names and comments don't use.
"""

from __future__ import annotations

import os
import subprocess
import unicodedata
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import TextIO

from rich.console import Console, ConsoleOptions, RenderResult
from rich.measure import Measurement
from rich.text import Text

ENTER_EXPLICIT_MODE = "\x1b[8l"  # BDSM reset: the terminal must not reorder
LEAVE_EXPLICIT_MODE = "\x1b[8h"  # back to the terminal's default, implicit mode


def _tmux(*args: str) -> str | None:
    try:
        result = subprocess.run(["tmux", *args], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def tmux_wrap(sequence: str) -> str:
    """tmux passes a DCS `tmux;` sequence (with ESCs doubled) straight to the outer terminal."""
    return "\x1bPtmux;" + sequence.replace("\x1b", "\x1b\x1b") + "\x1b\\"


@contextmanager
def explicit_mode(terminal: TextIO | None) -> Iterator[None]:
    """Stop the terminal reordering RTL lines while the app runs, then put it back."""
    if terminal is None:
        yield
        return
    pane = os.environ.get("TMUX_PANE") if os.environ.get("TMUX") else None
    enabled_passthrough = False
    if pane:
        if _tmux("show", "-Apv", "-t", pane, "allow-passthrough") not in ("on", "all"):
            enabled_passthrough = _tmux("set", "-p", "-t", pane, "allow-passthrough", "on") is not None
    wrap = tmux_wrap if pane else str
    terminal.write(wrap(ENTER_EXPLICIT_MODE))
    terminal.flush()
    try:
        yield
    finally:
        terminal.write(wrap(LEAVE_EXPLICIT_MODE))
        terminal.flush()
        if enabled_passthrough:
            _tmux("set", "-pu", "-t", pane, "allow-passthrough")

MIRRORED = str.maketrans("()[]{}<>«»", ")(][}{><»«")
_CONSOLE = Console()  # only used to resolve style names


def has_rtl(text: str) -> bool:
    return any(unicodedata.bidirectional(ch) in ("R", "AL") for ch in text)


def base_is_rtl(text: str) -> bool:
    """A paragraph's direction is that of its first strong character (rules P2, P3)."""
    for ch in text:
        kind = unicodedata.bidirectional(ch)
        if kind == "L":
            return False
        if kind in ("R", "AL"):
            return True
    return False


def _resolve_types(text: str, rtl: bool) -> list[str]:
    """Reduce every character to "L", "R" or "N" (number, as "EN"/"AN") per rules W1-W7 and N1-N2."""
    base = "R" if rtl else "L"
    types = [unicodedata.bidirectional(ch) for ch in text]

    # W1: non-spacing marks take the type of the character before them.
    for i, kind in enumerate(types):
        if kind == "NSM":
            types[i] = types[i - 1] if i else base

    # W2, W3: European numbers after Arabic letters are Arabic numbers; AL is R.
    last_strong = base
    for i, kind in enumerate(types):
        if kind in ("L", "R", "AL"):
            last_strong = kind
        elif kind == "EN" and last_strong == "AL":
            types[i] = "AN"
    types = ["R" if kind == "AL" else kind for kind in types]

    # W4: one separator between two numbers of the same kind joins them (1,000  3.5).
    for i in range(1, len(types) - 1):
        before, kind, after = types[i - 1], types[i], types[i + 1]
        if before == after == "EN" and kind in ("ES", "CS"):
            types[i] = "EN"
        elif before == after == "AN" and kind == "CS":
            types[i] = "AN"

    # W5: terminators next to European numbers are part of them (100%, $5).
    for i, kind in enumerate(types):
        if kind == "ET":
            j = i
            while j < len(types) and types[j] == "ET":
                j += 1
            if (i and types[i - 1] == "EN") or (j < len(types) and types[j] == "EN"):
                for k in range(i, j):
                    types[k] = "EN"

    # W6: leftover separators and terminators are neutral. W7: numbers after L are L.
    last_strong = base
    for i, kind in enumerate(types):
        if kind in ("ES", "ET", "CS"):
            types[i] = kind = "ON"
        if kind in ("L", "R"):
            last_strong = kind
        elif kind == "EN" and last_strong == "L":
            types[i] = "L"

    # N1, N2: a run of neutrals between two strong types of the same direction takes it; otherwise the base.
    # Numbers count as R here.
    def direction(kind: str) -> str | None:
        return "L" if kind == "L" else "R" if kind in ("R", "EN", "AN") else None

    i = 0
    while i < len(types):
        if direction(types[i]):
            i += 1
            continue
        j = i
        while j < len(types) and not direction(types[j]):
            j += 1
        before = direction(types[i - 1]) if i else base
        after = direction(types[j]) if j < len(types) else base
        for k in range(i, j):
            types[k] = (before if before == after else None) or base
        i = j
    return types


def visual_order(text: str, rtl: bool | None = None) -> list[int]:
    """The logical indexes of `text` (one line) in left-to-right display order."""
    if rtl is None:
        rtl = base_is_rtl(text)
    base_level = 1 if rtl else 0
    types = _resolve_types(text, rtl)

    # I1, I2: implicit levels.
    levels = []
    for kind in types:
        if base_level == 0:
            levels.append(1 if kind == "R" else 2 if kind in ("EN", "AN") else 0)
        else:
            levels.append(2 if kind in ("L", "EN", "AN") else 1)

    # L1: trailing whitespace goes back to the paragraph level.
    i = len(text)
    while i and unicodedata.bidirectional(text[i - 1]) in ("WS", "S", "B"):
        i -= 1
        levels[i] = base_level

    # L2: from the highest level down to the lowest odd one, reverse every run at that level or higher.
    order = list(range(len(text)))
    if not levels:
        return order
    lowest_odd = min((level for level in levels if level % 2), default=None)
    if lowest_odd is None:
        return order
    for level in range(max(levels), lowest_odd - 1, -1):
        i = 0
        while i < len(order):
            if levels[order[i]] >= level:
                j = i
                while j < len(order) and levels[order[j]] >= level:
                    j += 1
                order[i:j] = reversed(order[i:j])
                i = j
            else:
                i += 1
    return order


def _odd_levels(text: str, rtl: bool) -> set[int]:
    """Indexes displayed right-to-left, whose brackets must be mirrored (L4)."""
    types = _resolve_types(text, rtl)
    return {i for i, kind in enumerate(types) if kind == "R"}


def visual(text: Text | str, rtl: bool | None = None, console: Console | None = None) -> Text:
    """Reorder one line of (styled) text for display. Text without RTL characters is returned unchanged."""
    if isinstance(text, str):
        text = Text(text)
    plain = text.plain
    if not has_rtl(plain):
        return text
    if rtl is None:
        rtl = base_is_rtl(plain)
    console = console or _CONSOLE
    mirrored = _odd_levels(plain, rtl)
    result = Text(style=text.style, end="", no_wrap=True)
    for i in visual_order(plain, rtl):
        char = plain[i].translate(MIRRORED) if i in mirrored else plain[i]
        result.append(char, style=text.get_style_at_offset(console, i))
    return result


def fit(text: Text | str, width: int, console: Console | None = None, rtl: bool | None = None) -> Text:
    """One line, cut to `width` cells at its logical end (with an ellipsis), reordered, padded to `width`. `rtl`
    is the base direction, as for :func:`visual`: by default the first strong character's."""
    if isinstance(text, str):
        text = Text(text)
    line = text.copy()
    line.truncate(width, overflow="ellipsis")
    line = visual(line, rtl, console=console)
    line.pad_right(width - line.cell_len)
    return line


class BidiText:
    """A Rich renderable for text that may contain RTL paragraphs: wraps (or truncates) each paragraph in logical
    order at the available width, then reorders each line and right-aligns RTL paragraphs. Text without RTL
    characters renders exactly as the plain `Text` would."""

    def __init__(self, text: Text | str, *, wrap: bool = True, align_rtl: bool = True) -> None:
        self.text = Text(text) if isinstance(text, str) else text
        self.wrap = wrap
        self.align_rtl = align_rtl

    def __rich_measure__(self, console: Console, options: ConsoleOptions) -> Measurement:
        return Measurement.get(console, options, self.text)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        if not has_rtl(self.text.plain):
            yield self.text
            return
        width = options.max_width
        lines = Text(no_wrap=True)
        for n, line in enumerate(self._lines(console, width)):
            if n:
                lines.append("\n")
            lines.append_text(line)
        yield lines

    def _lines(self, console: Console, width: int) -> Iterable[Text]:
        for paragraph in self.text.split("\n", allow_blank=True):
            rtl = base_is_rtl(paragraph.plain)
            if self.wrap:
                pieces = list(paragraph.wrap(console, width, no_wrap=False)) or [Text("")]
            else:
                piece = paragraph.copy()
                piece.truncate(width, overflow="ellipsis")
                pieces = [piece]
            for piece in pieces:
                piece.rstrip()
                line = visual(piece, rtl, console)
                if rtl and self.align_rtl:
                    line = Text.assemble(" " * max(0, width - line.cell_len), line)
                yield line
