"""A card's details: header, description, attachments, checklists and comments. Used as the browser's preview pane
and the card screen. Ticked checklist items are hidden, with a count, until `X` shows them. With no card to show, it
shows a tip on using the app instead, a new one every so often."""

from __future__ import annotations

import random

from rich.console import Group, RenderableType
from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from tui_trello.backend import BackendError
from tui_trello.emoji import with_emoji
from tui_trello.models import (
    Attachment,
    Card,
    CardContext,
    CheckItem,
    Checklist,
    Comment,
)
from tui_trello.ui import markdown, render
from tui_trello.ui.bidi import BidiText, visual
from tui_trello.ui.screens.picker import attachment_hint, attachment_marker
from tui_trello.ui.tips import TIPS


class CardView(VerticalScroll):
    DEFAULT_CSS = """
    CardView { padding: 0 1; }
    CardView #card-title { text-style: bold; color: $accent; margin-bottom: 1; }
    CardView #card-meta { margin-bottom: 1; }
    CardView .section { text-style: bold; color: $text-muted; border-bottom: solid $panel-lighten-2; }
    CardView #card-desc { margin-bottom: 1; }
    CardView #card-comments { height: auto; margin-bottom: 1; min-height: 1; }
    CardView .comment.target { border-left: thick $accent; padding-left: 1; }
    CardView .checklists, CardView .attachments { display: none; }
    CardView .checklists.visible, CardView .attachments.visible { display: block; }
    CardView #card-attachments { margin-bottom: 1; }
    CardView #card-checklists { margin-bottom: 1; }
    CardView #card-body { height: auto; }
    CardView #card-tip { display: none; padding: 1 0; }
    CardView.empty #card-body { display: none; }
    CardView.empty #card-tip { display: block; }
    """

    KEY_HINTS = True  # name the keys that act on the card (x, a, c, e) in its hints; a read-only view names none
    TIP_SECONDS = 15
    REACTORS_SHOWN = 3  # names under a comment's emoji; more than this shows a count
    MISSING_COMMENT = ("That comment isn't on the card any more, or is older than the 50 shown; o opens the card on "
                       "trello.com")

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id, classes="empty")
        self.card: Card | None = None
        self.context: CardContext | None = None
        self.checklists: list[Checklist] | None = None  # as last drawn; None while they load or after an error
        self.target_comment = ""  # the comment a followed link points to: marked, and scrolled to once
        self.scroll_pending = False
        self.comments_shown = False  # the card's comments are in `#card-comments` (not an error or still loading)
        self.comments_card = ""  # the card whose comments `#card-comments` holds
        self.sections_loading: set[str] = set()  # attachments, checklists: above the comments, so they move them
        self.tip = random.randrange(len(TIPS))

    def on_mount(self) -> None:
        self.show_tip()
        self.set_interval(self.TIP_SECONDS, self.next_tip)
        self.app.store.drafts_changed.subscribe(self, self.on_draft_changed)
        self.app.store.notifications_changed.subscribe(self, lambda _: self.on_notifications_changed())
        self.app.store.comments_changed.subscribe(self, self.on_comments_changed)
        self.app.done_check_items_toggled.subscribe(self, lambda _: self.redraw_checklists())

    def on_comments_changed(self, card_id: str) -> None:
        if self.card and self.card.id == card_id:
            self.load_comments(self.card)

    def on_notifications_changed(self) -> None:
        if self.card and self.context:
            self.show_meta(self.card, self.context)

    def on_draft_changed(self, card_id: str) -> None:
        if self.card and self.context and self.card.id == card_id:
            self.show_meta(self.card, self.context)

    def compose(self) -> ComposeResult:
        yield Static(id="card-tip")
        with Vertical(id="card-body"):
            yield Static(id="card-title")
            yield Static(id="card-meta")
            yield Static("Description", classes="section")
            yield Static(id="card-desc")
            yield Static("Attachments", classes="section attachments")
            yield Static(id="card-attachments", classes="attachments")
            yield Static("Checklists", classes="section checklists")
            yield Static(id="card-checklists", classes="checklists")
            yield Static("Comments", classes="section")
            yield Vertical(id="card-comments")

    def show_tip(self) -> None:
        self.query_one("#card-tip", Static).update(Group(
            Text("No card here yet.", style="dim"), Text(""),
            Text.assemble(("💡 Tip", "bold"), (f"  {self.tip + 1}/{len(TIPS)}", "dim")),
            markdown.inline(TIPS[self.tip]),
        ))

    def next_tip(self) -> None:
        if self.has_class("empty"):
            self.tip = (self.tip + 1) % len(TIPS)
            self.show_tip()

    def show(self, card: Card | None, context: CardContext, comment_id: str = "") -> None:
        """Draw the card. With `comment_id`, mark that comment and scroll to it once the comments are in."""
        same_card = card is not None and self.card is not None and card.id == self.card.id
        if not same_card:
            self.target_comment, self.scroll_pending = "", False
        self.card, self.context = card, context
        self.comments_shown = False
        self.sections_loading = set()
        if comment_id and comment_id != self.target_comment:
            self.target_comment, self.scroll_pending = comment_id, True
        if not same_card:  # a redraw of the card keeps the view where it is
            self.scroll_home(animate=False)
        self.set_class(card is None, "empty")
        if card is None:
            return
        self.query_one("#card-title", Static).update(BidiText(with_emoji(card.name)))
        self.show_meta(card, context)
        self.show_description(card.desc)
        self.load_comments(card)  # clears the comments of another card; the top bar's spinner shows it loading
        if card.attachment_count or self.app.store.has_attachments(card.id):
            self.sections_loading.add("attachments")
            self.load_attachments(card)
        else:
            self.show_attachments([])
        self.checklists = None
        if card.checklist[1] or self.app.store.has_checklists(card.id):
            self.sections_loading.add("checklists")
            self.load_checklists(card)
        else:
            self.show_checklists([])

    def show_meta(self, card: Card, context: CardContext) -> None:
        meta = Text.assemble(
            ("in ", "dim"), visual(Text(with_emoji(context.location(card)), style="bold")), "  ",
            render.badges(card, unread=self.app.store.unread_by_card()[card.id]), "\n",
        )
        names = [context.members[m].full_name for m in card.member_ids if m in context.members]
        if names:
            meta.append_text(Text.assemble(("👤 ", "dim"), Text(", ", style="cyan").join(
                visual(Text(name, style="cyan")) for name in names), "\n"))
        meta.append_text(render.label_chips(card.labels))
        drafts = {"comment": ("c: ", "unsent comment"), "desc": ("e: ", "unsaved description")}
        for kind in self.app.store.drafts.kinds(card.id):
            key, what = drafts[kind]
            meta.append_text(Text.assemble("\n", ("✐ draft", "bold yellow"),
                                           (f"  {key if self.KEY_HINTS else ''}{what}", "yellow")))
        self.query_one("#card-meta", Static).update(meta)

    def show_description(self, desc: str) -> None:
        self.query_one("#card-desc", Static).update(
            markdown.render(desc, clickable=True) if desc.strip() else Text("No description.", style="dim italic"))

    def show_checklists(self, checklists: list[Checklist]) -> None:
        """Each checklist's heading and its items; the ticked ones only once `X` has shown them."""
        self.checklists = checklists
        shown = self.app.prefs.show_done_check_items
        self.query(".checklists").set_class(bool(checklists), "visible")
        parts: list[RenderableType] = []
        for checklist in checklists:
            done = checklist.done == len(checklist.items) and checklist.items
            parts.append(BidiText(Text.assemble(
                markdown.inline(checklist.name, Style(bold=True)), "  ",
                (f"☑ {checklist.done}/{len(checklist.items)}", "green" if done else "dim"))))
            parts += [self.item_line(item) for item in checklist.items if shown or not item.checked]
            if not shown and checklist.done:
                parts.append(Text(f"{checklist.done} done hidden", style="dim italic"))
            parts.append(Text(""))
        hints = []
        if any(checklist.done for checklist in checklists):
            hints.append(f"X: {'hide' if shown else 'show'} done items")
        if self.KEY_HINTS:
            hints.append("x: tick or add")
        hint = "   ".join(hints)
        parts[-1:] = [Text(hint, style="dim")] if checklists and hint else []
        self.query_one("#card-checklists", Static).update(Group(*parts))

    @staticmethod
    def item_line(item: CheckItem) -> BidiText:
        return BidiText(
            Text.assemble(("☑ ", "green"), markdown.inline(item.name, Style(dim=True, strike=True), clickable=True))
            if item.checked else Text.assemble(("☐ ", "dim"), markdown.inline(item.name, clickable=True)))

    def redraw_checklists(self) -> None:
        """After `X`: the same checklists again, without scrolling, so the reader keeps their place."""
        if self.card is not None and self.checklists is not None:
            self.show_checklists(self.checklists)

    def show_attachments(self, attachments: list[Attachment]) -> None:
        self.query(".attachments").set_class(bool(attachments), "visible")
        rows = [Text.assemble(attachment_marker(a), visual(with_emoji(a.name)), ("  " + attachment_hint(a), "dim"))
                for a in attachments]
        if rows and self.KEY_HINTS:
            rows.append(Text("a: open, save or add", style="dim"))
        self.query_one("#card-attachments", Static).update(Group(*rows))

    @work(exclusive=True, group="attachments")
    async def load_attachments(self, card: Card) -> None:
        def failed(exc: BackendError) -> None:
            self.query(".attachments").add_class("visible")
            self.query_one("#card-attachments", Static).update(Text(str(exc), style="red"))

        await self.load_section("attachments", card, self.app.store.attachments, self.show_attachments, failed)

    @work(exclusive=True, group="checklists")
    async def load_checklists(self, card: Card) -> None:
        def failed(exc: BackendError) -> None:
            self.checklists = None
            self.query(".checklists").add_class("visible")
            self.query_one("#card-checklists", Static).update(Text(str(exc), style="red"))

        await self.load_section("checklists", card, self.app.store.checklists, self.show_checklists, failed)

    async def load_section(self, name: str, card: Card, fetch, show, on_error) -> None:
        """Fetch a section above the comments and draw it, or say why it failed, and then release the hold it has on
        the scroll to a comment. A cancelled load doesn't release: the worker that cancelled it is a new load of the
        section, which took the hold again."""
        try:
            result = await fetch(card.id)
        except BackendError as exc:
            on_error(exc)
        else:
            if self.card is not None and self.card.id == card.id:
                show(result)
        self.section_loaded(name, card)

    def section_loaded(self, name: str, card: Card) -> None:
        """A section above the comments is in; with all of them in, a pending scroll to a comment can be done."""
        if self.card is None or self.card.id != card.id:
            return
        self.sections_loading.discard(name)
        if self.comments_shown:
            self.mark_target()

    @work(exclusive=True, group="comments")
    async def load_comments(self, card: Card, refresh: bool = False) -> None:
        widgets: list[Static]
        container = self.query_one("#card-comments", Vertical)
        if self.comments_card != card.id:  # another card's comments: out before the diff, which waits for it
            await container.remove_children()
            self.comments_card = card.id
        try:
            comments = await self.app.store.comments(card.id, refresh=refresh)
            me_id = (await self.app.store.me()).id
        except BackendError as exc:
            widgets = [Static(Text(str(exc), style="red"))]
            comments = None
        else:
            if self.card is None or self.card.id != card.id:
                return  # the user has moved on
            widgets = [Static(self.comment_body(comment, me_id), id=f"comment-{comment.id}", classes="comment")
                       for comment in comments]
            if not widgets:
                widgets = [Static(Text("No comments.", style="dim"))]
        await self.show_comment_widgets(widgets, comments is not None)
        self.comments_shown = comments is not None
        if self.comments_shown:
            self.mark_target()

    async def show_comment_widgets(self, widgets: list[Static], real: bool) -> None:
        """Put the widgets in `#card-comments`. Real comments are matched to the ones shown by id, updated in place,
        with only the new ones mounted and the gone ones removed, so that a reload (a reaction, a new comment)
        doesn't collapse the container and move the view. A message (an error, "No comments.") replaces them all."""
        container = self.query_one("#card-comments", Vertical)
        if not real:
            await container.remove_children()
            await container.mount_all(widgets)
            return
        wanted = {w.id for w in widgets}
        shown = {w.id: w for w in container.children if w.id in wanted}
        await container.remove_children([w for w in container.children if w.id not in wanted])
        if not shown:
            await container.mount_all(widgets)
            return
        for index, widget in enumerate(widgets):
            if current := shown.get(widget.id):
                current.update(widget.content)
            else:
                await container.mount(widget, before=index if index < len(container.children) else None)

    def comment_body(self, comment: Comment, me_id: str) -> Group:
        when = f"{comment.date:%d %b %H:%M}" if comment.date else ""
        parts: list[RenderableType] = [
            Text.assemble(("● ", "magenta"), visual(Text(comment.author, style="bold")), "  ", (when, "dim")),
            markdown.render(comment.text, clickable=True)]
        if counts := comment.reaction_counts(me_id):
            parts.append(Text("  ").join(self.reaction(comment, name, native, n, mine, me_id)
                                         for name, native, n, mine in counts))
        parts.append(Text(""))
        return Group(*parts)

    def show_comment(self, comment_id: str) -> None:
        """Mark the comment and scroll to it, now if the comments are in, else when they are."""
        self.target_comment, self.scroll_pending = comment_id, True
        if self.comments_shown:
            self.mark_target()

    def say_comment_missing(self) -> None:
        self.app.notify(self.MISSING_COMMENT, severity="warning")

    def mark_target(self) -> None:
        """Put the mark on the target comment and, the first time, scroll to it; say so if it isn't there."""
        for widget in self.query(".comment.target"):
            widget.remove_class("target")
        if not self.target_comment:
            return
        wanted = f"comment-{self.target_comment}"
        widget = next((w for w in self.query_one("#card-comments").children if w.id == wanted), None)
        if widget is not None:
            widget.add_class("target")
        if not self.scroll_pending or self.sections_loading:
            return
        self.scroll_pending = False
        if widget is None:
            self.say_comment_missing()
        else:
            self.call_after_refresh(self.scroll_to_widget, widget, top=True, animate=False)

    def reaction(self, comment: Comment, name: str, native: str, n: int, mine: bool, me_id: str) -> Text:
        """An emoji under a comment with who gave it, or how many when that's a lot of names."""
        who = comment.reactors(name, me_id)
        names = ", ".join(who) if n <= self.REACTORS_SHOWN else f"{n}"
        return Text.assemble(native, " ", visual(Text(names, style="bold cyan" if mine else "dim")))
