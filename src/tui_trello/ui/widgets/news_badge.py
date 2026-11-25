"""The unseen-news count in the top bar, beside the bell: blank when there is none; `N` opens the news."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from tui_trello.ui import keymap


class NewsBadge(Static):
    """Goes in a `TopBar`, after the `Bell`."""

    DEFAULT_CSS = """
    NewsBadge { width: auto; height: 1; padding: 0 1; background: transparent; }
    """

    def on_mount(self) -> None:
        news_changed = getattr(self.app, "news_changed", None)  # a bare App in tests has none
        if news_changed is not None:
            news_changed.subscribe(self, lambda _: self.redraw())
        self.redraw()

    def redraw(self) -> None:
        count = len(getattr(self.app, "unseen_news", ()))
        key = keymap.of(self.app).fill("{app.news}")
        self.update(Text(f"✦ {count} news ({key})", style="bold magenta") if count else "")
