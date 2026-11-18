"""Trello REST API backend (https://developer.atlassian.com/cloud/trello/rest/)."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import httpx

from tui_trello.backend import BackendError
from tui_trello.models import (
    Board,
    BoardSnapshot,
    Card,
    CardList,
    CheckItem,
    Checklist,
    Comment,
    Label,
    Member,
    Notification,
    WorkSnapshot,
)

API_ROOT = "https://api.trello.com/1"

CHECK_ITEM_FIELDS = "name,state,pos"

CARD_FIELDS = "name,desc,idList,idBoard,labels,idMembers,due,dueComplete,pos,url,dateLastActivity,badges"


class TrelloBackend:
    def __init__(self, auth: httpx.Auth, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        """`auth` comes from `tui_trello.auth.request_auth`: `OAuth2Auth`, or `TokenAuth` after `login --token`."""
        self._http = httpx.AsyncClient(base_url=API_ROOT, auth=auth, timeout=20, transport=transport)

    async def _request(self, method: str, path: str, *, body: dict[str, Any] | None = None, **params: Any) -> Any:
        """`params` go in the query string; `body` is sent as JSON, for text too long for a URL."""
        try:
            response = await self._http.request(method, path, params=params, json=body)
        except httpx.HTTPError as exc:
            raise BackendError(f"Could not reach Trello: {exc}") from exc
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
            raise BackendError(f"Trello returned {response.status_code} for {path}: {response.text[:200]}")
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
        data = await self._request("GET", f"/cards/{card_id}/actions", filter="commentCard")
        return [Comment.from_api(c) for c in data]  # Trello returns newest first

    async def move_card(self, card: Card, list_id: str, pos: str = "top") -> Card:
        data = await self._request("PUT", f"/cards/{card.id}", idList=list_id, pos=pos, fields=CARD_FIELDS)
        return Card.from_api(data)

    async def add_comment(self, card_id: str, text: str) -> Comment:
        return Comment.from_api(await self._request("POST", f"/cards/{card_id}/actions/comments", text=text))

    async def set_description(self, card: Card, desc: str) -> Card:
        data = await self._request("PUT", f"/cards/{card.id}", body={"desc": desc}, fields=CARD_FIELDS)
        return Card.from_api(data)

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

    async def notifications(self) -> list[Notification]:
        data = await self._request("GET", "/members/me/notifications", limit=50, fields="type,unread,date,data",
                                   memberCreator_fields="fullName,username")
        return [Notification.from_api(n) for n in data]  # newest first

    async def mark_notifications_read(self, ids: list[str]) -> None:
        await asyncio.gather(*(self._request("PUT", f"/notifications/{id_}", unread="false") for id_ in ids))

    async def mark_all_notifications_read(self) -> None:
        await self._request("POST", "/notifications/all/read")  # all of them, not only the 50 the app fetched

    async def aclose(self) -> None:
        await self._http.aclose()
