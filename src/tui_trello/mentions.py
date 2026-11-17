"""@mentions in comments: find the mention being typed and the members it could be.

Trello notifies a member when a comment contains `@username`.
"""

from __future__ import annotations

import re

from tui_trello.models import Member

# "@" at the start of the text or after a space, then the partial name up to the cursor.
TYPING = re.compile(r"(?:^|(?<=\s))@([\w.\-]*)$")
LIMIT = 8


def typing_mention(before_cursor: str) -> str | None:
    """The partial name after an "@" just before the cursor ("" right after the "@"), or None."""
    match = TYPING.search(before_cursor)
    return match.group(1) if match else None


def candidates(members: list[Member], query: str) -> list[Member]:
    """Members whose username, or any word of whose name, starts with `query`; username matches first."""
    query = query.lower()

    def rank(member: Member) -> int | None:
        if member.username.lower().startswith(query):
            return 0
        if any(word.lower().startswith(query) for word in member.full_name.split()):
            return 1
        return None

    ranked = [(r, m) for m in members if (r := rank(m)) is not None]
    return [m for _, m in sorted(ranked, key=lambda rm: (rm[0], rm[1].username.lower()))][:LIMIT]
