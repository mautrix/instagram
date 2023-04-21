# mautrix-instagram - A Matrix-Instagram puppeting bridge.
# Copyright (C) 2023 Tulir Asokan
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

from typing import AsyncIterable, Callable, Type
import asyncio
import json

from mauigpapi.errors.response import IGRateLimitError

from ..types import (
    CommandResponse,
    DMInboxResponse,
    DMThreadResponse,
    Thread,
    ThreadAction,
    ThreadItemType,
)
from .base import BaseAndroidAPI, T


class ThreadAPI(BaseAndroidAPI):
    async def get_inbox(
        self,
        cursor: str | None = None,
        seq_id: str | None = None,
        message_limit: int | None = 10,
        limit: int = 20,
        pending: bool = False,
        spam: bool = False,
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
            "push_disabled": "true",
            "is_prefetching": "false",
        }
        inbox_type = "inbox"
        if pending:
            inbox_type = "pending_inbox"
            if spam:
                inbox_type = "spam_inbox"
        elif not cursor:
            query["fetch_reason"] = "initial_snapshot"  # can also be manual_refresh
        headers = {
            # MainFeedFragment:feed_timeline for limit=0 cold start fetch
            "ig-client-endpoint": "DirectInboxFragment:direct_inbox",
        }
        return await self.std_http_get(
            f"/api/v1/direct_v2/{inbox_type}/", query=query, response_type=DMInboxResponse
        )

    async def iter_inbox(
        self,
        update_seq_id_and_cursor: Callable[[int, str | None], None],
        start_at: DMInboxResponse | None = None,
        local_limit: int | None = None,
        rate_limit_exceeded_backoff: float = 60.0,
    ) -> AsyncIterable[Thread]:
        thread_counter = 0
        if start_at:
            cursor = start_at.inbox.oldest_cursor
            seq_id = start_at.seq_id
            has_more = start_at.inbox.has_older
            for thread in start_at.inbox.threads:
                yield thread
                thread_counter += 1
                if local_limit and thread_counter >= local_limit:
                    return
            update_seq_id_and_cursor(seq_id, cursor)
        else:
            cursor = None
            seq_id = None
            has_more = True
        while has_more:
            try:
                resp = await self.get_inbox(cursor=cursor, seq_id=seq_id)
            except IGRateLimitError:
                self.log.warning(
                    "Fetching more threads failed due to rate limit. Waiting for "
                    f"{rate_limit_exceeded_backoff} seconds before resuming."
                )
                await asyncio.sleep(rate_limit_exceeded_backoff)
                continue
            except Exception:
                self.log.exception("Failed to fetch more threads")
                raise

            seq_id = resp.seq_id
            cursor = resp.inbox.oldest_cursor
            has_more = resp.inbox.has_older
            for thread in resp.inbox.threads:
                yield thread
                thread_counter += 1
                if local_limit and thread_counter >= local_limit:
                    return
            update_seq_id_and_cursor(seq_id, cursor)

    async def get_thread(
        self,
        thread_id: str,
        cursor: str | None = None,
        limit: int = 20,
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
        headers = {
            "ig-client-endpoint": "DirectThreadFragment:direct_thread",
            "x-ig-nav-chain": "MainFeedFragment:feed_timeline:1:cold_start::,DirectInboxFragment:direct_inbox:4:on_launch_direct_inbox::",
        }
        return await self.std_http_get(
            f"/api/v1/direct_v2/threads/{thread_id}/", query=query, response_type=DMThreadResponse
        )

    # /threads/.../get_items/ with urlencoded form body:
    # visual_message_return_type:     unseen
    # _uuid:                          device uuid
    # original_message_client_contexts:["client context"]
    # item_ids:                       [item id]

    async def get_thread_participant_requests(self, thread_id: str, page_size: int = 10):
        return await self.std_http_get(
            f"/api/v1/direct_v2/threads/{thread_id}/participant_requests/",
            query={"page_size": str(page_size)},
        )

    async def mark_seen(
        self, thread_id: str, item_id: str, client_context: str | None = None
    ) -> None:
        if not client_context:
            client_context = self.state.gen_client_context()
        data = {
            "thread_id": thread_id,
            "action": "mark_seen",
            "client_context": client_context,
            "_uuid": self.state.device.uuid,
            "offline_threading_id": client_context,
        }
        await self.std_http_post(
            f"/api/v1/direct_v2/threads/{thread_id}/items/{item_id}/seen/", data=data
        )

    async def create_group_thread(self, recipient_users: list[int | str]) -> Thread:
        return await self.std_http_post(
            "/api/v1/direct_v2/create_group_thread/",
            data={
                "_uuid": self.state.device.uuid,
                "_uid": self.state.session.ds_user_id,
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

    async def delete_item(
        self, thread_id: str, item_id: str, orig_client_context: str | None = None
    ) -> None:
        await self.std_http_post(
            f"/api/v1/direct_v2/threads/{thread_id}/items/{item_id}/delete/",
            data={
                "is_shh_mode": "0",
                "send_attribution": "direct_thread",
                "_uuid": self.state.device.uuid,
                "original_message_client_context": orig_client_context,
            },
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
            "device_id": self.state.device.id,
            "mutation_token": client_context,
            "_uuid": self.state.device.uuid,
            **kwargs,
            "offline_threading_id": client_context,
            "is_x_transport_forward": "false",
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
