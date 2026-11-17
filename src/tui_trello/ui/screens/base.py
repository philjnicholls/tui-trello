"""Behaviour shared by the screens.

- :class:`CardActionsScreen`: verbs on "the current card" (move, comment, labels, checklist, open in browser). A new card feature
  (archive, assign, label, due date, ...) is added here once, as a binding plus an action, and works in every view.
  Subclasses only say which card is current.
- :class:`ListScreen`: a card list with a `/` filter bar using the query language in `tui_trello.query`.
- :class:`BoardScreen`: a list screen drawing the open board, redrawn whenever the store says it changed.

Textual calls `on_mount` on every class in the MRO (subclass first), so subclasses don't call `super().on_mount()`.

Motions (j, k, gg, G, ctrl+d, ctrl+u) are app-wide, in `tui_trello.ui.app`; screens only bind h and l, whose
meaning ("back out", "go in") depends on the layout.
"""

from __future__ import annotations

import webbrowser

from textual import on, work
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Input

from tui_trello.backend import BackendError
from tui_trello.models import BoardSnapshot, Card
from tui_trello.query import CardQuery
from tui_trello.ui.screens.picker import (
    ChecklistPickerScreen,
    Choice,
    LabelPickerScreen,
    PickerScreen,
    TextPromptScreen,
)


class TopBar(Horizontal):
    """The one-line bar at the top of every screen: a `Static` the screen writes its status in, then a `Spinner`,
    which is the app's only loading indicator."""

    DEFAULT_CSS = """
    TopBar { height: 1; background: $panel; }
    TopBar > Static { width: 1fr; padding: 0 1; }
    TopBar > Spinner { width: auto; }
    """


FILTER_HELP = "words  #label  @member  list:name  !overdue  !due    enter: apply   esc: clear"


class CardActionsScreen(Screen):
    BINDINGS = [
        Binding("m", "move_card", "Move"),
        Binding("c", "comment", "Comment"),
        Binding("t", "labels", "Labels"),
        Binding("x", "checklist", "Checklist"),
        Binding("o", "open_in_browser", "Open in browser", show=False),
    ]

    def current_card(self) -> Card | None:
        raise NotImplementedError

    def open_card(self) -> None:
        from tui_trello.ui.screens.card import CardScreen

        if card := self.current_card():
            self.app.push_screen(CardScreen(card.id))

    @work
    async def action_move_card(self) -> None:
        card = self.current_card()
        context = self.app.store.context_for(card.id) if card else None
        if not (card and context):
            return
        lists = context.lists_for(card)
        choices = [Choice(lst.name, lst.id, "current" if lst.id == card.list_id else "") for lst in lists]
        list_id = await self.app.push_screen_wait(PickerScreen(f"Move “{card.name}” to…", choices))
        if list_id is None or list_id == card.list_id:
            return
        try:
            await self.app.store.move_card(card, list_id)
        except BackendError as exc:
            self.notify(str(exc), severity="error")
        else:
            self.notify(f"Moved to {next(lst.name for lst in lists if lst.id == list_id)}")

    @work
    async def action_comment(self) -> None:
        card = self.current_card()
        if not card:
            return
        board_id = card.board_id
        text = await self.app.push_screen_wait(
            TextPromptScreen(f"Comment on “{card.name}”", mentions=lambda: self.app.store.members(board_id)))
        if not text:
            return
        try:
            await self.app.store.add_comment(card.id, text)
        except BackendError as exc:
            self.notify(str(exc), severity="error")
        else:
            self.notify("Comment added")

    def action_labels(self) -> None:
        if card := self.current_card():
            self.app.push_screen(LabelPickerScreen(card.id))

    def action_checklist(self) -> None:
        if card := self.current_card():
            self.app.push_screen(ChecklistPickerScreen(card.id))

    def action_open_in_browser(self) -> None:
        if (card := self.current_card()) and card.url:
            webbrowser.open(card.url)


class ListScreen(CardActionsScreen):
    """A screen listing cards. Compose a `TopBar`, an `Input(id="filter")` and the list; implement `redraw()` and
    `focus_list()`."""

    DEFAULT_CSS = """
    ListScreen #filter { display: none; border: none; height: 1; padding: 0 1; background: $boost; }
    ListScreen #filter.visible { display: block; }
    ListScreen #filter:focus { border: none; }
    """

    BINDINGS = [Binding("slash", "filter", "Filter")]

    def __init__(self) -> None:
        super().__init__()
        self.query_text = ""

    @property
    def card_query(self) -> CardQuery:
        return CardQuery.parse(self.query_text)

    def redraw(self) -> None:
        raise NotImplementedError

    def focus_list(self) -> None:
        raise NotImplementedError

    def action_filter(self) -> None:
        box = self.query_one("#filter", Input)
        box.add_class("visible")
        box.focus()

    @on(Input.Changed, "#filter")
    def on_filter_changed(self, event: Input.Changed) -> None:
        self.query_text = event.value
        self.redraw()

    @on(Input.Submitted, "#filter")
    def on_filter_submitted(self) -> None:
        if not self.query_text:
            self.query_one("#filter", Input).remove_class("visible")
        self.focus_list()

    def key_escape(self) -> None:
        """Esc clears the filter, from the filter bar or from the list."""
        box = self.query_one("#filter", Input)
        if box.value or box.has_focus:
            box.value = ""
            box.remove_class("visible")
            self.focus_list()


class BoardScreen(ListScreen):
    """A list screen showing the open board."""


    def on_mount(self) -> None:
        self.app.store.board_changed.subscribe(self, lambda _: self.redraw())
        if self.snapshot:
            self.redraw()

    @property
    def snapshot(self) -> BoardSnapshot | None:
        return self.app.store.snapshot
