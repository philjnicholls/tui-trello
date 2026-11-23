"""Following a link found in a card's text: the router. It reads what a URL points to (`tui_trello.links`) and sends
it to the part of the app that already handles that: the card screen, the browser view, the attachment picker, or
the web browser."""

from __future__ import annotations

import webbrowser
from typing import Literal
from urllib.parse import urlsplit

from rich.text import Text
from textual.worker import WorkerCancelled

from tui_trello import links
from tui_trello.backend import BackendError
from tui_trello.models import Card
from tui_trello.ui import markdown
from tui_trello.ui.screens.card import CardScreen
from tui_trello.ui.screens.picker import AttachmentPickerScreen, Choice

OPENABLE_SCHEMES = {"http", "https", "mailto"}
ICONS = {"board": "🗂 ", "card": "🃏 ", "comment": "💬 ", "attachment": "📎 ", "web": "🔗 "}
KIND_NAMES = {"web": "web page"}  # the others are called what they are


async def follow(app, url: str) -> Literal["screen", "board", "browser", "nothing"]:
    """Do what following `url` means: open the card, comment, board or attachment it points to, or the web page.
    Says what came of it: "screen" (the card screen or the attachments picker is up), "board" (the board's browser
    view is up, or another board load took over), "browser" (the web browser was asked to open it), or "nothing" (a
    toast says why)."""
    store = app.store
    link = links.parse(url, store.link_hosts)
    try:
        if link.kind == "web":
            open_in_browser(app, url)
            return "browser"
        if link.kind == "board":
            board = await store.board_by_link(link.short_link)
            await app.switch_mode("browser")
            while isinstance(app.screen, CardScreen):  # so the board shows
                await app.pop_screen()
            return await open_board(app, board.id)
        if link.kind == "attachment":
            attachments = await store.attachments(link.card_id)
            if any(a.id == link.attachment_id for a in attachments):
                app.push_screen(AttachmentPickerScreen(link.card_id, target=link.attachment_id))
                return "screen"
            app.notify("That attachment is no longer on its card", severity="warning")
            return "nothing"
        card = await store.card_by_link(link.short_link)
        return "screen" if await show_card(app, card.id, card.board_id, link.comment_id) == "opened" else "nothing"
    except BackendError as exc:
        app.notify(str(exc), title="Could not follow the link", severity="error", markup=False)
        return "nothing"


async def open_board(app, board_id: str) -> Literal["board", "nothing"]:
    """Load the board in the app's board worker and wait for it. "board" if it loaded, or if the user opened another
    board meanwhile (that load cancels this one, and wins); "nothing" if it failed (the worker has shown a toast)."""
    try:
        await app.open_board(board_id).wait()
    except WorkerCancelled:
        return "board"
    snapshot = app.store.snapshot
    return "board" if snapshot is not None and snapshot.board.id == board_id else "nothing"


def open_in_browser(app, url: str) -> None:
    """Open the link in the web browser, if it is one that is safe to: it comes from other people's text."""
    scheme = urlsplit(url).scheme.lower()
    if scheme in OPENABLE_SCHEMES:
        webbrowser.open(url)
    else:
        app.notify(f"Not opening a {scheme or 'relative'}: link", severity="warning", markup=False)


async def show_card(app, card_id: str, board_id: str, comment_id: str = "") -> Literal["opened", "gone", "error"]:
    """Open the card screen on the card (loading its board if no loaded snapshot has it), scrolled to the comment if
    there is one. If that can't be done, say why with a toast: "error" if its board didn't load, "gone" if the card
    is archived or deleted."""
    store = app.store
    if not store.find_card(card_id):
        try:
            snapshot = await store.open_board(board_id)
        except BackendError as exc:
            app.notify(str(exc), title="Could not open board", severity="error")
            return "error"
        app.sub_title = snapshot.board.name
    if not store.find_card(card_id):
        app.notify("That card has been archived or deleted.", severity="warning")
        return "gone"
    screen = app.screen
    if isinstance(screen, CardScreen) and screen.card_id == card_id:
        if comment_id:
            screen.show_comment(comment_id)
        else:
            app.notify("That's this card")
    else:
        app.open_card(card_id, comment_id)
    return "opened"


async def link_choices(app, card: Card) -> list[Choice[str]]:
    """Every distinct link in the card's description, comments and checklist items, in that order."""
    store = app.store
    found: list[tuple[markdown.Link, str]] = [(link, "description") for link in markdown.links(card.desc)]
    for comment in await store.comments(card.id):
        when = f", {comment.date:%d %b}" if comment.date else ""
        found += [(link, f"{comment.author}'s comment{when}") for link in markdown.links(comment.text)]
    if card.checklist[1] or store.has_checklists(card.id):
        for checklist in await store.checklists(card.id):
            for item in checklist.items:
                found += [(link, f"checklist {checklist.name}") for link in markdown.links(item.name, one_line=True)]
    choices: list[Choice[str]] = []
    seen: set[str] = set()
    for link, source in found:
        if link.url in seen:
            continue
        seen.add(link.url)
        parsed = links.parse(link.url, store.link_hosts)
        label = link.text if link.text != link.url else describe(app, parsed)
        kind = KIND_NAMES.get(parsed.kind, parsed.kind)
        choices.append(Choice(label, link.url, f"{kind} · {source}", Text(ICONS[parsed.kind])))
    return choices


def describe(app, link: links.TrelloLink) -> str:
    """A name for a link whose text is just its URL: the card or board's name if it is loaded, an attachment's file
    name, a web page's host and path."""
    store = app.store
    if link.kind in ("card", "comment") and (card := store.known_card(link.short_link)):
        return card.name
    if link.kind == "board" and (board := store.known_board(link.short_link)):
        return f"Board: {board.name}"
    parts = urlsplit(link.url)
    if link.kind == "attachment":
        return parts.path.rsplit("/", 1)[-1] or link.url
    return (parts.netloc + parts.path).removeprefix("www.") or link.url
