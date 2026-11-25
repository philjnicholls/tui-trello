"""`N`: the news from tui-trello's repository (`remote/newsfeed.md`), newest first; opening it marks it all seen."""

from __future__ import annotations

from datetime import datetime

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from tui_trello.remote import NewsItem
from tui_trello.ui import markdown


class NewsScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    NewsScreen { align: center middle; }
    NewsScreen > VerticalScroll {
        width: 84; max-width: 95%; height: auto; max-height: 90%; border: round $accent; background: $surface;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape,q", "dismiss", "Close", id="news.close"),
        Binding("N", "dismiss", "Close", show=False, id="app.news"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.items: list[NewsItem] = []

    def compose(self) -> ComposeResult:
        remote = getattr(self.app, "remote", None)
        self.items = remote.news() if remote else []
        with VerticalScroll():
            yield Static(self.content(), id="news")

    def content(self) -> Table:
        """The text is fetched, so it is never read as markup (`Text`), and its links are not clickable."""
        table = Table.grid()
        table.add_column()
        table.add_row(Text("News about tui-trello", style="bold"))
        table.add_row("")
        for item in self.items:
            table.add_row(Text(f"{item.date:%Y-%m-%d}  {item.title}", style="bold yellow"))
            table.add_row(markdown.render(item.body, hyperlinks=False))
            table.add_row("")
        if not self.items:
            table.add_row(Text("No news."))
            table.add_row("")
        table.add_row(Text(self.footnote(), style="dim"))
        return table

    def footnote(self) -> str:
        remote = getattr(self.app, "remote", None)
        if remote is None:
            return "News is turned off ([remote] enabled = false, or --no-remote)."
        fetched = remote.last_fetched()
        return f"Last fetched {datetime.fromtimestamp(fetched):%Y-%m-%d %H:%M}." if fetched else "Not fetched yet."

    def on_mount(self) -> None:
        self.app.mark_news_seen([item.id for item in self.items])
