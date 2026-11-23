"""Behaviour shared by the screens.

- :class:`CardActionsScreen`: verbs on "the current card" (move, comment, description, labels, checklist,
  attachments, reply or react to a comment, copy a link, open in browser). A new card feature
  (archive, assign, label, due date, ...) is added here once, as a binding plus an action, and works in every view.
  Subclasses only say which card is current.
- :class:`ListScreen`: a card list with a `/` filter bar using the query language in `tui_trello.query`, and `n`
  to make a new card: subclasses say which list it goes on and put the cursor on it once made.
- :class:`BoardScreen`: a list screen drawing the open board, redrawn whenever the store says it changed.

Textual calls `on_mount` on every class in the MRO (subclass first), so subclasses don't call `super().on_mount()`.

Motions (j, k, gg, G, ctrl+d, ctrl+u) are app-wide, in `tui_trello.ui.app`; screens only bind h and l, whose
meaning ("back out", "go in") depends on the layout.
"""

from __future__ import annotations

import re
import webbrowser
from pathlib import Path

from rich.cells import cell_len
from rich.text import Text
from textual import on, work
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Input

from tui_trello import quote
from tui_trello.backend import BackendError
from tui_trello.emoji import with_emoji
from tui_trello.models import REACTIONS, BoardSnapshot, Card, CardList, Comment
from tui_trello.query import CardQuery
from tui_trello.store import NewCardDraft
from tui_trello.ui import clipboard, markdown
from tui_trello.ui.bidi import cut
from tui_trello.ui.screens.picker import (
    AttachmentPickerScreen,
    ChecklistPickerScreen,
    Choice,
    LabelPickerScreen,
    LinkPickerScreen,
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


COMMENT_LABEL = 60  # terminal cells of a comment, or of a part of one, shown (and matched) in a picker
FILTER_HELP = "words  #label  @member  list:name  !overdue  !due    enter: apply   esc: clear"


class CardActionsScreen(Screen):
    BINDINGS = [
        Binding("m", "move_card", "Move"),
        Binding("c", "comment", "Comment"),
        Binding("e", "edit_description", "Description"),
        Binding("t", "labels", "Labels"),
        Binding("x", "checklist", "Checklist"),
        Binding("a", "attachments", "Attachments", show=False),
        Binding("C", "reply", "Reply", show=False),
        Binding("R", "react", "React", show=False),
        Binding("y", "copy_link", "Copy link", show=False),
        Binding("Y", "copy_comment_link", "Copy comment link", show=False),
        Binding("o", "open_in_browser", "Open in browser", show=False),
        Binding("L", "follow_link", "Follow link", show=False),
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
        choices = [Choice(with_emoji(lst.name), lst.id, "current" if lst.id == card.list_id else "", search=lst.name)
                   for lst in lists]
        list_id = await self.app.push_screen_wait(PickerScreen(f"Move “{with_emoji(card.name)}” to…", choices))
        if list_id is None or list_id == card.list_id:
            return
        try:
            await self.app.store.move_card(card, list_id)
        except BackendError as exc:
            self.notify(str(exc), severity="error")
        else:
            self.notify(f"Moved to {with_emoji(next(lst.name for lst in lists if lst.id == list_id))}")

    @work
    async def action_comment(self) -> None:
        if card := self.current_card():
            await write_comment(self, card.id, card.board_id, f"Comment on “{with_emoji(card.name)}”")

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
            f"Description of “{with_emoji(card.name)}”", mentions=lambda: store.members(board_id), multiline=True,
            text=draft.text if draft else card.desc, notice=notice, on_change=keep,
            attach=lambda path: attach_for_text(self, card.id, path)))
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

    def action_attachments(self) -> None:
        if card := self.current_card():
            self.app.push_screen(AttachmentPickerScreen(card.id))

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
            when = f"{comment.date:%d %b}" if comment.date else ""
            reactions = " ".join(f"{native}{n}" for _, native, n, _ in comment.reaction_counts(me_id))
            shown, search = label_and_search(comment.text)
            choices.append(Choice(f"{comment.author}: {shown}", comment,
                                  "  ".join(part for part in (when, reactions) if part),
                                  search=f"{comment.author}: {search}"))
        return await self.app.push_screen_wait(PickerScreen(title, choices))

    @work
    async def action_reply(self) -> None:
        card = self.current_card()
        if not card or not (comment := await self.pick_comment(card, "Reply to which comment?")):
            return
        await reply_to(self, card.id, card.name, card.board_id, comment.author, comment.author_username, comment.text)

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

    @work
    async def action_follow_link(self) -> None:
        """Pick one of the links in the card's text and follow it."""
        # Imported here: follow imports the card screen, which imports this module.
        from tui_trello.ui import follow

        if not (card := self.current_card()):
            return
        try:
            choices = await follow.link_choices(self.app, card)
        except BackendError as exc:
            self.notify(str(exc), severity="error")
            return
        if not choices:
            self.notify("No links on this card")
        elif url := await self.app.push_screen_wait(LinkPickerScreen(card, choices)):
            self.app.action_follow_link(url)  # a worker of the app's: this screen may be popped by the link


def label_and_search(source: str, full: bool = False) -> tuple[str, str]:
    """What a picker shows of some Markdown text, and what it matches: the text as rendered, on one line and cut to
    `COMMENT_LABEL` cells unless `full`; and the same text as stored when that is as short (so a shortcode's name
    finds its emoji), else the rendered text cut to `COMMENT_LABEL`. Fuzzy matching is exponential in the query's
    repeated letters, so it never sees more than that."""
    shown = " ".join(markdown.plain(source).split())
    cut_label = cut(shown, COMMENT_LABEL)
    stored = " ".join(source.split())
    return shown if full else cut_label, stored if cell_len(stored) <= COMMENT_LABEL else cut_label


async def write_comment(screen: Screen, card_id: str, board_id: str, title: str, start: str = "") -> None:
    """Open the comment editor on the card's draft, with `start` (a reply's quote) after it, and send it. The card
    needn't be on a loaded board (a reply from Notifications)."""
    store = screen.app.store
    draft = store.draft("comment", card_id)
    text = "\n\n".join(part for part in (draft.text.rstrip() if draft else "", start) if part)
    text = await screen.app.push_screen_wait(TextPromptScreen(
        title, mentions=lambda: store.members(board_id),
        text=text, notice="Your unsent comment" if draft else "",
        on_change=lambda text: store.save_draft("comment", card_id, text),
        attach=lambda path: attach_for_text(screen, card_id, path)))
    if not text:
        return
    try:
        await store.add_comment(card_id, text)
    except BackendError as exc:
        screen.notify(f"{exc} The comment is kept as a draft: c to try again.", severity="error")
    else:
        store.save_draft("comment", card_id, "")
        screen.notify("Comment added")


async def reply_to(screen: Screen, card_id: str, card_name: str, board_id: str, author: str, username: str,
                   text: str) -> None:
    """Write a comment quoting `author`'s comment `text` and mentioning them. A long one isn't quoted whole: the
    user picks its start, cut short, or one of its parts."""
    text = quote.own_text(text)
    quoted = text
    if not quote.fits(text):
        start = quote.shorten(text)
        label, search = label_and_search(start, full=True)
        choices = [Choice(label, start, "the start", search=search, search_only=True)]
        for part in quote.parts(text):
            if part != start:
                label, search = label_and_search(part, full=True)
                choices.append(Choice(label, part, search=search, search_only=True))
        quoted = await screen.app.push_screen_wait(PickerScreen(f"{author}'s comment is long: quote which part?",
                                                                choices))
        if quoted is None:
            return
    await write_comment(screen, card_id, board_id, f"Reply to {author} on “{with_emoji(card_name)}”",
                        quote.reply(quoted, username))


async def attach_for_text(screen: Screen, card_id: str, path: Path) -> str:
    """Upload the file to the card, as trello.com does for a file added to a comment, and return a Markdown link to
    it."""
    attachment = await screen.app.store.attach_file(card_id, path)
    screen.notify(f"Attached {attachment.name} to the card")
    name = attachment.name.replace("[", "(").replace("]", ")")
    return f"[{name}]({attachment.url})"


def split_card_text(text: str) -> tuple[str, str]:
    """A new card's box's text as the card's name (its first line, on one line) and description (the lines after it,
    without blank lines at either end)."""
    name, _, desc = text.partition("\n")
    return " ".join(name.split()), re.sub(r"\A\s*\n|\n\s*\Z", "", desc) if desc.strip() else ""


def index_of(cards: list[Card], card_id: str) -> int | None:
    """Where the card is in the list of cards a view shows, if it is."""
    return next((i for i, card in enumerate(cards) if card.id == card_id), None)


class ListScreen(CardActionsScreen):
    """A screen listing cards. Compose a `TopBar`, an `Input(id="filter")` and the list; implement `redraw()`,
    `focus_list()`, `new_card_list()` and `select_card()`."""

    DEFAULT_CSS = """
    ListScreen #filter { display: none; border: none; height: 1; padding: 0 1; background: $boost; }
    ListScreen #filter.visible { display: block; }
    ListScreen #filter:focus { border: none; }
    """

    BINDINGS = [
        Binding("slash", "filter", "Filter"),
        Binding("n", "new_card", "New card"),
    ]

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

    async def new_card_list(self) -> CardList | None:
        """The list `n` makes a card on, asking if need be; None (having said why, if it isn't obvious) for none."""
        raise NotImplementedError

    def select_card(self, card_id: str) -> None:
        """Put the cursor on the card, if the view shows it."""
        raise NotImplementedError

    def place(self) -> tuple[object, ...]:
        """Where the user is: a new card is selected once made only if they haven't moved on meanwhile."""
        card = self.current_card()
        return self.app.screen, self.focused, card.id if card else None

    def list_label(self, card_list: CardList) -> str:
        return with_emoji(card_list.name)

    def new_card_toast(self, card: Card, card_list: CardList) -> str:
        return f"Added “{with_emoji(card.name)}” to {self.list_label(card_list)}"

    async def pick_list(self, title: str, choices: list[Choice[CardList]]) -> CardList | None:
        return await self.app.push_screen_wait(PickerScreen(title, choices))

    def new_card_notice(self, card_list: CardList, box: NewCardDraft) -> str:
        """Why a new card's box starts with text, if it does."""
        if not (draft := box.draft):
            return ""
        of = f" (1 of {box.free})" if box.free > 1 else ""
        if not draft.sent:
            return f"Your unsent card{of}"
        # Sent before, with no answer: Trello may have made it, and a resend would make a second.
        name, _ = split_card_text(draft.text)
        snapshot = self.app.store.snapshot
        if name and snapshot and any(card.name == name for card in snapshot.cards_in(card_list.id)):
            return (f"This card may already have been made on Trello: “{with_emoji(name)}” is on "
                    f"{with_emoji(card_list.name)} already; check before sending{of}")
        return f"This card may already have been made on Trello: check before sending{of}"

    @work
    async def action_new_card(self) -> None:
        """Ask for the card's name, and its description on the lines after it, and make it at the bottom of the
        list. The box's text is a draft of its own until Trello has made the card (see `Store.new_card_box`)."""
        place = self.place()
        if not (card_list := await self.new_card_list()):
            return
        store = self.app.store
        with store.new_card_box(card_list.id) as box:
            text = await self.app.push_screen_wait(TextPromptScreen(
                f"New card in “{with_emoji(card_list.name)}”", text=box.draft.text if box.draft else "",
                notice=self.new_card_notice(card_list, box), hint="the lines after the first are the description",
                on_change=lambda text: store.save_draft("card", box.id, text), strip=False))
        if not text:
            return
        name, desc = split_card_text(text)
        if not name:
            self.notify("A card needs a name on the first line", severity="warning")
            return
        try:
            card = await store.create_card(card_list, name, desc, draft=box.id)
        except BackendError as exc:
            if exc.unsure:
                self.notify(f"{exc} The card may have been made on Trello anyway: check before sending it again (n).",
                            severity="error")
            else:
                self.notify(f"{exc} The card is kept as a draft: n to try again.", severity="error")
            return
        here = self.place() == place
        # The screens subscribe to the store's signals without `immediate`, so publishing queued this screen's
        # redraw with `call_next`; queueing the selection the same way runs it after the redraw.
        def show() -> None:
            if here:
                self.select_card(card.id)
            self.notify(self.new_card_toast(card, card_list))

        self.call_next(show)

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

    BINDINGS = [
        Binding("B", "copy_board_link", "Copy board link", show=False),
    ]


    def on_mount(self) -> None:
        self.app.store.board_changed.subscribe(self, lambda _: self.redraw())
        self.app.store.notifications_changed.subscribe(self, lambda _: self.redraw())
        if self.snapshot:
            self.redraw()

    @property
    def snapshot(self) -> BoardSnapshot | None:
        return self.app.store.snapshot

    def new_card_toast(self, card: Card, card_list: CardList) -> str:
        toast = super().new_card_toast(card, card_list)
        snapshot = self.snapshot
        if snapshot and snapshot.board.id == card.board_id and not self.card_query.matches(card, snapshot):
            toast += " (hidden by the filter; esc clears it)"  # only on the board on screen
        return toast

    def board_lists(self) -> list[CardList]:
        """The open board's lists, for a new card; none, having said why, if no board is open or it has none."""
        if not self.snapshot:
            self.notify("Open a board first (b)")
            return []
        if not self.snapshot.lists:
            self.notify("This board has no lists")
        return self.snapshot.lists

    def action_copy_board_link(self) -> None:
        if self.snapshot and self.snapshot.board.url:
            self.copy(self.snapshot.board.url, "the board")
