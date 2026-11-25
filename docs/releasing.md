# Releasing

For the maintainer. A release is a version bump, a changelog section and a tag; the `release` workflow does the rest.

## One-time setup

- **PyPI**: an account with two-factor authentication, and a *pending trusted publisher* for the project `tui-trello`:
  owner `philjnicholls`, repository `tui-trello`, workflow `release.yml`, environment `pypi`. No token or password is
  stored anywhere: PyPI trusts the workflow's identity.
- **GitHub**: an environment named `pypi` (Settings, Environments) with you as a required reviewer, so every publish
  waits for your approval.

## Making a release

1. Set `__version__` in `src/tui_trello/__init__.py` (the only place the version is written; `pyproject.toml` reads
   it).
2. In `CHANGELOG.md`, move the `[Unreleased]` notes under a new `## [X.Y.Z] - YYYY-MM-DD` heading, leaving
   `[Unreleased]` empty, and update the link references at the foot.
3. Check: `venv/bin/pytest`, `venv/bin/ruff check .`, and `python scripts/release_notes.py X.Y.Z` prints the notes.
4. Commit: `chore(release): vX.Y.Z`.
5. Tag and push: `git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin main vX.Y.Z`.
6. The workflow (`.github/workflows/release.yml`) fails unless the tag matches `__version__`, then runs the tests,
   builds the wheel and sdist, and runs `twine check --strict`. Approve the `pypi` environment when GitHub asks; it
   publishes to PyPI and creates the GitHub Release with the changelog section as its notes.
7. Check https://pypi.org/project/tui-trello/ and the Release page, and try `pipx install tui-trello` in a fresh
   shell.

If a release fails half way, note that a version uploaded to PyPI can never be uploaded again, even if deleted: fix
the problem and release the next patch version.

## The Trello app registrations

- **OAuth client** (the default `tui-trello login`): `OAUTH_CLIENT_ID` in `src/tui_trello/auth.py`, set up at
  https://trello.com/apps/admin with the callback URL `http://127.0.0.1:8765/callback` and the scopes in
  `auth.SCOPES`. Changing the client ID logs every user out, so it needs a release.

## Posting news

Add a section at the top of `remote/newsfeed.md` on `main`:

```markdown
## 2026-12-01: A short title

One or two sentences of Markdown.
```

Keep it short, and don't rely on links: they are not clickable. It reaches users within an hour of their next start.
An item's identity is its heading line, so editing the heading makes it show as new again for everyone who has seen it,
while editing only the body doesn't. `tests/test_remote.py::test_published_files_are_valid` checks the file in CI.
