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
from typing import Any, Dict, List, Optional

from attr import dataclass
import attr

from mautrix.types import SerializableAttrs

from .account import BaseResponseUser
from .thread_item import ThreadItem


@dataclass
class ThreadUser(BaseResponseUser, SerializableAttrs):
    interop_messaging_user_fbid: int
    interop_user_type: Optional[int] = None
    is_using_unified_inbox_for_direct: Optional[bool] = None


@dataclass
class ThreadTheme(SerializableAttrs):
    id: str


@dataclass
class ThreadUserLastSeenAt(SerializableAttrs):
    timestamp: str
    item_id: str
    shh_seen_state: Dict[str, Any]


@dataclass(kw_only=True)
class Thread(SerializableAttrs):
    thread_id: str
    thread_v2_id: str

    users: List[ThreadUser]
    # left_users: List[TODO]
    inviter: Optional[BaseResponseUser] = None
    admin_user_ids: List[int]

    last_activity_at: int
    muted: bool
    # This seems to be missing in some cases
    is_pin: bool = False
    named: bool
    canonical: bool
    pending: bool
    archived: bool
    # TODO enum? even groups seem to be "private"
    thread_type: str
    viewer_id: int
    thread_title: str
    # This seems to be missing in some cases
    folder: Optional[int] = None
    vc_muted: bool
    is_group: bool
    mentions_muted: bool
    approval_required_for_new_members: bool
    input_mode: int
    business_thread_folder: int
    read_state: int
    last_non_sender_item_at: int
    assigned_admin_id: int
    shh_mode_enabled: bool
    is_close_friend_thread: bool
    has_older: bool
    has_newer: bool

    theme: ThreadTheme
    last_seen_at: Dict[str, ThreadUserLastSeenAt] = attr.ib(factory=lambda: {})

    newest_cursor: Optional[str] = None
    oldest_cursor: Optional[str] = None
    next_cursor: Optional[str] = None
    prev_cursor: Optional[str] = None
    last_permanent_item: Optional[ThreadItem] = None
    items: List[ThreadItem]

    # These might only be in single thread requests and not inbox
    valued_request: Optional[bool] = None
    pending_score: Optional[bool] = None
