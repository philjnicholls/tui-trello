"""Tips on using tui-trello, shown in the card pane while there's no card to show. Inline Markdown: keys in `code`."""

from __future__ import annotations

TIPS = (
    "`l` goes into a column and `h` backs out; `enter` opens a card full screen.",
    "`/` filters the cards: words, `#label`, `@member`, `list:name`, `!overdue`, `!due`. `esc` clears it.",
    "`:` opens the command palette: jump to any board or card by typing part of its name.",
    "`b` picks another board. Set `default_board` in config.toml to open one at start-up.",
    "`1` `2` `3` `4` switch between the browser, triage, my work and notifications; `gt` and `gT` step through them.",
    "`c` comments on a card: `@` mentions someone, `alt+enter` starts a new line.",
    "`C` replies to a comment: the reply quotes it and @mentions its author.",
    "`esc` in a comment or description keeps what you wrote as a draft, even if you quit.",
    "`R` reacts to a comment with an emoji; picking one you gave takes it off.",
    "`m` moves a card to another list.",
    "`t` puts labels on a card or takes them off; type a new name to create one.",
    "`x` ticks checklist items; type new text to add an item or a checklist.",
    "`a` lists a card's attachments: open one, save it to Downloads, or attach a file or a link.",
    "`ctrl+o` in a comment or description attaches a file and puts its link in.",
    "`y` copies a card's link, `Y` the link to one of its comments.",
    "`o` opens the card on trello.com.",
    "In notifications, `u` shows or hides the ones you've read; tui-trello remembers which.",
    "`s` in triage cycles the sort: list, due date, last activity.",
    "`p` in my work shows or hides the card preview.",
    "`r` reloads from Trello.",
    "`?` lists every key.",
)
