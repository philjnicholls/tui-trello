"""Unsent comments and unsaved descriptions, kept per card in `$XDG_STATE_HOME/tui-trello/drafts.json`.

Trello's API has no drafts (trello.com keeps its own in the browser), so these stay on this computer, in tui-trello.
A draft is written as it is typed and survives quitting or a crash; it goes when the text is sent, or when the box is
emptied. The file is readable only by the user: drafts are private until sent.

A description draft also records the description it started from, so the editor can warn when someone has changed
the card's description on Trello since.

A new card has no id until it is made, so each new card's box keeps its draft (the name, and the description after
the first line) under `<list id>/<token>`, a key of its own from the moment it opens: two boxes on one list, or one
open while another card is being sent, never write over each other. The draft stays until Trello has made the card.
While it is being sent it is marked `sent`, and the mark is kept if the outcome is unknown (the app quit, or the
request timed out after reaching Trello), so whoever offers the draft again can warn that the card may exist already.
Once marked, it stays until the card is made or the draft is dropped: neither a later failure nor an edit unmakes a
card Trello may have made. See `Store.new_card_box`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal
from uuid import uuid4

from tui_trello.config import state_dir

Kind = Literal["comment", "desc", "card"]


def drafts_path() -> Path:
    return state_dir() / "drafts.json"


def new_card_id(list_id: str) -> str:
    """A key of its own for a new card's draft on the list."""
    return f"{list_id}/{uuid4().hex[:8]}"


@dataclass(frozen=True)
class Draft:
    text: str
    base: str = ""  # for a description: the description the draft was started from
    sent: bool = False  # for a new card: sent, and not known to have failed (Trello may have made it)


class Drafts:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or drafts_path()
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            data = {}
        self._drafts = {key: Draft(d.get("text", ""), d.get("base", ""), bool(d.get("sent"))) for key, d in data.items()
                        if isinstance(d, dict)}

    @staticmethod
    def _key(kind: Kind, card_id: str) -> str:
        return f"{kind}:{card_id}"

    def get(self, kind: Kind, card_id: str) -> Draft | None:
        return self._drafts.get(self._key(kind, card_id))

    def kinds(self, card_id: str) -> list[Kind]:
        """Which drafts the card has: "comment", "desc", both or neither."""
        return [kind for kind in ("comment", "desc") if self._key(kind, card_id) in self._drafts]

    def ids(self, kind: Kind, prefix: str) -> list[str]:
        """The ids of the kind's drafts starting with the prefix, oldest first."""
        start = self._key(kind, prefix)
        return [key.removeprefix(f"{kind}:") for key in self._drafts if key.startswith(start)]

    def set(self, kind: Kind, card_id: str, text: str, base: str = "") -> bool:
        """Keep the text as the card's draft, or drop the draft if the text is blank. True if anything changed."""
        key, before = self._key(kind, card_id), self._drafts.get(self._key(kind, card_id))
        if text.strip():
            # An edit keeps a new card's mark that it was sent: Trello may have made it all the same.
            self._drafts[key] = Draft(text, base, bool(before and before.sent))
        else:
            self._drafts.pop(key, None)
        if self._drafts.get(key) == before:
            return False
        self._save()
        return True

    def discard(self, kind: Kind, card_id: str) -> bool:
        return self.set(kind, card_id, "")

    def mark_sent(self, kind: Kind, card_id: str, sent: bool) -> None:
        """Mark the draft as sent, with the outcome unknown, or not."""
        key = self._key(kind, card_id)
        if (draft := self._drafts.get(key)) and draft.sent != sent:
            self._drafts[key] = replace(draft, sent=sent)
            self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({key: {"text": d.text} | ({"base": d.base} if d.base else {}) | ({"sent": True} if d.sent else {})
                       for key, d in self._drafts.items()}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)  # a crash mid-write leaves the old file, not half a new one
