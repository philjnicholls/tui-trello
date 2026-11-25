# Privacy policy

tui-trello is a terminal client for Trello that runs on your own computer. It has no server of its own: nothing you see
or do in it is sent to its author or to anyone other than Trello (and, for the news, GitHub, as below).

## What it accesses

When you log in, you allow tui-trello to read and change your boards, cards, lists and comments, and to read your
Trello profile (name, username, avatar, email address and memberships) and mark your notifications read. It uses that
access only to show your Trello data in the terminal and to make the changes you ask for. The requests go straight from
your computer to Trello's API.

## What it stores, and where

Everything it keeps stays on your computer, in your user's folders, readable only by you:

- `~/.config/tui-trello/credentials.json`: your login (the OAuth access and refresh tokens).
- `~/.config/tui-trello/config.toml`: your settings, if you write any.
- `~/.local/state/tui-trello/drafts.json`: comments, descriptions and new cards you haven't sent yet.
- `~/.local/state/tui-trello/prefs.json`: choices you made in the app, such as which news items you've read.
- `~/.local/state/tui-trello/remote/`: a copy of tui-trello's public news file.

Your Trello data (boards, cards, comments, people) is held in memory while the app runs and is not written to disk,
apart from your own unsent drafts.

## What it sends elsewhere

- **Trello** (Atlassian): your requests, under your login. Atlassian's own privacy policy applies to them.
- **GitHub**: unless you turn it off (`[remote] enabled = false` in `config.toml`, or `--no-remote`), the app fetches
  one public file, `remote/newsfeed.md`, from `raw.githubusercontent.com` at most once an hour. The request carries no
  identifiers, no version and no cookies; GitHub sees your IP address as it would for any web request.

tui-trello sends no telemetry, analytics or crash reports.

## Removing your data

`tui-trello logout` deletes your saved login. To revoke tui-trello's access itself, remove it under Applications in your
Atlassian account settings. Deleting the folders above removes everything else the app stored.

## Contact

Questions about this policy: open an issue at https://github.com/philjnicholls/tui-trello/issues. Security problems:
see [SECURITY.md](SECURITY.md).
