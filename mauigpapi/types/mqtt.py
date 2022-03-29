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
from typing import Any, List, Optional, Union
import json

from attr import dataclass
import attr

from mautrix.types import JSON, SerializableAttrs, SerializableEnum

from .account import BaseResponseUser
from .thread import Thread
from .thread_item import ThreadItem


class Operation(SerializableEnum):
    ADD = "add"
    REPLACE = "replace"
    REMOVE = "remove"


class ThreadAction(SerializableEnum):
    SEND_ITEM = "send_item"
    PROFILE = "profile"
    MARK_SEEN = "mark_seen"
    MARK_VISUAL_ITEM_SEEN = "mark_visual_item_seen"
    INDICATE_ACTIVITY = "indicate_activity"


class ReactionStatus(SerializableEnum):
    CREATED = "created"
    DELETED = "deleted"


class TypingStatus(SerializableEnum):
    OFF = 0
    TEXT = 1
    VISUAL = 2


@dataclass(kw_only=True)
class CommandResponsePayload(SerializableAttrs):
    client_context: Optional[str] = None
    item_id: Optional[str] = None
    timestamp: Optional[str] = None
    thread_id: Optional[str] = None
    message: Optional[str] = None


@dataclass(kw_only=True)
class CommandResponse(SerializableAttrs):
    action: str
    status: str
    status_code: Optional[str] = None
    payload: CommandResponsePayload


@dataclass(kw_only=True)
class IrisPayloadData(SerializableAttrs):
    op: Operation
    path: str
    value: str


@dataclass(kw_only=True)
class IrisPayload(SerializableAttrs):
    data: List[IrisPayloadData]
    message_type: int
    seq_id: int
    event: str = "patch"
    mutation_token: Optional[str] = None
    realtime: Optional[bool] = None
    sampled: Optional[bool] = None


@dataclass(kw_only=True)
class MessageSyncMessage(ThreadItem, SerializableAttrs):
    path: str
    op: Operation = Operation.ADD

    # These come from parsing the path
    admin_user_id: Optional[int] = None
    approval_required_for_new_members: Optional[bool] = None
    has_seen: Optional[int] = None
    thread_id: Optional[str] = None


@dataclass(kw_only=True)
class MessageSyncEvent(SerializableAttrs):
    iris: IrisPayload
    message: MessageSyncMessage


@dataclass
class ThreadSyncEvent(Thread, SerializableAttrs):
    path: str
    op: Operation


@dataclass(kw_only=True)
class PubsubPublishMetadata(SerializableAttrs):
    publish_time_ms: str
    topic_publish_id: int


@dataclass(kw_only=True)
class PubsubBasePayload(SerializableAttrs):
    lazy: Optional[bool] = False
    event: str = "patch"
    publish_metadata: Optional[PubsubPublishMetadata] = None
    num_endpoints: Optional[int] = None


@dataclass(kw_only=True)
class ActivityIndicatorData(SerializableAttrs):
    timestamp: Union[int, str]
    sender_id: str
    ttl: int
    activity_status: TypingStatus

    @property
    def timestamp_ms(self) -> int:
        return int(self.timestamp) // 1000

    @classmethod
    def deserialize(cls, data: JSON) -> "ActivityIndicatorData":
        # The ActivityIndicatorData in PubsubPayloadData is actually a string,
        # so we need to unmarshal it first.
        if isinstance(data, str):
            data = json.loads(data)
        return super().deserialize(data)


@dataclass(kw_only=True)
class PubsubPayloadData(SerializableAttrs):
    double_publish: bool = attr.ib(metadata={"json": "doublePublish"})
    value: ActivityIndicatorData
    path: str
    op: Operation = Operation.ADD


@dataclass(kw_only=True)
class PubsubPayload(PubsubBasePayload, SerializableAttrs):
    data: List[PubsubPayloadData] = attr.ib(factory=lambda: [])


@dataclass(kw_only=True)
class PubsubEvent(SerializableAttrs):
    base: PubsubBasePayload
    data: PubsubPayloadData
    thread_id: str
    activity_indicator_id: str


@dataclass(kw_only=True)
class AppPresenceEvent(SerializableAttrs):
    user_id: str
    is_active: bool
    last_activity_at_ms: str
    in_threads: List[Any]


@dataclass(kw_only=True)
class AppPresenceEventPayload(SerializableAttrs):
    presence_event: AppPresenceEvent


@dataclass(kw_only=True)
class ZeroProductProvisioningEvent(SerializableAttrs):
    device_id: str
    product_name: str
    zero_provisioned_time: str


@dataclass(kw_only=True)
class RealtimeZeroProvisionPayload(SerializableAttrs):
    zero_product_provisioning_event: ZeroProductProvisioningEvent


@dataclass(kw_only=True)
class ClientConfigUpdateEvent(SerializableAttrs):
    publish_id: str
    client_config_name: str
    backing: str  # might be "QE"
    client_subscription_id: str  # should be GraphQLQueryID.clientConfigUpdate


@dataclass(kw_only=True)
class ClientConfigUpdatePayload(SerializableAttrs):
    client_config_update_event: ClientConfigUpdateEvent


# TODO figure out if these need to be separate
RealtimeDirectData = ActivityIndicatorData


@dataclass(kw_only=True)
class RealtimeDirectEvent(SerializableAttrs):
    op: Operation
    path: str
    value: RealtimeDirectData
    # Comes from the parent object
    # TODO many places have this kind of event, it's usually "patch", might need an enum
    event: Optional[str] = None
    # Parsed from path
    thread_id: Optional[str] = None
    activity_indicator_id: Optional[str] = None


@dataclass(kw_only=True)
class LiveVideoSystemComment(SerializableAttrs):
    pk: str
    created_at: int
    text: str
    user_count: int
    user: BaseResponseUser


@dataclass(kw_only=True)
class LiveVideoComment(SerializableAttrs):
    pk: str
    user_id: str
    text: str
    type: int
    created_at: int
    created_at_utc: int
    content_type: str
    status: str = "Active"
    bit_flags: int
    did_report_as_spam: bool
    inline_composer_display_condition: str
    user: BaseResponseUser


@dataclass(kw_only=True)
class LiveVideoCommentEvent(SerializableAttrs):
    client_subscription_id: str
    live_seconds_per_comment: int
    comment_likes_enabled: bool
    comment_count: int
    caption: Optional[str] = None
    caption_is_edited: bool
    has_more_comments: bool
    has_more_headload_comments: bool
    media_header_display: str
    comment_muted: int
    comments: Optional[List[LiveVideoComment]] = None
    pinned_comment: Optional[LiveVideoComment] = None
    system_comments: Optional[List[LiveVideoSystemComment]] = None


@dataclass(kw_only=True)
class LiveVideoCommentPayload(SerializableAttrs):
    live_video_comment_event: LiveVideoCommentEvent
