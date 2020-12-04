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
from typing import Optional

from .base import BaseAndroidAPI
from ..types import DirectInboxResponse


class DirectInboxAPI(BaseAndroidAPI):
    async def direct_inbox(self, cursor: Optional[str] = None, seq_id: Optional[str] = None,
                           thread_message_limit: int = 10, limit: int = 20) -> DirectInboxResponse:
        query = {
            "visual_message_return_type": "unseen",
            "cursor": cursor,
            "direction": "older" if cursor else None,
            "seq_id": seq_id,
            "thread_message_limit": thread_message_limit,
            "persistentBadging": "true",
            "limit": limit,
        }
        return await self.std_http_get("/api/v1/direct_v2/inbox/", query=query,
                                       response_type=DirectInboxResponse)
