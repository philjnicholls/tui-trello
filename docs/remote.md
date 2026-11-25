# Remote files

tui-trello reads one small file from this repository's `main` branch, so it can change without a release:

- `https://raw.githubusercontent.com/philjnicholls/tui-trello/main/remote/newsfeed.md`: news for users.

The code is `src/tui_trello/remote.py`, and the news popup is `ui/screens/news.py`. The URL is fixed in the code:
nothing fetched can change where the app fetches from, or any setting.

## `newsfeed.md`

One item per `## YYYY-MM-DD: Title` heading, Markdown under it, newest first. Headings that don't match are skipped
with their text; at most 20 items are kept. The heading line is the item's identity: the app remembers which it has
shown (`news_seen` in `prefs.json`), so editing a heading makes the item new again. News is shown as plain text: links
are not clickable, and toasts are never read as markup.

## How it is fetched

- A background worker checks after the first screen is up, at most once an hour (`CHECK_AFTER`), and every six hours
  while the app stays open (`RECHECK_EVERY`). The app starts exactly as fast as without it.
- A GET with `If-None-Match` and the cached ETag, so an unchanged file costs a `304`. The ETag is sent only if it is
  printable ASCII, and a failed fetch forgets it, so a damaged cache can't block refreshes for good. No cookies, no
  identifiers, no version: just `User-Agent: tui-trello`. A 3 second timeout per request, 6 seconds for the whole
  refresh. Redirects are not followed.
- A body over 64 KiB or one that isn't UTF-8: the file is discarded. Offline, a 404 (the repository private or
  renamed), another status or a timeout: nothing is said. In every case the last good copy stays and the next check
  tries again.
- GitHub's CDN may serve a copy up to about five minutes old after a push.

The cache is `$XDG_STATE_HOME/tui-trello/remote/` (`~/.local/state/tui-trello/remote/`): `newsfeed.md` and `meta.json`
(the ETag, the last fetch and the last attempt), written atomically.

## Turning it off

`[remote] enabled = false` in `config.toml`, or `--no-remote`: no request to GitHub, the cache ignored and no news.
`SECURITY.md` explains the trade-off and why the file isn't signed.

## Testing

`RemoteFiles(cache_dir, transport)` takes an `httpx.MockTransport`, so tests answer from a handler and make no network
request (see `tests/test_remote.py`). `tests/conftest.py` replaces `remote.default_transport` so a test that doesn't
pass a transport fails if it fetches. `TrelloApp` takes `remote=None` by default: no fetching, no news, no badge, which
is what the tests and `scripts/screenshots.py` use.
