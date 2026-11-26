# Changelog

All notable changes to tui-trello are listed here, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Before 1.0.0, any release may change the command line,
`config.toml` or the `[keys]` ids.

## [Unreleased]

### Added

- Card members: join or leave a card (`J`), add or remove board members (`M`); my work follows at once. Watch or
  unwatch a card (`w`), shown with 👀. `M`, `J` and `w` are new default keys: a `[keys]` override that already uses one
  of them is refused, so move it to another key.

## [0.1.0] - 2026-11-25

First public release.

### Added

- Four views: the Miller-column browser, triage, my work and notifications.
- Log in with OAuth 2.0 and PKCE (`tui-trello login`).
- Search every board on Trello, archived cards included, and filter the cards on screen.
- Create, move, archive and delete cards; edit descriptions; manage labels, checklists and attachments.
- Drafts of comments, descriptions and new cards, kept if the app is closed or Trello can't be reached.
- Comments with replies, reactions, editing and deleting, and @mentions.
- Links to Trello cards, comments, boards and attachments: follow them in the app, or preview them in a popup.
- Right-to-left text (Arabic and other RTL scripts) laid out by the app, including terminals that reorder text themselves.
- Markdown in descriptions and comments, and `:shortcode:` emoji.
- Configurable keys: `[keys]` in `config.toml`, listed by `tui-trello keys`, with two-key sequences.
- Notifications with unread counts, in-app toasts and desktop alerts.
- `--open URL` to start on a Trello link, and `--demo` to try the app with sample data.
- `--version`.
- News about tui-trello, shown with `N`, read from the public repository (turn off with `[remote] enabled = false` or
  `--no-remote`).

[Unreleased]: https://github.com/philjnicholls/tui-trello/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/philjnicholls/tui-trello/releases/tag/v0.1.0
