"""Behaviour shared by the screens.

- :class:`CardActionsScreen`: verbs on "the current card" (move, comment, description, labels, checklist, react to
  a comment, copy a link, open in browser). A new card feature
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

from rich.text import Text
from textual import on, work
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Input

from tui_trello.backend import BackendError
from tui_trello.models import REACTIONS, BoardSnapshot, Card, Comment
from tui_trello.query import CardQuery
from tui_trello.ui import clipboard
from tui_trello.ui.screens.picker import (
    ChecklistPickerScreen,
    Choice,
    LabelPickerScreen,
    PickerScreen,
    TextPromptScreen,
)


class TopBar(Horizontal):
    """The one-line bar at the top of every screen: a `Static` the screen writes its status in, a `Bell` (the unread
    notification count), then a `Spinner`, which is the app's only loading indicator."""

    DEFAULT_CSS = """
    TopBar { height: 1; background: $panel; }
    TopBar > Static { width: 1fr; padding: 0 1; }
    TopBar > Spinner, TopBar > Bell { width: auto; }
    """


FILTER_HELP = "words  #label  @member  list:name  !overdue  !due    enter: apply   esc: clear"


class CardActionsScreen(Screen):
    BINDINGS = [
        Binding("m", "move_card", "Move"),
        Binding("c", "comment", "Comment"),
        Binding("e", "edit_description", "Description"),
        Binding("t", "labels", "Labels"),
        Binding("x", "checklist", "Checklist"),
        Binding("R", "react", "React", show=False),
        Binding("y", "copy_link", "Copy link", show=False),
        Binding("Y", "copy_comment_link", "Copy comment link", show=False),
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
        store, board_id = self.app.store, card.board_id
        draft = store.draft("comment", card.id)
        text = await self.app.push_screen_wait(TextPromptScreen(
            f"Comment on “{card.name}”", mentions=lambda: store.members(board_id),
            text=draft.text if draft else "", notice="Your unsent comment" if draft else "",
            on_change=lambda text: store.save_draft("comment", card.id, text)))
        if not text:
            return
        try:
            await store.add_comment(card.id, text)
        except BackendError as exc:
            self.notify(f"{exc} The comment is kept as a draft: c to try again.", severity="error")
        else:
            store.save_draft("comment", card.id, "")
            self.notify("Comment added")

    @work
    async def action_edit_description(self) -> None:
        card = self.current_card()
        if not card:
            return
        store, board_id = self.app.store, card.board_id
        draft = store.draft("desc", card.id)
        base = draft.base if draft else card.desc  # the description the edit started from
        notice = ""
        if draft:
            notice = "Your unsaved edit"
            if draft.base != card.desc:
                notice += ". The description has changed on Trello since you started it; saving replaces that."

        def keep(text: str) -> None:
            store.save_draft("desc", card.id, "" if text == base else text, base=base)

        desc = await self.app.push_screen_wait(TextPromptScreen(
            f"Description of “{card.name}”", mentions=lambda: store.members(board_id), multiline=True,
            text=draft.text if draft else card.desc, notice=notice, on_change=keep))
        current = store.find_card(card.id) or card
        if desc is None:
            return
        if desc == current.desc:
            store.save_draft("desc", card.id, "")
            return
        try:
            await store.set_description(current, desc)
        except BackendError as exc:
            self.notify(f"{exc} The edit is kept as a draft: e to try again.", severity="error")
        else:
            store.save_draft("desc", card.id, "")
            self.notify("Description saved")

    def action_labels(self) -> None:
        if card := self.current_card():
            self.app.push_screen(LabelPickerScreen(card.id))

    def action_checklist(self) -> None:
        if card := self.current_card():
            self.app.push_screen(ChecklistPickerScreen(card.id))

    async def pick_comment(self, card: Card, title: str) -> Comment | None:
        """Choose one of the card's comments, newest first."""
        store = self.app.store
        try:
            comments = await store.comments(card.id)
            me_id = (await store.me()).id
        except BackendError as exc:
            self.notify(str(exc), severity="error")
            return None
        if not comments:
            self.notify("No comments on this card")
            return None
        choices = []
        for comment in comments:
            text = " ".join(comment.text.split())
            when = f"{comment.date:%d %b}" if comment.date else ""
            reactions = " ".join(f"{native}{n}" for _, native, n, _ in comment.reaction_counts(me_id))
            choices.append(Choice(f"{comment.author}: {text[:60]}{'…' if len(text) > 60 else ''}", comment,
                                  "  ".join(part for part in (when, reactions) if part)))
        return await self.app.push_screen_wait(PickerScreen(title, choices))

    @work
    async def action_react(self) -> None:
        card = self.current_card()
        if not card or not (comment := await self.pick_comment(card, "React to which comment?")):
            return
        me_id = self.app.store.me_id
        counts = {name: (n, mine) for name, _, n, mine in comment.reaction_counts(me_id)}
        offered = [(name, native, words) for name, native, words in REACTIONS]
        # Someone else's emoji that isn't on the list can still be added to, or taken off.
        offered += [(name, native, name.replace("_", " ")) for name, native, _, _ in comment.reaction_counts(me_id)
                    if all(name != o[0] for o in REACTIONS)]
        choices = []
        for name, native, words in offered:
            n, mine = counts.get(name, (0, False))
            hint = ", ".join(part for part in (f"{n}" if n else "", "yours: enter takes it off" if mine else "")
                             if part)
            choices.append(Choice(words, (name, native), hint, Text(f"{native}  ")))
        chosen = await self.app.push_screen_wait(PickerScreen(f"React to {comment.author}'s comment", choices))
        if not chosen:
            return
        name, native = chosen
        try:
            await self.app.store.toggle_reaction(card.id, comment, name, native)
        except BackendError as exc:
            self.notify(str(exc), severity="error")

    def copy(self, url: str, what: str) -> None:
        clipboard.copy(url, self.app.copy_to_clipboard)
        self.notify(url, title=f"Copied the link to {what}")

    def action_copy_link(self) -> None:
        if (card := self.current_card()) and card.url:
            self.copy(card.url, "the card")

    @work
    async def action_copy_comment_link(self) -> None:
        card = self.current_card()
        if card and card.url and (comment := await self.pick_comment(card, "Copy the link to which comment?")):
            self.copy(card.comment_url(comment.id), f"{comment.author}'s comment")

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
        self.app.store.notifications_changed.subscribe(self, lambda _: self.redraw())
        if self.snapshot:
            self.redraw()

    @property
    def snapshot(self) -> BoardSnapshot | None:
        return self.app.store.snapshot
