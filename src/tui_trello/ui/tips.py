"""Tips on using tui-trello, shown in the card pane while there's no card to show. Inline Markdown: keys in `code`,
written as `{id}` placeholders that `ui/keymap.py` fills with the key in use."""

from __future__ import annotations

TIPS = (
    "`{browser.in}` goes into a column and `{browser.out}` backs out; `enter` opens a card full screen.",
    "`{list.filter}` filters the cards on screen: words, `#label`, `@member`, `list:name`, `!overdue`, `!due`. "
    "`{list.clear_filter}` clears it.",
    "`{app.search}` searches every board on Trello, archived cards too; `board:` and `label:` narrow it.",
    "`{app.commands}` opens the command palette: jump to any board or card by typing part of its name.",
    "`{app.boards}` picks another board. Set `default_board` in config.toml to open one at start-up.",
    "`{app.browser}` `{app.triage}` `{app.mywork}` `{app.notifications}` switch between the browser, triage, my work "
    "and notifications; `{chord.next_view}` and `{chord.previous_view}` step through them.",
    "`{card.comment}` comments on a card: `@` mentions someone, `{editor.newline}` starts a new line.",
    "`{card.reply}` replies to a comment: the reply quotes it and @mentions its author.",
    "`{card.edit_comment}` edits one of your comments, `{card.delete_comment}` deletes one.",
    "`{editor.cancel}` in a comment or description keeps what you wrote as a draft, even if you quit.",
    "`{card.react}` reacts to a comment with an emoji; picking one you gave takes it off.",
    "`{list.new_card}` makes a new card: on the highlighted list in the browser, or pick the list in triage and my "
    "work.",
    "`{card.move}` moves a card to another list; `{card.archive}` archives it.",
    "`{card.labels}` puts labels on a card or takes them off; type a new name to create one.",
    "`{card.checklist}` ticks checklist items; type new text to add an item or a checklist.",
    "`{card.attachments}` lists a card's attachments: open one, save it to Downloads, or attach a file or a link.",
    "`{editor.attach}` in a comment or description attaches a file and puts its link in.",
    "`{card.copy_link}` copies a card's link, `{card.copy_comment_link}` the link to one of its comments.",
    "`{card.open}` opens the card on trello.com.",
    "`{card.follow_link}` follows a link on a card: a Trello card, comment, board or attachment opens right here.",
    "Click a link to preview its card, comment or attachment in a popup; `{preview.close}` closes it and you're back "
    "where you were.",
    "In notifications, `{notifications.toggle_read}` shows or hides the ones you've read; tui-trello remembers "
    "which.",
    "`{triage.sort}` in triage cycles the sort: list, due date, last activity.",
    "`{mywork.preview}` in my work shows or hides the card preview.",
    "`{app.refresh}` reloads from Trello.",
    "Every key can be changed in config.toml's `[keys]`; `tui-trello keys` lists them.",
    "`{app.help}` lists every key.",
)
