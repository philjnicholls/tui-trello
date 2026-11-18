"""Unsent comments and unsaved descriptions, kept per card in `$XDG_STATE_HOME/tui-trello/drafts.json`.

Trello's API has no drafts (trello.com keeps its own in the browser), so these stay on this computer, in tui-trello.
A draft is written as it is typed and survives quitting or a crash; it goes when the text is sent, or when the box is
emptied. The file is readable only by the user: drafts are private until sent.

A description draft also records the description it started from, so the editor can warn when someone has changed
the card's description on Trello since.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Kind = Literal["comment", "desc"]


def drafts_path() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "tui-trello" / "drafts.json"


@dataclass(frozen=True)
class Draft:
    text: str
    base: str = ""  # for a description: the description the draft was started from


class Drafts:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or drafts_path()
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            data = {}
        self._drafts = {key: Draft(d.get("text", ""), d.get("base", "")) for key, d in data.items()
                        if isinstance(d, dict)}

    @staticmethod
    def _key(kind: Kind, card_id: str) -> str:
        return f"{kind}:{card_id}"

    def get(self, kind: Kind, card_id: str) -> Draft | None:
        return self._drafts.get(self._key(kind, card_id))

    def kinds(self, card_id: str) -> list[Kind]:
        """Which drafts the card has: "comment", "desc", both or neither."""
        return [kind for kind in ("comment", "desc") if self._key(kind, card_id) in self._drafts]

    def set(self, kind: Kind, card_id: str, text: str, base: str = "") -> bool:
        """Keep the text as the card's draft, or drop the draft if the text is blank. True if anything changed."""
        key, before = self._key(kind, card_id), self._drafts.get(self._key(kind, card_id))
        if text.strip():
            self._drafts[key] = Draft(text, base)
        else:
            self._drafts.pop(key, None)
        if self._drafts.get(key) == before:
            return False
        self._save()
        return True

    def discard(self, kind: Kind, card_id: str) -> bool:
        return self.set(kind, card_id, "")

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({key: {"text": d.text, "base": d.base} if d.base else {"text": d.text}
                       for key, d in self._drafts.items()}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)  # a crash mid-write leaves the old file, not half a new one
