# mautrix-instagram - A Matrix-Instagram puppeting bridge.
# Copyright (C) 2020 Tulir Asokan
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
from typing import Optional, AsyncIterable

from .base import BaseAndroidAPI
from ..types import DMInboxResponse, DMThreadResponse, Thread, ThreadItem


class ThreadAPI(BaseAndroidAPI):
    async def get_inbox(self, cursor: Optional[str] = None, seq_id: Optional[str] = None,
                        message_limit: int = 10, limit: int = 20, pending: bool = False,
                        direction: str = "older") -> DMInboxResponse:
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
        return await self.std_http_get(f"/api/v1/direct_v2/{inbox_type}/", query=query,
                                       response_type=DMInboxResponse)

    async def iter_inbox(self, cursor: Optional[str] = None, seq_id: Optional[str] = None,
                         message_limit: int = 10) -> AsyncIterable[Thread]:
        has_more = True
        while has_more:
            resp = await self.get_inbox(message_limit=message_limit, cursor=cursor, seq_id=seq_id)
            seq_id = resp.seq_id
            cursor = resp.inbox.prev_cursor
            has_more = resp.inbox.has_older
            for thread in resp.inbox.threads:
                yield thread

    async def get_thread(self, thread_id: str,  cursor: Optional[str] = None, limit: int = 10,
                         direction: str = "older", seq_id: Optional[int] = None
                         ) -> DMThreadResponse:
        query = {
            "visual_message_return_type": "unseen",
            "cursor": cursor,
            "direction": direction,
            "seq_id": seq_id,
            "limit": limit,
        }
        return await self.std_http_get(f"/api/v1/direct_v2/threads/{thread_id}/", query=query,
                                       response_type=DMThreadResponse)

    async def iter_thread(self, thread_id: str, seq_id: Optional[int] = None,
                          cursor: Optional[str] = None) -> AsyncIterable[ThreadItem]:
        has_more = True
        while has_more:
            resp = await self.get_thread(thread_id, seq_id=seq_id, cursor=cursor)
            cursor = resp.thread.oldest_cursor
            has_more = resp.thread.has_older
            for item in resp.thread.items:
                yield item

    async def delete_item(self, thread_id: str, item_id: str) -> None:
        await self.std_http_post(f"/api/v1/direct_v2/threads/{thread_id}/items/{item_id}/delete/",
                                 data={"_csrftoken": self.state.cookies.csrf_token,
                                       "_uuid": self.state.device.uuid})
