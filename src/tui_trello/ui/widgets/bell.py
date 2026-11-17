"""The unread-notification count in the top bar: blank when there are none; `4` opens the list."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static


class Bell(Static):
    """Goes in a `TopBar`, before the `Spinner`."""

    DEFAULT_CSS = """
    Bell { width: auto; height: 1; padding: 0 1; background: transparent; }
    """

    def on_mount(self) -> None:
        self.app.store.notifications_changed.subscribe(self, lambda _: self.redraw())
        self.redraw()

    def redraw(self) -> None:
        count = self.app.store.unread_count
        self.update(Text(f"● {count} unread", style="bold yellow") if count else "")
