"""Trello REST API backend (https://developer.atlassian.com/cloud/trello/rest/)."""

from __future__ import annotations

import asyncio
import mimetypes
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx

from tui_trello.auth import TokenAuth
from tui_trello.backend import BackendError
from tui_trello.models import (
    Attachment,
    Board,
    BoardSnapshot,
    Card,
    CardList,
    CardPreview,
    CheckItem,
    Checklist,
    Comment,
    Label,
    Member,
    Notification,
    Reaction,
    WorkSnapshot,
)

API_ROOT = "https://api.trello.com/1"

CHECK_ITEM_FIELDS = "name,state,pos"

ATTACHMENT_FIELDS = "name,url,isUpload,bytes,mimeType,date,fileName"

CARD_FIELDS = "name,desc,idList,idBoard,labels,idMembers,due,dueComplete,pos,url,dateLastActivity,badges,closed"

# Errors raised before any of the request went out: Trello can't have acted on it. Any other (a read timeout, a
# dropped connection) may come after Trello has.
NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.UnsupportedProtocol,
            httpx.LocalProtocolError, httpx.ProxyError, httpx.InvalidURL)


class TrelloBackend:
    def __init__(self, auth: httpx.Auth, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        """`auth` comes from `tui_trello.auth.request_auth`: `OAuth2Auth`, or `TokenAuth` after `login --token`."""
        self._auth = auth
        self._http = httpx.AsyncClient(base_url=API_ROOT, auth=auth, timeout=20, transport=transport)

    async def _request(self, method: str, path: str, *, body: dict[str, Any] | None = None,
                       files: dict[str, Any] | None = None, **params: Any) -> Any:
        """`params` go in the query string; `body` is sent as JSON, for text too long for a URL; `files` as a
        multipart upload, given longer to send."""
        timeout = httpx.Timeout(20, write=600) if files else httpx.USE_CLIENT_DEFAULT
        try:
            response = await self._http.request(method, path, params=params, json=body, files=files, timeout=timeout)
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            # Only an error before the request went out is sure not to have reached Trello.
            unsure = not isinstance(exc, NOT_SENT)
            raise BackendError(f"Could not reach Trello: {exc}", unsure=unsure) from exc
        if response.status_code in (400, 401) and "invalid key" in response.text:
            raise BackendError("Trello doesn't recognise the app's API key; it may have been deleted or regenerated. "
                               "Set a current one as APP_API_KEY in tui_trello/auth.py (or api_key in the config).")
        if response.status_code == 403 and "unauthorized notification" in response.text:
            raise BackendError("Marking notifications read needs a permission your login doesn't have yet. "
                               "Run `tui-trello login` again.")
        if response.status_code == 401 and "permission" in response.text:
            raise BackendError(f"You don't have access to that on Trello ({path}).")
        if response.status_code == 401:
            raise BackendError("Trello rejected the credentials (401). Run `tui-trello login` again.")
        if response.is_error:
            raise BackendError(f"Trello returned {response.status_code} for {path}: {response.text[:200]}",
                               unsure=response.is_server_error)
        return response.json()

    async def me(self) -> Member:
        return Member.from_api(await self._request("GET", "/members/me", fields="fullName,username"))

    async def boards(self) -> list[Board]:
        data = await self._request("GET", "/members/me/boards", filter="open", fields="name,url,starred")
        return sorted((Board.from_api(b) for b in data), key=lambda b: (not b.starred, b.name.lower()))

    async def board_snapshot(self, board_id: str) -> BoardSnapshot:
        board, lists, cards, members, labels = await asyncio.gather(
            self._request("GET", f"/boards/{board_id}", fields="name,url,starred"),
            self._request("GET", f"/boards/{board_id}/lists", filter="open", fields="name,idBoard,pos"),
            self._request("GET", f"/boards/{board_id}/cards", filter="open", fields=CARD_FIELDS),
            self._request("GET", f"/boards/{board_id}/members", fields="fullName,username"),
            self._request("GET", f"/boards/{board_id}/labels", fields="name,color"),
        )
        # "open" cards include ones in archived lists, which Trello's own board hides; so do we.
        open_lists = {lst["id"] for lst in lists}
        return BoardSnapshot(
            board=Board.from_api(board),
            lists=sorted((CardList.from_api(lst) for lst in lists), key=lambda lst: lst.pos),
            cards=[Card.from_api(c) for c in cards if c["idList"] in open_lists],
            members={m["id"]: Member.from_api(m) for m in members},
            labels=[Label.from_api(label) for label in labels],
        )

    async def card(self, card_id: str) -> Card:
        # One request: the nested list says whether it is archived, which the card itself doesn't.
        data = await self._request("GET", f"/cards/{card_id}", fields=CARD_FIELDS, list="true", list_fields="closed")
        return Card.from_api(data)

    async def card_preview(self, card_id: str) -> CardPreview:
        """A card, its list, board and members, for showing it without loading its board. Archived cards are
        returned, marked."""
        card = await self._request(
            "GET", f"/cards/{card_id}", fields=CARD_FIELDS, list="true", list_fields="name,closed",
            board="true", board_fields="name,closed", members="true", member_fields="fullName,username")
        card_list, board, members = card["list"], card["board"], card["members"]
        archived = next((what for what, data in (("card", card), ("list", card_list), ("board", board))
                         if data.get("closed")), "")
        return CardPreview(Card.from_api(card), f"{board['name']} › {card_list['name']}",
                           {m["id"]: Member.from_api(m) for m in members}, archived)

    async def board(self, board_id: str) -> Board:
        return Board.from_api(await self._request("GET", f"/boards/{board_id}", fields="name,url,starred"))

    async def my_work(self) -> WorkSnapshot:
        me, cards, boards = await asyncio.gather(
            self._request("GET", "/members/me", fields="fullName,username"),
            self._request("GET", "/members/me/cards", filter="open", fields=CARD_FIELDS),
            self._request("GET", "/members/me/boards", filter="open", fields="name,url,starred", lists="open",
                          list_fields="name,idBoard,pos"),
        )
        lists = {lst["id"]: CardList.from_api(lst) for b in boards for lst in b.get("lists") or ()}
        return WorkSnapshot(
            me=Member.from_api(me),
            cards=[Card.from_api(c) for c in cards if c["idList"] in lists],  # not in archived lists or closed boards
            boards={b["id"]: Board.from_api(b) for b in boards},
            lists=lists,
        )

    async def comments(self, card_id: str) -> list[Comment]:
        # reactions=true isn't in Trello's API reference, but it puts each comment's reactions in, as trello.com
        # asks for them; without it they'd take a request per comment.
        data = await self._request("GET", f"/cards/{card_id}/actions", filter="commentCard", reactions="true")
        return [Comment.from_api(c) for c in data]  # Trello returns newest first

    async def move_card(self, card: Card, list_id: str, pos: str = "top") -> Card:
        data = await self._request("PUT", f"/cards/{card.id}", idList=list_id, pos=pos, fields=CARD_FIELDS)
        return Card.from_api(data)

    async def create_card(self, list_id: str, name: str, desc: str = "", *, pos: str = "bottom") -> Card:
        body = {"idList": list_id, "name": name, "pos": pos, **({"desc": desc} if desc else {})}
        return Card.from_api(await self._request("POST", "/cards", body=body, fields=CARD_FIELDS))

    async def add_comment(self, card_id: str, text: str) -> Comment:
        return Comment.from_api(await self._request("POST", f"/cards/{card_id}/actions/comments", text=text))

    async def set_description(self, card: Card, desc: str) -> Card:
        data = await self._request("PUT", f"/cards/{card.id}", body={"desc": desc}, fields=CARD_FIELDS)
        return Card.from_api(data)

    async def add_reaction(self, comment_id: str, short_name: str) -> Reaction:
        data = await self._request("POST", f"/actions/{comment_id}/reactions", body={"shortName": short_name})
        return Reaction.from_api(data)

    async def remove_reaction(self, comment_id: str, reaction_id: str) -> None:
        await self._request("DELETE", f"/actions/{comment_id}/reactions/{reaction_id}")

    async def labels(self, board_id: str) -> list[Label]:
        data = await self._request("GET", f"/boards/{board_id}/labels", fields="name,color")
        return [Label.from_api(label) for label in data]

    async def members(self, board_id: str) -> list[Member]:
        data = await self._request("GET", f"/boards/{board_id}/members", fields="fullName,username")
        return [Member.from_api(member) for member in data]

    async def add_label(self, card: Card, label: Label) -> Card:
        await self._request("POST", f"/cards/{card.id}/idLabels", value=label.id)
        return replace(card, labels=(*card.labels, label))

    async def remove_label(self, card: Card, label: Label) -> Card:
        await self._request("DELETE", f"/cards/{card.id}/idLabels/{label.id}")
        return replace(card, labels=tuple(lb for lb in card.labels if lb.id != label.id))

    async def create_label(self, board_id: str, name: str, color: str | None) -> Label:
        params = {"name": name, "idBoard": board_id}
        if color:
            params["color"] = color
        return Label.from_api(await self._request("POST", "/labels", **params))

    async def checklists(self, card_id: str) -> list[Checklist]:
        data = await self._request("GET", f"/cards/{card_id}/checklists", fields="name,pos",
                                   checkItem_fields=CHECK_ITEM_FIELDS)
        return sorted((Checklist.from_api(c) for c in data), key=lambda c: c.pos)

    async def set_check_item(self, card_id: str, item: CheckItem, checked: bool) -> CheckItem:
        data = await self._request("PUT", f"/cards/{card_id}/checkItem/{item.id}",
                                   state="complete" if checked else "incomplete")
        return CheckItem.from_api(data)

    async def add_check_item(self, checklist_id: str, name: str) -> CheckItem:
        data = await self._request("POST", f"/checklists/{checklist_id}/checkItems", name=name, pos="bottom")
        return CheckItem.from_api(data)

    async def create_checklist(self, card_id: str, name: str) -> Checklist:
        return Checklist.from_api(await self._request("POST", f"/cards/{card_id}/checklists", name=name))

    async def attachments(self, card_id: str) -> list[Attachment]:
        data = await self._request("GET", f"/cards/{card_id}/attachments", fields=ATTACHMENT_FIELDS)
        return [Attachment.from_api(a) for a in data]

    async def attach_file(self, card_id: str, path: Path) -> Attachment:
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise BackendError(f"Could not read {path}: {exc.strerror}") from exc
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = await self._request("POST", f"/cards/{card_id}/attachments", files={"file": (path.name, content, mime)},
                                   name=path.name, mimeType=mime)
        return Attachment.from_api(data)

    async def attach_link(self, card_id: str, url: str, name: str = "") -> Attachment:
        params = {"url": url, **({"name": name} if name else {})}
        return Attachment.from_api(await self._request("POST", f"/cards/{card_id}/attachments", **params))

    async def download_attachment(self, attachment: Attachment, dest: Path) -> None:
        """Save an uploaded file. Trello's download links take the older key and token, in an OAuth header; no
        OAuth 2.0 scope covers them, so with the browser login they answer 401."""
        headers = {}
        if isinstance(self._auth, TokenAuth):
            key, token = self._auth.params["key"], self._auth.params["token"]
            headers["Authorization"] = f'OAuth oauth_consumer_key="{key}", oauth_token="{token}"'
        try:
            async with self._http.stream("GET", attachment.url, headers=headers, timeout=httpx.Timeout(20, read=600),
                                         follow_redirects=True) as response:
                if response.status_code in (401, 403):
                    raise BackendError("Trello doesn't let the browser login download attachments. Open it in the "
                                       "web browser instead (enter), or log in with `tui-trello login --token` to "
                                       "save files from the app.")
                if response.is_error:
                    raise BackendError(f"Trello returned {response.status_code} for {attachment.name}")
                with dest.open("wb") as out:
                    async for chunk in response.aiter_bytes():
                        out.write(chunk)
        except httpx.HTTPError as exc:
            dest.unlink(missing_ok=True)
            raise BackendError(f"Could not download {attachment.name}: {exc}") from exc
        except BaseException:
            dest.unlink(missing_ok=True)  # no half-written file left behind
            raise

    async def notifications(self) -> list[Notification]:
        # reactions: on a reactionAdded notification, the emoji given. Unlike data, it only comes if named here.
        data = await self._request("GET", "/members/me/notifications", limit=50,
                                   fields="type,unread,date,data,idMemberCreator,reactions",
                                   memberCreator_fields="fullName,username")
        return [Notification.from_api(n) for n in data]  # newest first

    async def mark_notifications_read(self, ids: list[str]) -> None:
        await asyncio.gather(*(self._request("PUT", f"/notifications/{id_}", unread="false") for id_ in ids))

    async def mark_all_notifications_read(self) -> None:
        await self._request("POST", "/notifications/all/read")  # all of them, not only the 50 the app fetched

    async def aclose(self) -> None:
        await self._http.aclose()
