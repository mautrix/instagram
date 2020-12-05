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
from typing import List, Any, Dict, Optional

from attr import dataclass
from mautrix.types import SerializableAttrs

from .account import BaseResponseUser
from .thread import ThreadItem


@dataclass
class DirectInboxUser(BaseResponseUser, SerializableAttrs['DirectInboxViewer']):
    interop_messaging_user_fbid: int
    is_using_unified_inbox_for_direct: bool


@dataclass
class DirectInboxCursor(SerializableAttrs['DirectInboxCursor']):
    cursor_timestamp_seconds: int
    cursor_thread_v2_id: int


@dataclass
class DirectInboxThreadTheme(SerializableAttrs['DirectInboxThreadTheme']):
    id: str


@dataclass
class UserLastSeenAt(SerializableAttrs['UserLastSeenAt']):
    timestamp: str
    item_id: str
    shh_seen_state: Dict[str, Any]


@dataclass
class DirectInboxThread(SerializableAttrs['DirectInboxThread']):
    thread_id: str
    thread_v2_id: str

    users: List[DirectInboxUser]
    inviter: BaseResponseUser
    admin_user_ids: List[int]

    last_activity_at: int
    muted: bool
    is_pin: bool
    named: bool
    canonical: bool
    pending: bool
    archived: bool
    # TODO enum? even groups seem to be "private"
    thread_type: str
    viewer_id: int
    thread_title: str
    folder: int
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

    theme: DirectInboxThreadTheme
    last_seen_at: Dict[int, UserLastSeenAt]

    newest_cursor: str
    oldest_cursor: str
    next_cursor: str
    prev_cursor: str
    last_permanent_item: ThreadItem
    items: List[ThreadItem]


@dataclass
class DirectInbox(SerializableAttrs['DirectInbox']):
    threads: List[DirectInboxThread]
    has_older: bool
    unseen_count: int
    unseen_count_ts: int
    prev_cursor: DirectInboxCursor
    next_cursor: DirectInboxCursor
    blended_inbox_enabled: bool


@dataclass
class DirectInboxResponse(SerializableAttrs['DirectInboxFeedResponse']):
    status: str
    seq_id: int
    snapshot_at_ms: int
    pending_requests_total: int
    has_pending_top_requests: bool
    viewer: DirectInboxUser
    inbox: DirectInbox
    # TODO type
    most_recent_inviter: Any = None
