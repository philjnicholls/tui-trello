"""`/`: search every board on Trello, archived cards too. Trello does the matching, a moment after typing stops."""

from __future__ import annotations

from rich.text import Text
from textual import work
from textual.binding import Binding
from textual.timer import Timer
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from tui_trello.backend import BackendError
from tui_trello.emoji import with_emoji
from tui_trello.models import CardPreview
from tui_trello.ui.screens.picker import Choice, PickerScreen

ARCHIVED = {"card": "archived", "list": "list archived", "board": "board closed"}


class SearchScreen(PickerScreen[str]):
    """Type to search; enter on an open card dismisses with its URL, for the app to go to (loading its board if need
    be); on an archived one, which no loaded board has, it opens the preview. alt+p previews any result, and esc in
    the preview comes back here with the query and results as they were."""

    HINT = ("enter: open · {popup.preview}: preview · archived cards too · Trello's search terms work: "
            "board: label: is:open")
    PLACEHOLDER = "Search every board…"

    BINDINGS = [
        # priority: a terminal sends alt+p as ESC then p, which reaches the filter box as a printable `p` that it
        # would type instead of letting the screen's binding see it.
        Binding("alt+p", "preview", "Preview", show=False, priority=True, id="popup.preview"),
    ]

    SEARCH_DELAY = 0.4  # seconds after the last key before the search is made
    MIN_QUERY = 2  # characters

    def __init__(self) -> None:
        super().__init__("Search Trello", [])
        self.asked = ""  # the query the results (or the search under way) are for
        self.timer: Timer | None = None
        self.searching = False
        self.failure = ""  # why the last search failed, if it did

    def refilter(self) -> None:
        """Trello did the matching, so show what it found as it is, or one line on where the search stands. A changed
        query clears the results and starts the pause before searching."""
        query = self.query_text.strip()
        if query != self.asked:
            self.asked = query
            self.choices = []
            self.failure = ""
            if self.timer:
                self.timer.stop()
                self.timer = None
            self.workers.cancel_group(self, "search")
            self.searching = len(query) >= self.MIN_QUERY
            if self.searching:
                self.timer = self.set_timer(self.SEARCH_DELAY, lambda: self.search(query))
        options = self.query_one(OptionList)
        self.shown = list(self.choices)
        if self.shown:
            options.set_options([self.option(c.label, c) for c in self.shown])
            options.highlighted = 0
            return
        if len(query) < self.MIN_QUERY:
            status = "Type to search every board (archived cards too)"
        else:
            status = ("Searching…" if self.searching else f"Search failed: {self.failure}" if self.failure
                      else "No cards match")
        options.set_options([Option(Text(status, style="dim"), disabled=True)])
        options.highlighted = None

    @work(exclusive=True, group="search")
    async def search(self, query: str) -> None:
        try:
            hits = await self.app.store.search_cards(query)
        except BackendError as exc:
            self.notify(str(exc), severity="error", markup=False)
            hits, failure = [], str(exc)
        else:
            failure = ""
        if query != self.asked:  # typing went on meanwhile
            return
        self.searching = False
        self.failure = failure
        self.choices = [self.choice(hit) for hit in hits]
        self.refilter()

    @staticmethod
    def choice(hit: CardPreview) -> Choice[CardPreview]:
        hint = hit.location + (f" · {ARCHIVED[hit.archived]}" if hit.archived else "")
        return Choice(with_emoji(hit.card.name), hit, hint, Text("🗄 " if hit.archived else "🃏 "),
                      search=hit.card.name)

    def highlighted(self) -> CardPreview | None:
        highlighted = self.query_one(OptionList).highlighted
        return self.shown[highlighted].value if highlighted is not None and highlighted < len(self.shown) else None

    def choose(self, choice: Choice[CardPreview]) -> None:
        if choice.value.archived:
            self.action_preview()  # no loaded board has it: it can only be previewed
        else:
            self.dismiss(choice.value.card.url)

    @work
    async def action_preview(self) -> None:
        """Preview the highlighted card on top of this list. Esc there comes back here as it was; enter follows the
        card, ctrl+o opens it in the browser (this popup closes either way)."""
        if not (hit := self.highlighted()):
            return
        if (result := await self.app.preview_link(hit.card.url, hit.location)) is not None:
            self.dismiss(result or None)  # "" if it went to the web browser
