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
from typing import Dict, Any, List, Optional
import json

from mautrix.types import SerializableAttrs, SerializableEnum, JSON, dataclass, field

from .subscription import GraphQLQueryID

_topic_map: Dict[str, str] = {
    "/pp": "34",  # unknown
    "/ig_sub_iris": "134",
    "/ig_sub_iris_response": "135",
    "/ig_message_sync": "146",
    "/ig_send_message": "132",
    "/ig_send_message_response": "133",
    "/ig_realtime_sub": "149",
    "/pubsub": "88",
    "/t_fs": "102",  # Foreground state
    "/graphql": "9",
    "/t_region_hint": "150",
    "/mqtt_health_stats": "/mqtt_health_stats",
    "179": "179",  # also unknown
}

_reverse_topic_map: Dict[str, str] = {value: key for key, value in _topic_map.items()}


class RealtimeTopic(SerializableEnum):
    SUB_IRIS = "/ig_sub_iris"
    SUB_IRIS_RESPONSE = "/ig_sub_iris_response"
    MESSAGE_SYNC = "/ig_message_sync"
    SEND_MESSAGE = "/ig_send_message"
    SEND_MESSAGE_RESPONSE = "/ig_send_message_response"
    REALTIME_SUB = "/ig_realtime_sub"
    PUBSUB = "/pubsub"
    FOREGROUND_STATE = "/t_fs"
    GRAPHQL = "/graphql"
    REGION_HINT = "/t_region_hint"
    MQTT_HEALTH_STATS = "/mqtt_health_stats"
    UNKNOWN_PP = "/pp"
    UNKNOWN_179 = "179"

    @property
    def encoded(self) -> str:
        return _topic_map[self.value]

    @classmethod
    def decode(cls, val: str) -> 'RealtimeTopic':
        return cls(_reverse_topic_map[val])


class ThreadItemType(SerializableEnum):
    DELETION = "deletion"
    MEDIA = "media"
    TEXT = "text"
    LIKE = "like"
    HASHTAG = "hashtag"
    PROFILE = "profile"
    MEDIA_SHARE = "media_share"
    LOCATION = "location"
    ACTION_LOG = "action_log"
    TITLE = "title"
    USER_REACTION = "user_reaction"
    HISTORY_EDIT = "history_edit"
    REACTION_LOG = "reaction_log"
    REEL_SHARE = "reel_share"
    DEPRECATED_CHANNEL = "deprecated_channel"
    LINK = "link"
    RAVEN_MEDIA = "raven_media"
    LIVE_VIDEO_SHARE = "live_video_share"
    TEST = "test"
    STORY_SHARE = "story_share"
    REEL_REACT = "reel_react"
    LIVE_INVITE_GUEST = "live_invite_guest"
    LIVE_VIEWER_INVITE = "live_viewer_invite"
    TYPE_MAX = "type_max"
    PLACEHOLDER = "placeholder"
    PRODUCT = "product"
    PRODUCT_SHARE = "product_share"
    VIDEO_CALL_EVENT = "video_call_event"
    POLL_VOTE = "poll_vote"
    FELIX_SHARE = "felix_share"
    ANIMATED_MEDIA = "animated_media"
    CTA_LINK = "cta_link"
    VOICE_MEDIA = "voice_media"
    STATIC_STICKER = "static_sticker"
    AR_EFFECT = "ar_effect"
    SELFIE_STICKER = "selfie_sticker"
    REACTION = "reaction"


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


@dataclass
class CommandResponsePayload(SerializableAttrs['CommandResponsePayload']):
    client_context: Optional[str] = None
    item_id: Optional[str] = None
    timestamp: Optional[str] = None
    thread_id: Optional[str] = None


@dataclass
class CommandResponse(SerializableAttrs['CommandResponse']):
    action: str
    status: str
    status_code: str
    payload: CommandResponsePayload


@dataclass
class IrisPayloadData(SerializableAttrs['IrisPayloadData']):
    op: Operation
    path: str
    value: str


@dataclass
class IrisPayload(SerializableAttrs['IrisPayload']):
    data: List[IrisPayloadData]
    message_type: int
    seq_id: int
    event: str = "patch"
    mutation_token: Optional[str] = None
    realtime: Optional[bool] = None
    sampled: Optional[bool] = None


class ViewMode(SerializableEnum):
    ONCE = "once"
    REPLAYABLE = "replayable"
    PERMANENT = "permanent"


@dataclass
class CreativeConfig(SerializableAttrs['CreativeConfig']):
    capture_type: str
    camera_facing: str
    should_render_try_it_on: bool


@dataclass
class CreateModeAttribution(SerializableAttrs['CreateModeAttribution']):
    type: str
    name: str


@dataclass
class ImageVersion(SerializableAttrs['ImageVersion']):
    width: int
    height: int
    url: str
    estimated_scan_sizes: Optional[List[int]] = None


@dataclass
class ImageVersions(SerializableAttrs['ImageVersions']):
    candidates: List[ImageVersion]


@dataclass
class VideoVersion(SerializableAttrs['VideoVersion']):
    type: int
    width: int
    height: int
    url: str
    id: str


class MediaType(SerializableEnum):
    IMAGE = 1
    VIDEO = 2
    AD_MAP = 6
    LIVE = 7
    CAROUSEL = 8
    LIVE_REPLAY = 9
    COLLECTION = 10
    AUDIO = 11
    SHOWREEL_NATIVE = 12


@dataclass
class RegularMediaItem(SerializableAttrs['RegularMediaItem']):
    id: str
    image_versions2: Optional[ImageVersions] = None
    video_versions: Optional[List[VideoVersion]] = None
    original_width: int
    original_height: int
    media_type: MediaType
    media_id: Optional[int] = None
    organic_tracking_token: Optional[str] = None
    creative_config: Optional[CreativeConfig] = None
    create_mode_attribution: Optional[CreateModeAttribution] = None


@dataclass
class FriendshipStatus(SerializableAttrs['FriendshipStatus']):
    following: bool
    outgoing_request: bool
    is_bestie: bool
    is_restricted: bool


@dataclass
class MinimalUser(SerializableAttrs['MinimalUser']):
    pk: int
    username: str


@dataclass
class User(MinimalUser, SerializableAttrs['User']):
    full_name: str
    is_private: bool
    is_favorite: bool
    is_unpublished: bool
    has_anonymous_profile_picture: bool
    profile_pic_url: str
    profile_pic_id: str
    latest_reel_media: int
    friendship_status: FriendshipStatus


@dataclass
class Caption(SerializableAttrs['Caption']):
    pk: int
    user_id: int
    text: str
    # TODO enum?
    type: int
    created_at: int
    created_at_utc: int
    content_type: str
    # TODO enum?
    status: str
    bit_flags: int
    user: User
    did_report_as_spam: bool
    share_enabled: bool
    media_id: int


@dataclass
class MediaShareItem(SerializableAttrs['MediaShareItem']):
    taken_at: int
    pk: int
    id: str
    device_timestamp: int
    media_type: MediaType
    code: str
    client_cache_key: str
    filter_type: int
    image_versions2: ImageVersions
    video_versions: VideoVersion
    original_width: int
    original_height: int
    user: User
    can_viewer_reshare: bool
    caption_is_edited: bool
    comment_likes_enabled: bool
    comment_threading_enabled: bool
    has_more_comments: bool
    max_num_visible_preview_comments: int
    can_view_more_preview_comments: bool
    comment_count: int
    like_count: int
    has_liked: bool
    photo_of_you: bool
    caption: Caption
    can_viewer_save: bool
    organic_tracking_token: str


@dataclass
class ReplayableMediaItem(SerializableAttrs['ReplayableMediaItem']):
    view_mode: ViewMode
    seen_count: int
    seen_user_ids: List[int]
    replay_expiring_at_us: Optional[Any] = None


@dataclass
class VisualMedia(ReplayableMediaItem, SerializableAttrs['VisualMedia']):
    url_expire_at_secs: int
    playback_duration_secs: int
    media: RegularMediaItem


@dataclass
class AudioInfo(SerializableAttrs['AudioInfo']):
    audio_src: str
    duration: int
    waveform_data: List[int]
    waveform_sampling_frequence_hz: int


@dataclass
class VoiceMediaData(SerializableAttrs['VoiceMediaData']):
    id: str
    audio: AudioInfo
    organic_tracking_token: str
    user: MinimalUser
    # TODO enum?
    product_type: str = "direct_audio"
    media_type: MediaType = MediaType.AUDIO


@dataclass
class VoiceMediaItem(ReplayableMediaItem, SerializableAttrs['VoiceMediaItem']):
    media: VoiceMediaData


@dataclass
class AnimatedMediaImage(SerializableAttrs['AnimatedMediaImage']):
    height: str
    mp4: str
    mp4_size: str
    size: str
    url: str
    webp: str
    webp_size: str
    width: str


@dataclass
class AnimatedMediaImages(SerializableAttrs['AnimatedMediaImages']):
    fixed_height: Optional[AnimatedMediaImage] = None


@dataclass
class AnimatedMediaItem(SerializableAttrs['AnimatedMediaItem']):
    id: str
    is_random: str
    is_sticker: str
    images: AnimatedMediaImages


@dataclass
class MessageSyncMessage(SerializableAttrs['MessageSyncMessage']):
    thread_id: str
    item_id: Optional[str] = None
    admin_user_ids: Optional[int] = None
    approval_required_for_new_members: Optional[bool] = None
    participants: Optional[Dict[str, str]] = None
    # TODO enum
    op: Operation = Operation.ADD
    path: str
    user_id: Optional[int] = None
    timestamp: int
    item_type: Optional[ThreadItemType] = None
    text: Optional[str] = None
    media: Optional[RegularMediaItem] = None
    voice_media: Optional[VoiceMediaItem] = None
    animated_media: Optional[AnimatedMediaItem] = None
    visual_media: Optional[VisualMedia] = None
    media_share: Optional[MediaShareItem] = None
    reactions: Optional[dict] = None


@dataclass
class MessageSyncEvent(SerializableAttrs['MessageSyncEvent']):
    iris: IrisPayload
    message: MessageSyncMessage


@dataclass
class PubsubPublishMetadata(SerializableAttrs['PubsubPublishMetadata']):
    publish_time_ms: str
    topic_publish_id: int


@dataclass
class PubsubBasePayload(SerializableAttrs['PubsubBasePayload']):
    lazy: bool
    event: str = "patch"
    publish_metadata: Optional[PubsubPublishMetadata] = None
    num_endpoints: Optional[int] = None


@dataclass
class ActivityIndicatorData(SerializableAttrs['ActivityIndicatorData']):
    timestamp: str
    sender_id: str
    ttl: int
    activity_status: TypingStatus

    @classmethod
    def deserialize(cls, data: JSON) -> 'ActivityIndicatorData':
        # The ActivityIndicatorData in PubsubPayloadData is actually a string,
        # so we need to unmarshal it first.
        if isinstance(data, str):
            data = json.loads(data)
        return super().deserialize(data)


@dataclass
class PubsubPayloadData(SerializableAttrs['PubsubPayloadData']):
    double_publish: bool = field(json="doublePublish")
    value: ActivityIndicatorData
    path: str
    op: Operation = Operation.ADD


@dataclass
class PubsubPayload(PubsubBasePayload, SerializableAttrs['PubsubPayload']):
    data: List[PubsubPayloadData]


@dataclass
class PubsubEvent(SerializableAttrs['PubsubEvent']):
    base: PubsubBasePayload
    data: PubsubPayloadData
    thread_id: str
    activity_indicator_id: str


@dataclass
class AppPresenceEvent(SerializableAttrs['AppPresenceEvent']):
    user_id: str
    is_active: bool
    last_activity_at_ms: str
    in_threads: List[Any]


@dataclass
class AppPresenceEventPayload(SerializableAttrs['AppPresenceEventPayload']):
    presence_event: AppPresenceEvent


@dataclass
class ZeroProductProvisioningEvent(SerializableAttrs['ZeroProductProvisioningEvent']):
    device_id: str
    product_name: str
    zero_provisioned_time: str


@dataclass
class RealtimeZeroProvisionPayload(SerializableAttrs['RealtimeZeroProvisionPayload']):
    zero_product_provisioning_event: ZeroProductProvisioningEvent


@dataclass
class ClientConfigUpdateEvent(SerializableAttrs['ClientConfigUpdateEvent']):
    publish_id: str
    client_config_name: str
    backing: str = "QE"
    client_subscription_id: str = GraphQLQueryID.clientConfigUpdate


@dataclass
class ClientConfigUpdatePayload(SerializableAttrs['ClientConfigUpdatePayload']):
    client_config_update_event: ClientConfigUpdateEvent


RealtimeDirectData = ActivityIndicatorData


@dataclass
class RealtimeDirectEvent(SerializableAttrs['RealtimeDirectEvent']):
    op: Operation
    path: str
    value: RealtimeDirectData


@dataclass
class LiveVideoCommentUser(SerializableAttrs['LiveVideoCommentUser']):
    pk: str
    username: str
    full_name: str
    is_private: bool
    is_verified: bool
    profile_pic_url: str
    profile_pic_id: Optional[str] = None


@dataclass
class LiveVideoSystemComment(SerializableAttrs['LiveVideoSystemComment']):
    pk: str
    created_at: int
    text: str
    user_count: int
    user: LiveVideoCommentUser


@dataclass
class LiveVideoComment(SerializableAttrs['LiveVideoComment']):
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
    user: LiveVideoCommentUser


@dataclass
class LiveVideoCommentEvent(SerializableAttrs['LiveVideoCommentEvent']):
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


@dataclass
class LiveVideoCommentPayload(SerializableAttrs['LiveVideoCommentPayload']):
    live_video_comment_event: LiveVideoCommentEvent
