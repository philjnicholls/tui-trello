# Contributing to tui-trello

Thanks for thinking of helping. Bug reports, ideas and pull requests are all welcome. Please read the
[code of conduct](CODE_OF_CONDUCT.md) first. For a security problem, don't open an issue: see
[SECURITY.md](SECURITY.md).

For anything bigger than a small fix, open an issue first so we can agree on the shape of it before you spend time.

## Set up

tui-trello needs Python 3.11 or newer. From a clone of the repository:

```sh
python -m venv venv
venv/bin/pip install -e '.[dev]'
```

The package is installed editable, so code changes apply the next time you start the app.

## Run

```sh
venv/bin/tui-trello --demo          # built-in sample data: no Trello account, no network
venv/bin/python -m tui_trello --demo
```

`--demo` is the quickest way to see a change. To run against your own Trello, use `tui-trello login` once.

The app takes over the terminal, so `print()` output and tracebacks from workers are only visible through Textual's
dev console. Use two terminals:

```sh
venv/bin/textual console                                 # terminal 1
venv/bin/textual run --dev -c tui-trello --demo          # terminal 2
```

## Test

```sh
venv/bin/pytest                          # everything (a few minutes)
venv/bin/pytest tests/test_cli.py        # one file
venv/bin/pytest tests/test_cli.py::test_version_prints_the_version_and_exits
```

The tests make no network request and open no browser. Interface flows are driven with key presses against the demo
backend (`tests/test_app.py`); the Trello backend is tested with `httpx.MockTransport` (`tests/test_trello_backend.py`).
`tests/conftest.py` fails any test that opens a browser tab or fetches the remote files without a transport of its own.
Add a test with every change, in the style of its neighbours.

## Lint

```sh
venv/bin/ruff check .
```

The rules (pycodestyle, pyflakes, isort, pyupgrade, bugbear; line length 120) are in `pyproject.toml`. The code is not
run through `ruff format`: match the compact style of the code around yours.

## Keep these in step

- **The key table.** Every key has an id (`card.archive`). A new binding needs an entry in `WHAT` in
  `src/tui_trello/ui/keymap.py`, a line in the `?` help (`ui/screens/keys.py`), and a row in the README's table
  between the `<!-- keys-table -->` markers. `tests/test_keymap.py` checks the README against the code; regenerate the
  table with `python -c "from tui_trello.ui import keymap; print(keymap.markdown_table())"`.
- **Screenshots**, after a change to how a view looks: `venv/bin/python scripts/screenshots.py` regenerates
  `docs/screenshots/` from the demo data.
- **The emoji table**: `scripts/emoji_codes.py` (the one script that downloads anything; run it by hand).
- **The changelog.** Add a line under `[Unreleased]` in `CHANGELOG.md` for anything a user would notice.

## Commits and pull requests

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):
`type(scope): description`, in the imperative, with the why in the body. Types are `feat`, `fix`, `docs`, `test`,
`refactor`, `perf`, `build`, `ci` and `chore`. Scopes seen in the history: `ui`, `cli`, `auth`, `backend` and `remote`
(the files fetched from GitHub).

```
fix(ui): say at once when a followed card link is archived
```

One change per pull request, with the tests passing and `ruff check .` clean. The pull request template asks what and
why, how you tested it, and for a changelog line.

## Where things live

[docs/architecture.md](docs/architecture.md) maps the code and says how to add a feature (a view, a key, a palette
command). [docs/remote.md](docs/remote.md) describes the files the app fetches from GitHub.
[docs/releasing.md](docs/releasing.md) is for the maintainer. [docs/tui-designs.md](docs/tui-designs.md) holds the
interface designs, built and proposed.
