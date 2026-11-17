from __future__ import annotations

import argparse
import asyncio
import sys

from tui_trello.config import LAYOUTS, Settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tui-trello", description="A keyboard-first terminal client for Trello.")
    parser.add_argument("--demo", action="store_true", help="use built-in sample data instead of Trello")
    parser.add_argument("--board", help="board id or short link to open")
    parser.add_argument("--layout", choices=LAYOUTS, help="screen to start on")
    commands = parser.add_subparsers(dest="command", metavar="{login,logout}")
    login_parser = commands.add_parser("login", help="authorise tui-trello in the browser and save the token")
    login_parser.add_argument("--token", action="store_true",
                              help="use Trello's older flow: paste a long-lived token for the app's API key")
    commands.add_parser("logout", help="forget the saved token")
    args = parser.parse_args(argv)

    settings = Settings.load()
    if args.command == "login":
        sys.exit(cmd_login(settings, token=args.token))
    if args.command == "logout":
        sys.exit(cmd_logout())

    if args.board:
        settings.default_board = args.board
    if args.layout:
        settings.layout = args.layout

    if args.demo:
        from tui_trello.backend.demo import DemoBackend

        backend = DemoBackend()
        settings.default_board = settings.default_board if args.board else "b-product"
    else:
        backend = trello_backend(settings)

    from tui_trello.ui.app import TrelloApp
    from tui_trello.ui.bidi import explicit_mode

    # The app lays out RTL text itself; stop bidi terminals reordering whole screen lines (see ui/bidi.py).
    with explicit_mode(sys.__stdout__ if sys.__stdout__ and sys.__stdout__.isatty() else None):
        TrelloApp(backend, settings).run()


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


def cmd_logout() -> int:
    from tui_trello.auth import credentials_path, delete_credentials

    if delete_credentials():
        print(f"Removed {credentials_path()}. To revoke access too, see https://trello.com/my/account (Applications).")
    else:
        print("Not logged in.")
    return 0
