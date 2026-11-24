from __future__ import annotations

import argparse
import asyncio
import sys

from tui_trello import links
from tui_trello.config import LAYOUTS, Settings

OPENABLE_KINDS = ("board", "card", "comment", "attachment")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tui-trello", description="A keyboard-first terminal client for Trello.")
    parser.add_argument("--demo", action="store_true", help="use built-in sample data instead of Trello")
    start = parser.add_mutually_exclusive_group()
    start.add_argument("--board", help="board id or short link to open")
    start.add_argument("--open", metavar="URL",
                       help="open this Trello board, card, comment or attachment link at start-up "
                            "(quote it: 'https://trello.com/c/...#comment-...')")
    parser.add_argument("--layout", choices=LAYOUTS, help="screen to start on")
    commands = parser.add_subparsers(dest="command", metavar="{login,logout,keys}")
    login_parser = commands.add_parser("login", help="authorise tui-trello in the browser and save the token")
    login_parser.add_argument("--token", action="store_true",
                              help="use Trello's older flow: paste a long-lived token for the app's API key")
    commands.add_parser("logout", help="forget the saved token")
    commands.add_parser("keys", help="list every key action and its key, and check [keys] in config.toml")
    args = parser.parse_args(argv)
    if args.open is not None and args.command:
        parser.error("--open can't be used with login, logout or keys")

    settings = Settings.load()
    if args.command == "login":
        sys.exit(cmd_login(settings, token=args.token))
    if args.command == "logout":
        sys.exit(cmd_logout())
    if args.command == "keys":
        sys.exit(cmd_keys(settings))

    if args.board:
        settings.default_board = args.board
    if args.layout:
        settings.layout = args.layout
    elif args.open is not None:
        settings.layout = "browser"  # a card opens over its board, whatever config.toml starts on

    from tui_trello.drafts import Drafts, drafts_path

    if args.demo:
        from tui_trello.backend.demo import DemoBackend

        backend = DemoBackend()
        if args.open is not None:
            check_open_url(parser, args.open, getattr(backend, "link_hosts", links.TRELLO_HOSTS))
        settings.default_board = settings.default_board if args.board else "b-product"
        drafts = Drafts(drafts_path().with_name("demo-drafts.json"))  # not mixed in with real cards' drafts
    else:
        if args.open is not None:  # checked before trello_backend can start a login
            check_open_url(parser, args.open, links.TRELLO_HOSTS)
        backend = trello_backend(settings)
        drafts = Drafts()

    from tui_trello.ui.app import TrelloApp
    from tui_trello.ui.bidi import explicit_mode

    # The app lays out RTL text itself; stop bidi terminals reordering whole screen lines (see ui/bidi.py).
    with explicit_mode(sys.__stdout__ if sys.__stdout__ and sys.__stdout__.isatty() else None):
        TrelloApp(backend, settings, drafts, open_url=args.open or "").run()


def check_open_url(parser: argparse.ArgumentParser, url: str, hosts: frozenset[str]) -> None:
    """Stop with a usage error unless `url` is a link the app can open."""
    if links.parse(url, hosts).kind not in OPENABLE_KINDS:
        parser.error(f"--open: not a Trello board, card, comment or attachment link: {url!r}")


def api_key(settings: Settings) -> str:
    from tui_trello.auth import APP_API_KEY

    return settings.api_key or APP_API_KEY


def trello_backend(settings: Settings):
    from tui_trello.auth import LegacyToken, load_credentials, request_auth
    from tui_trello.backend.trello import TrelloBackend

    # A token set by hand (TRELLO_TOKEN or [trello] token) wins over the saved login, as config.py documents.
    credentials = LegacyToken(settings.token) if settings.token else load_credentials()
    if credentials is None:
        print("Not logged in to Trello yet.")
        if cmd_login(settings):
            sys.exit(1)
        return trello_backend(settings)
    return TrelloBackend(request_auth(credentials, api_key(settings)))


def cmd_login(settings: Settings, token: bool = False) -> int:
    from tui_trello.auth import (
        LoginError,
        delete_credentials,
        login_oauth2,
        login_token,
        request_auth,
        save_credentials,
        whoami,
    )

    async def run():
        if token:
            credentials = await login_token(api_key(settings))
        else:
            credentials = await login_oauth2(port=settings.oauth_port)
        # Save before checking, so a refresh during the check doesn't leave a used refresh token on disk.
        save_credentials(credentials)
        try:
            return await whoami(request_auth(credentials, api_key(settings)))
        except BaseException:  # LoginError, or interrupted: don't keep credentials that weren't checked
            delete_credentials()
            raise

    try:
        name = asyncio.run(run())
    except LoginError as exc:
        print(f"Login failed: {exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        return 130
    print(f"Logged in as {name}.")
    return 0


def cmd_keys(settings: Settings) -> int:
    """Print every key id with the key in use, as a `[keys]` table to copy from; the problems with `[keys]` go to
    stderr, and the status is 1 if there are any."""
    from tui_trello.ui.keymap import KeyMap

    keymap = KeyMap.build(settings.keys)
    print(keymap.listing(), end="")
    problems = settings.warnings + keymap.warnings
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


def cmd_logout() -> int:
    from tui_trello.auth import credentials_path, delete_credentials

    if delete_credentials():
        print(f"Removed {credentials_path()}. To revoke access too, see https://trello.com/my/account (Applications).")
    else:
        print("Not logged in.")
    return 0
