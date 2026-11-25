# Security policy

## Supported versions

Only the latest release of tui-trello gets security fixes.

## Reporting a vulnerability

Please report it privately, using GitHub's private vulnerability reporting: open the **Security** tab of
[philjnicholls/tui-trello](https://github.com/philjnicholls/tui-trello/security) and choose **Report a vulnerability**.
That is the only channel; please don't open a public issue or pull request for a security problem. You can expect a
first reply within a week, and a fix or a decision, with credit if you want it, once the report is understood.

Never put a Trello token, a refresh token or private card content in a report.

## What the app keeps, and where

- `~/.config/tui-trello/credentials.json`: your login (the OAuth tokens), mode 0600, written atomically. `tui-trello logout` deletes it; revoke the login itself under Applications at
  https://trello.com/my/account.
- `~/.local/state/tui-trello/`: drafts of comments and descriptions (`drafts.json`), remembered choices
  (`prefs.json`), and the cached copy of the remote files (`remote/`).
- `~/.config/tui-trello/config.toml`: your settings.

The app sends no telemetry. During `tui-trello login` it listens on `127.0.0.1` only (port 8765 by default), for the
one callback from your browser, and stops when the login finishes or times out.

## Public by design

`OAUTH_CLIENT_ID` in `src/tui_trello/auth.py` is in the source on purpose. It identifies the application to Atlassian
and Trello, not a user, and no secret is embedded: the OAuth client is a public client, and PKCE protects the
exchange. A fork can register its own OAuth client.

## Remote files

Unless turned off, the app reads one file from this repository's `main` branch over HTTPS, at most once an hour (see
[docs/remote.md](docs/remote.md)): `remote/newsfeed.md`. It can show text in the news popup and a toast. Its links are
not clickable, and toasts are not read as markup. The worst a hostile item could do is say something misleading. Nothing
fetched changes any setting, or where the app fetches from: those are in the code.

To turn it off, set `enabled = false` under `[remote]` in `config.toml`, or start with `--no-remote`: the app then makes
no request to GitHub and ignores any copy it saved.

Anyone who can push to `main` could change the news, and the code of every later release; the remote file differs only
in reaching running copies within an hour, without an upgrade. The file is not signed; this was judged acceptable for
those limits, and you can turn the feature off.
