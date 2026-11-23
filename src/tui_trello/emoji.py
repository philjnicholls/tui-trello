"""`:shortcode:` emoji, shown as the emoji itself, as Trello's web app does.

Trello keeps the name Trello's emoji picker gave (`:smiley:`, `:+1:`) in the text it stores. The names are iamcal's
emoji-data names (see `emoji_codes.py`), not Rich's or GitHub's, so only a name in that table is replaced: anything
else (`:nope:`, a removed custom emoji) stays as typed. Skin tones are names of their own, written straight after the
emoji (`:+1::skin-tone-3:`), so they fall out as two emoji side by side.

The opening colon may not follow a word character, "/", "=", "?" or "&", and the closing one may not be followed by a
word character, so times (`10:30:00`), `a:b:c` and URL paths and queries in plain text are left alone.

Display only: apply it where text is drawn, never to text that is edited or sent back to Trello.
"""

from __future__ import annotations

import re
from functools import lru_cache

from tui_trello.emoji_codes import CODES

SHORTCODE = re.compile(r"(?<![\w/=?&]):([a-z0-9_+\-]+):(?!\w)")


# Longer texts skip the cache, so it holds short names and not whole comments.
CACHE_LIMIT = 300


@lru_cache(maxsize=4096)
def _replace(text: str) -> str:
    return SHORTCODE.sub(lambda m: CODES.get(m.group(1), m.group()), text)


def with_emoji(text: str) -> str:
    """`text` with each :name: Trello knows (`:smiley:`, `:+1:`) as the emoji itself; others stay as written."""
    if ":" not in text:
        return text
    return _replace(text) if len(text) <= CACHE_LIMIT else _replace.__wrapped__(text)
