"""Which Trello thing a URL points to: a board, a card, a comment, an attachment, or something else (a web page).

Pure functions, no UI and no network. `ui/follow.py` sends each kind to the part of the app that handles it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

TRELLO_HOSTS = frozenset({"trello.com", "www.trello.com"})  # a backend may have more (the demo's)

# Short links are not told by their length: the demo's ids ("id12", "b-product") don't look like Trello's.
BOARD_PATH = re.compile(r"^/b/([^/?#]+)(?:/.*)?$")
CARD_PATH = re.compile(r"^/c/([^/?#]+)(?:/.*)?$")
ATTACHMENT_PATH = re.compile(r"^/1/cards/([^/?#]+)/attachments/([^/?#]+)(?:/.*)?$")
COMMENT_FRAGMENT = re.compile(r"^comment-(.+)$")


@dataclass(frozen=True)
class TrelloLink:
    kind: Literal["board", "card", "comment", "attachment", "web"]
    url: str
    short_link: str = ""  # board or card
    comment_id: str = ""
    card_id: str = ""  # an attachment's card: the full id
    attachment_id: str = ""


def parse(url: str, hosts: frozenset[str] = TRELLO_HOSTS) -> TrelloLink:
    """What `url` points to; "web" for anything the app has no view for."""
    web = TrelloLink("web", url)
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
    except ValueError:
        return web
    if parts.scheme.lower() not in ("http", "https") or host not in hosts:
        return web
    if match := BOARD_PATH.match(parts.path):
        return TrelloLink("board", url, short_link=match[1])
    if match := CARD_PATH.match(parts.path):
        if comment := COMMENT_FRAGMENT.match(parts.fragment):
            return TrelloLink("comment", url, short_link=match[1], comment_id=comment[1])
        return TrelloLink("card", url, short_link=match[1])
    if match := ATTACHMENT_PATH.match(parts.path):
        return TrelloLink("attachment", url, card_id=match[1], attachment_id=match[2])
    return web


def short_link(url: str, hosts: frozenset[str] = TRELLO_HOSTS) -> str:
    """The short link of a board or card URL; "" for any other."""
    link = parse(url, hosts)
    return link.short_link if link.kind in ("board", "card", "comment") else ""
