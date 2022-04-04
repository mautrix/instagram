# mautrix-instagram - A Matrix-Instagram puppeting bridge.
# Copyright (C) 2022 Tulir Asokan
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
from __future__ import annotations

from typing import AsyncIterable, Type
import json

from ..types import (
    CommandResponse,
    DMInboxResponse,
    DMThreadResponse,
    ShareVoiceResponse,
    Thread,
    ThreadAction,
    ThreadItem,
    ThreadItemType,
)
from .base import BaseAndroidAPI, T


class ThreadAPI(BaseAndroidAPI):
    async def get_inbox(
        self,
        cursor: str | None = None,
        seq_id: str | None = None,
        message_limit: int = 10,
        limit: int = 20,
        pending: bool = False,
        direction: str = "older",
    ) -> DMInboxResponse:
        query = {
            "visual_message_return_type": "unseen",
            "cursor": cursor,
            "direction": direction if cursor else None,
            "seq_id": seq_id,
            "thread_message_limit": message_limit,
            "persistentBadging": "true",
            "limit": limit,
        }
        inbox_type = "pending_inbox" if pending else "inbox"
        return await self.std_http_get(
            f"/api/v1/direct_v2/{inbox_type}/", query=query, response_type=DMInboxResponse
        )

    async def iter_inbox(
        self, start_at: DMInboxResponse | None = None, message_limit: int = 10
    ) -> AsyncIterable[Thread]:
        if start_at:
            cursor = start_at.inbox.oldest_cursor
            seq_id = start_at.seq_id
            has_more = start_at.inbox.has_older
            for thread in start_at.inbox.threads:
                yield thread
        else:
            cursor = None
            seq_id = None
            has_more = True
        while has_more:
            resp = await self.get_inbox(message_limit=message_limit, cursor=cursor, seq_id=seq_id)
            seq_id = resp.seq_id
            cursor = resp.inbox.oldest_cursor
            has_more = resp.inbox.has_older
            for thread in resp.inbox.threads:
                yield thread

    async def get_thread(
        self,
        thread_id: str,
        cursor: str | None = None,
        limit: int = 10,
        direction: str = "older",
        seq_id: int | None = None,
    ) -> DMThreadResponse:
        query = {
            "visual_message_return_type": "unseen",
            "cursor": cursor,
            "direction": direction,
            "seq_id": seq_id,
            "limit": limit,
        }
        return await self.std_http_get(
            f"/api/v1/direct_v2/threads/{thread_id}/", query=query, response_type=DMThreadResponse
        )

    async def iter_thread(
        self, thread_id: str, seq_id: int | None = None, cursor: str | None = None
    ) -> AsyncIterable[ThreadItem]:
        has_more = True
        while has_more:
            resp = await self.get_thread(thread_id, seq_id=seq_id, cursor=cursor)
            cursor = resp.thread.oldest_cursor
            has_more = resp.thread.has_older
            for item in resp.thread.items:
                yield item

    async def create_group_thread(self, recipient_users: list[int | str]) -> Thread:
        return await self.std_http_post(
            "/api/v1/direct_v2/create_group_thread/",
            data={
                "_csrftoken": self.state.cookies.csrf_token,
                "_uuid": self.state.device.uuid,
                "_uid": self.state.cookies.user_id,
                "recipient_users": json.dumps(
                    [str(user) for user in recipient_users], separators=(",", ":")
                ),
            },
            response_type=Thread,
        )

    async def approve_thread(self, thread_id: int | str) -> None:
        await self.std_http_post(
            f"/api/v1/direct_v2/threads/{thread_id}/approve/",
            data={
                "filter": "DEFAULT",
                "_uuid": self.state.device.uuid,
            },
            raw=True,
        )

    async def approve_threads(self, thread_ids: list[int | str]) -> None:
        await self.std_http_post(
            "/api/v1/direct_v2/threads/approve_multiple/",
            data={
                "thread_ids": json.dumps(
                    [str(thread) for thread in thread_ids], separators=(",", ":")
                ),
                "folder": "",
            },
        )

    async def delete_item(self, thread_id: str, item_id: str) -> None:
        await self.std_http_post(
            f"/api/v1/direct_v2/threads/{thread_id}/items/{item_id}/delete/",
            data={"_csrftoken": self.state.cookies.csrf_token, "_uuid": self.state.device.uuid},
        )

    async def _broadcast(
        self,
        thread_id: str,
        item_type: str,
        response_type: Type[T],
        signed: bool = False,
        client_context: str | None = None,
        **kwargs,
    ) -> T:
        client_context = client_context or self.state.gen_client_context()
        form = {
            "action": ThreadAction.SEND_ITEM.value,
            "send_attribution": "direct_thread",
            "thread_ids": f"[{thread_id}]",
            "is_shh_mode": "0",
            "client_context": client_context,
            "_csrftoken": self.state.cookies.csrf_token,
            "device_id": self.state.device.id,
            "mutation_token": client_context,
            "_uuid": self.state.device.uuid,
            **kwargs,
            "offline_threading_id": client_context,
        }
        return await self.std_http_post(
            f"/api/v1/direct_v2/threads/broadcast/{item_type}/",
            data=form,
            raw=not signed,
            response_type=response_type,
        )

    async def broadcast(
        self,
        thread_id: str,
        item_type: ThreadItemType,
        signed: bool = False,
        client_context: str | None = None,
        **kwargs,
    ) -> CommandResponse:
        return await self._broadcast(
            thread_id, item_type.value, CommandResponse, signed, client_context, **kwargs
        )

    async def broadcast_audio(
        self, thread_id: str, is_direct: bool, client_context: str | None = None, **kwargs
    ) -> ShareVoiceResponse | CommandResponse:
        response_type = ShareVoiceResponse if is_direct else CommandResponse
        return await self._broadcast(
            thread_id, "share_voice", response_type, False, client_context, **kwargs
        )
