"""Keep the Alt modifier on named keys.

Terminals send Alt+<key> as ESC followed by the key. Textual's parser (textual._xterm_parser, as of 8.2) only adds
"alt+" to single-character keys, so Alt+Enter arrives as plain "enter" and can't be bound (the comment box uses it
for a new line). This wraps the parser's key mapping to add "alt+" to named keys too: enter, tab, backspace, ...

Shift+Enter can't be done the same way: most terminals (GNOME Terminal included) send exactly what Enter sends.
"""

from __future__ import annotations

from textual import events

try:
    from textual._xterm_parser import XTermParser
except ImportError:  # pragma: no cover - Textual moved its parser; Alt+named keys just stay unbound
    XTermParser = None


def install() -> None:
    if XTermParser is None or getattr(XTermParser, "_tui_trello_alt", False):
        return
    original = XTermParser._sequence_to_key_events

    def sequence_to_key_events(self, sequence: str, alt: bool = False):
        for event in original(self, sequence, alt):
            if alt and len(sequence) == 1 and not event.key.startswith("alt+") and len(event.key) > 1:
                event = events.Key(f"alt+{event.key}", event.character)
            yield event

    XTermParser._sequence_to_key_events = sequence_to_key_events
    XTermParser._tui_trello_alt = True
