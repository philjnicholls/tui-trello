# Architecture

```
src/tui_trello/
  cli.py              argument parsing; picks a backend; starts the app
  config.py           Settings from env vars and ~/.config/tui-trello/config.toml
  auth.py             OAuth 2.0 + PKCE login, token refresh (OAuth2Auth), the older key/token flow (TokenAuth)
  models.py           frozen dataclasses: Board, CardList, Card, Label, Member, Comment; BoardSnapshot (one
                      board) and WorkSnapshot (my cards on every board), both satisfying CardContext
  agenda.py           group cards by due date for My work
  query.py            the card filter language (#label @member list:x !overdue words)
  store.py            app-wide state: open board, my work, caches; board_changed and work_changed signals
  backend/
    __init__.py       Backend protocol + BackendError
    trello.py         Trello REST API over async httpx
    demo.py           in-memory sample data (--demo, tests, screenshots)
  ui/
    app.py            TrelloApp: modes (one per layout), vim motions and chords, palette providers
    commands.py       ctrl+p providers: boards, cards
    render.py         how a card/label/due date looks, shared by every view
    bidi.py           right-to-left text: reorder per field (a compact UAX #9), BidiText, fit()
    markdown.py       Markdown in descriptions and comments as styled, RTL-aware text
    widgets/
      card_view.py    card header, description, comments
      spinner.py      the top-bar spinner, driven by Store.busy: the only loading indicator
    screens/
      base.py         CardActionsScreen (m, c, o), ListScreen (/ filter), BoardScreen (redraws on board_changed)
      browser.py      Miller columns: lists | cards | preview
      triage.py       sortable, filterable table of every card
      mywork.py       my cards on every board, grouped by due date, with preview
      card.py         full-screen card
      keys.py         the ? key reference
      picker.py       PickerScreen (fuzzy choose one) and TextPromptScreen
tests/                pytest; UI flows driven by key presses against the demo backend
scripts/screenshots.py
```

## Layers

```
 screens / widgets ──read──▶ Store ──calls──▶ Backend (TrelloBackend | DemoBackend)
        ▲                      │
        └── board_changed ─────┘
```

- **Models** are the only thing the UI sees. Raw API JSON stops at `Model.from_api`, so the UI doesn't care whether
  data came from the REST API, the demo backend or (later) a local cache.
- **Auth**: `tui-trello login` runs OAuth 2.0 with PKCE against tui-trello's public OAuth client, so users never
  register an app. `OAuth2Auth`, an `httpx.Auth` handed to `TrelloBackend`, sends the bearer token and refreshes it
  (under a lock: refresh tokens are single use and the backend sends requests concurrently), saving each new pair.
  `TokenAuth` is the older key + token scheme, kept for `login --token` and scripts.
- **Backend** is a `Protocol`: async methods returning models, raising `BackendError` with a message fit to show the
  user. Anything that implements it can be passed to `TrelloApp`.
- **Store** owns the open `BoardSnapshot` and the `WorkSnapshot`. Every mutation goes through it; it patches every
  snapshot holding the card and publishes `board_changed` / `work_changed`, and every screen (in any mode, at any
  depth of the screen stack) redraws. No screen calls another screen to tell it something changed. Screens draw a
  card through `CardContext`, so the card view and the verbs work the same whichever snapshot the card came from.
- **Loading**: every backend call in `Store` runs inside `_busy(name)`, which publishes `busy_changed`; the
  `Spinner` in each screen's `TopBar` turns and says what is in flight. That is the only loading indicator.
- **Right-to-left text**: anything that came from Trello goes through `ui/bidi.py` before it is drawn: `visual()`
  for short fields, `fit()` for fixed-width columns, `BidiText` for text that wraps. Never reorder a whole row:
  columns would swap sides. The CLI switches bidi terminals to explicit mode so they don't reorder screen lines.
- **Keys**: motions (`j` `k` `gg` `G` `ctrl+d` `ctrl+u`) live once in `TrelloApp` and act on the focused widget,
  trying its `action_cursor_down`, `action_first`, `action_scroll_home`, ... in turn (`MOTIONS`). Two-key sequences
  are in `CHORDS`. Screens bind only what is theirs: `h`/`l`, and their verbs. Keep `ui/screens/keys.py` in step.
- **Screens** are Textual screens. Layouts are Textual *modes*, each with its own screen stack, so switching from the
  browser to the triage table and back keeps your place in both.

The old proof of concept made blocking `py-trello` calls on the UI thread (card comments) and in a thread worker;
everything is now `async` on Textual's event loop, and board loading fetches lists, cards, members and labels
concurrently.

## Adding things

| to add                  | do                                                                                    |
| ----------------------- | ------------------------------------------------------------------------------------- |
| a card action (archive, | a `Binding` and an `action_*` on `CardActionsScreen` in `ui/screens/base.py`; a       |
| assign, due date, ...)  | `Store` method that calls the backend and publishes `board_changed`; a method on the  |
|                         | `Backend` protocol, `TrelloBackend` and `DemoBackend`. It then works in every layout. |
| a layout                | a `BoardScreen` subclass implementing `show_board()` (and `current_card()` if it      |
|                         | extends `CardActionsScreen`); add it to `TrelloApp.MODES`, a key to switch to it, and |
|                         | its name to `config.LAYOUTS`.                                                         |
| a filter term           | an entry in `query.FLAGS` (`!name`), or a prefix in `CardQuery.parse`.                |
| a palette command       | a `textual.command.Provider` in `ui/commands.py`, added to `TrelloApp.COMMANDS`.      |
| a field on cards        | the dataclass field and `from_api` in `models.py`; add it to `CARD_FIELDS` in         |
|                         | `backend/trello.py`; show it in `ui/render.py`.                                       |
| a picker                | `await self.app.push_screen_wait(PickerScreen(title, [Choice(label, value), ...]))`   |
|                         | inside a `@work` method.                                                              |

Every new feature should come with a test in `tests/test_app.py` that drives it with key presses against
`DemoBackend`; those run in a second or two and need no network.

## Next steps worth doing

- **Optimistic updates with undo**: `Store.move_card` could patch the snapshot first, call the backend, and roll back
  (with a toast) on failure; `u` would undo the last move.
- **Local cache**: a `CachingBackend` that wraps `TrelloBackend` and stores snapshots in SQLite, so start-up is
  instant and the app works offline read-only. It slots in without touching the UI.
- **Rate limits**: Trello allows 100 requests / 10 s per token; `TrelloBackend._request` is the one place to add a
  limiter and retry on 429.
- **Keymap config**: give each `Binding` an `id`, read `[keys]` from the config file and apply it with
  `App.set_keymap` (and let `CHORDS` be overridden the same way).
- **Counts**: `5j` / `3gt` would be a small extension of the chord handling in `TrelloApp.on_event`.
