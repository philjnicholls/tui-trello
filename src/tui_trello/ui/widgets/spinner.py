"""A one-cell spinner that turns while the store has anything in flight, with a word saying what."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
LABELS = {"board": "loading board", "work": "loading your cards", "boards": "loading boards",
          "comments": "loading comments", "checklists": "loading checklists", "labels": "loading labels",
          "members": "loading members", "preview": "loading the preview", "notifications": "checking notifications",
          "save": "saving", "search": "searching"}


class Spinner(Static):
    """Goes in a `TopBar`."""

    DEFAULT_CSS = """
    Spinner { width: auto; height: 1; padding: 0 1; color: $accent; background: transparent; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.frame = 0

    def on_mount(self) -> None:
        self.app.store.busy_changed.subscribe(self, lambda _: self.tick())
        self.timer = self.set_interval(0.08, self.tick, pause=not self.app.store.is_busy())
        self.tick()

    def tick(self) -> None:
        store = self.app.store
        if not store.is_busy():
            self.timer.pause()
            self.update("")
            return
        self.timer.resume()
        self.frame = (self.frame + 1) % len(FRAMES)
        what = ", ".join(LABELS.get(name, name) for name in store.busy)
        self.update(Text.assemble((FRAMES[self.frame], "bold"), " ", (what, "dim")))
