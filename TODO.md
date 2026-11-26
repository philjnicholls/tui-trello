# TODO

Ordered by how much each item helps users: earlier sprints fill gaps people hit every day; later ones are polish,
rarer workflows and internal tidying.

## Sprint 1: everyday card editing

The core Trello verbs that are missing outright.

* feat set, change and clear a card's due and start dates, and mark the due date complete
* feat rename a card
* feat reorder cards within a list
* feat browse archived cards and restore them

## Sprint 2: lists, boards and moving work around

Structural editing, so a board can be run without opening Trello in a browser.

* feat create, rename, archive and reorder lists
* feat move a card to another board, and copy a card
* feat create and close boards; star and unstar a board

## Sprint 3: finishing half-done features

Things that can be created but not then fixed or removed, plus the data-loss and noise bugs users notice.

* feat rename, delete and reorder checklists and checklist items; set an item's due date and assignee
* feat delete and rename attachments
* feat save uploaded attachments again under OAuth (ctrl+s only explains for now; Trello's download needs the old API key)
* feat edit a label's name and colour, and delete a label from the board
* bug the retired-setting warning shows twice in one launch: on the command line before login, then in the app
* bug a malformed newsfeed reply (protocol or decoding error) keeps the stored ETag; only connect/timeout errors should

## Sprint 4: richer cards and staying informed

Useful for teams that rely on them, less often needed day to day.

* feat show and edit custom fields on a card
* feat board and card activity history beyond comments
* feat watch and unwatch boards and lists
* feat set and remove a card cover (image or colour)

## Sprint 5: polish, niche and housekeeping

* feat demo data that shows every feature, annotated screenshots and a short screen recording for the README
* bug terminals that shape Arabic themselves (VTE default, Konsole, mlterm) can join the app's reordered Arabic letters wrongly
* feat voting on cards (Power-Up)
* feat stickers on cards
* chore `tui-trello keys` picks out [keys] problems by message prefix; keep them in their own list
