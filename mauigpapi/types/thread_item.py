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
from typing import List, Optional, Union
import logging

from attr import dataclass
import attr

from mautrix.types import (
    JSON,
    ExtensibleEnum,
    Obj,
    SerializableAttrs,
    SerializableEnum,
    SerializerError,
)
from mautrix.types.util.serializable_attrs import _dict_to_attrs

from .account import BaseResponseUser, UserIdentifier

log = logging.getLogger("mauigpapi.types")


class ThreadItemType(ExtensibleEnum):
    DELETION = "deletion"
    MEDIA = "media"
    TEXT = "text"
    LIKE = "like"
    HASHTAG = "hashtag"
    PROFILE = "profile"
    MEDIA_SHARE = "media_share"
    CONFIGURE_PHOTO = "configure_photo"
    CONFIGURE_VIDEO = "configure_video"
    SHARE_VOICE = "share_voice"
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
    CLIP = "clip"
    GUIDE_SHARE = "guide_share"


@dataclass(kw_only=True)
class ThreadItemActionLog(SerializableAttrs):
    description: str
    # TODO bold, text_attributes


class ViewMode(SerializableEnum):
    ONCE = "once"
    REPLAYABLE = "replayable"
    PERMANENT = "permanent"


@dataclass(kw_only=True)
class CreativeConfig(SerializableAttrs):
    capture_type: str
    camera_facing: Optional[str] = None
    should_render_try_it_on: Optional[bool] = None


@dataclass(kw_only=True)
class CreateModeAttribution(SerializableAttrs):
    type: str
    name: str


@dataclass(kw_only=True)
class ImageVersion(SerializableAttrs):
    width: int
    height: int
    url: str
    estimated_scan_sizes: Optional[List[int]] = None


@dataclass(kw_only=True)
class ImageVersions(SerializableAttrs):
    candidates: List[ImageVersion]


@dataclass(kw_only=True)
class VideoVersion(SerializableAttrs):
    type: int
    width: int
    height: int
    url: str
    id: Optional[str] = None


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

    @property
    def human_name(self) -> str:
        return self.name.lower().replace("_", " ")


@dataclass(kw_only=True)
class ExpiredMediaItem(SerializableAttrs):
    media_type: Optional[MediaType] = None
    user: Optional[BaseResponseUser] = None


@dataclass(kw_only=True)
class RegularMediaItem(SerializableAttrs):
    id: str
    image_versions2: Optional[ImageVersions] = None
    video_versions: Optional[List[VideoVersion]] = None
    original_width: Optional[int] = None
    original_height: Optional[int] = None
    media_type: MediaType
    media_id: Optional[int] = None
    organic_tracking_token: Optional[str] = None
    creative_config: Optional[CreativeConfig] = None
    create_mode_attribution: Optional[CreateModeAttribution] = None
    is_commercial: Optional[bool] = None
    commerciality_status: Optional[str] = None  # TODO enum? commercial

    @property
    def best_image(self) -> Optional[ImageVersion]:
        if not self.image_versions2:
            return None
        best: Optional[ImageVersion] = None
        for version in self.image_versions2.candidates:
            if version.width == self.original_width and version.height == self.original_height:
                return version
            elif not best or (version.width * version.height > best.width * best.height):
                best = version
        return best

    @property
    def best_video(self) -> Optional[VideoVersion]:
        if not self.video_versions:
            return None
        best: Optional[VideoVersion] = None
        for version in self.video_versions:
            if version.width == self.original_width and version.height == self.original_height:
                return version
            elif not best or (version.width * version.height > best.width * best.height):
                best = version
        return best


@dataclass(kw_only=True)
class Caption(SerializableAttrs):
    pk: int
    user_id: int
    text: str
    # TODO enum? 1
    type: int
    created_at: int
    created_at_utc: int
    # TODO enum? comment
    content_type: str
    # TODO enum? Active
    status: str
    # TODO enum-ish thing?
    bit_flags: int
    user: BaseResponseUser
    did_report_as_spam: bool
    share_enabled: bool
    media_id: int

    # Might not be in all captions
    is_covered: Optional[bool] = None
    private_reply_status: Optional[int] = None


@dataclass
class Location(SerializableAttrs):
    pk: int
    short_name: str
    facebook_places_id: int
    # TODO enum?
    external_source: str  # facebook_places
    name: str
    address: str
    city: str
    lng: Optional[float] = None
    lat: Optional[float] = None
    is_eligible_for_guides: bool = False


@dataclass(kw_only=True)
class CarouselMediaItem(RegularMediaItem, SerializableAttrs):
    carousel_parent_id: str
    pk: int


@dataclass
class UserTag(SerializableAttrs):
    user: BaseResponseUser
    position: List[float]
    # start_time_in_video_in_sec
    # duration_in_video_in_sec


@dataclass
class UserTags(SerializableAttrs):
    in_: List[UserTag] = attr.ib(metadata={"json": "in"}, factory=lambda: [])


@dataclass(kw_only=True)
class MediaShareItem(RegularMediaItem, SerializableAttrs):
    taken_at: int
    pk: int
    device_timestamp: int
    code: str
    client_cache_key: str
    filter_type: int
    user: BaseResponseUser
    # Not present in reel shares
    can_viewer_reshare: Optional[bool] = None
    caption_is_edited: bool = False
    comment_likes_enabled: bool = False
    comment_threading_enabled: bool = False
    has_more_comments: bool = False
    max_num_visible_preview_comments: int = 0
    # preview_comments: List[TODO]
    can_view_more_preview_comments: bool = False
    comment_count: int = 0
    like_count: int = 0
    has_liked: bool = False
    photo_of_you: bool = False
    usertags: Optional[UserTags] = None
    caption: Optional[Caption] = None
    can_viewer_save: bool = True
    location: Optional[Location] = None
    carousel_media_count: Optional[int] = None
    carousel_media: Optional[List[CarouselMediaItem]] = None


@dataclass
class SharingFrictionInfo(SerializableAttrs):
    should_have_sharing_friction: bool
    bloks_app_url: Optional[str]


# The fields in this class have been observed in reel share items, but may exist elsewhere too.
# If they're observed in other types, they should be moved to MediaShareItem.
@dataclass(kw_only=True)
class ReelMediaShareItem(MediaShareItem, SerializableAttrs):
    # These three are apparently sometimes not present
    # TODO enum?
    caption_position: Optional[int] = None
    is_reel_media: Optional[bool] = None
    timezone_offset: Optional[int] = None
    # likers: List[TODO]
    can_see_insights_as_brand: bool = False
    expiring_at: Optional[int] = None
    sharing_friction_info: Optional[SharingFrictionInfo] = None
    is_in_profile_grid: bool = False
    profile_grid_control_enabled: bool = False
    is_shop_the_look_eligible: bool = False
    # TODO enum?
    deleted_reason: Optional[int] = None
    integrity_review_decision: Optional[str] = None
    # Not present in story_share, only reel_share
    story_is_saved_to_archive: Optional[bool] = None


@dataclass(kw_only=True)
class ReplayableMediaItem(SerializableAttrs):
    view_mode: ViewMode
    seen_count: int
    seen_user_ids: List[int]
    replay_expiring_at_us: Optional[int] = None


@dataclass(kw_only=True)
class VisualMedia(ReplayableMediaItem, SerializableAttrs):
    url_expire_at_secs: Optional[int] = None
    playback_duration_secs: Optional[int] = None
    media: Union[RegularMediaItem, ExpiredMediaItem]

    @classmethod
    def deserialize(cls, data: JSON) -> "VisualMedia":
        data = {**data}
        if "id" not in data["media"]:
            data["media"] = ExpiredMediaItem.deserialize(data["media"])
        else:
            data["media"] = RegularMediaItem.deserialize(data["media"])
        return _dict_to_attrs(cls, data)


@dataclass(kw_only=True)
class AudioInfo(SerializableAttrs):
    audio_src: str
    duration: int
    waveform_data: Optional[List[int]] = None
    waveform_sampling_frequency_hz: Optional[int] = None


@dataclass(kw_only=True)
class VoiceMediaData(SerializableAttrs):
    id: str
    audio: AudioInfo
    organic_tracking_token: str
    user: UserIdentifier
    # TODO enum?
    product_type: str  # "direct_audio"
    media_type: MediaType  # MediaType.AUDIO


@dataclass(kw_only=True)
class VoiceMediaItem(ReplayableMediaItem, SerializableAttrs):
    media: VoiceMediaData


@dataclass(kw_only=True)
class AnimatedMediaImage(SerializableAttrs):
    height: str
    mp4: str
    mp4_size: str
    size: str
    url: str
    webp: str
    webp_size: str
    width: str


@dataclass(kw_only=True)
class AnimatedMediaImages(SerializableAttrs):
    fixed_height: Optional[AnimatedMediaImage] = None


@dataclass(kw_only=True)
class AnimatedMediaItem(SerializableAttrs):
    id: str
    is_random: str
    is_sticker: str
    images: AnimatedMediaImages


@dataclass
class Reaction(SerializableAttrs):
    sender_id: int
    timestamp: int
    client_context: int
    emoji: str = "❤️"
    super_react_type: Optional[str] = None


@dataclass
class Reactions(SerializableAttrs):
    likes_count: int = 0
    likes: List[Reaction] = attr.ib(factory=lambda: [])
    emojis: List[Reaction] = attr.ib(factory=lambda: [])


@dataclass
class LinkContext(SerializableAttrs):
    link_url: str
    link_title: str
    link_summary: str
    link_image_url: str


@dataclass
class LinkItem(SerializableAttrs):
    text: str
    link_context: LinkContext
    client_context: str
    mutation_token: Optional[str] = None


class ReelShareType(ExtensibleEnum):
    REPLY = "reply"
    REACTION = "reaction"
    MENTION = "mention"
    REPLY_GIF = "reply_gif"


@dataclass
class ReelShareReactionInfo(SerializableAttrs):
    emoji: str
    # TODO find type
    # intensity: Any


@dataclass
class ReelShareItem(SerializableAttrs):
    text: str
    type: ReelShareType
    reel_owner_id: int
    is_reel_persisted: int
    reel_type: str
    media: Union[ReelMediaShareItem, ExpiredMediaItem]
    reaction_info: Optional[ReelShareReactionInfo] = None
    mentioned_user_id: Optional[int] = None

    @classmethod
    def deserialize(cls, data: JSON) -> "ReelShareItem":
        data = {**data}
        if "id" not in data["media"]:
            data["media"] = ExpiredMediaItem.deserialize(data["media"])
        else:
            data["media"] = ReelMediaShareItem.deserialize(data["media"])
        return _dict_to_attrs(cls, data)


@dataclass
class StoryShareItem(SerializableAttrs):
    text: str
    media: Union[ReelMediaShareItem, ExpiredMediaItem]

    # Only present when not expired
    is_reel_persisted: Optional[bool] = None
    # TODO enum?
    reel_type: Optional[str] = None  # user_reel
    reel_id: Optional[str] = None
    # TODO enum?
    story_share_type: Optional[str] = None  # default

    # Only present when expired
    message: Optional[str] = None
    # TODO enum
    reason: Optional[int] = None  # 3 = expired?

    @classmethod
    def deserialize(cls, data: JSON) -> "StoryShareItem":
        data = {**data}
        if "media" not in data:
            data["media"] = ExpiredMediaItem()
        else:
            data["media"] = ReelMediaShareItem.deserialize(data["media"])
        return _dict_to_attrs(cls, data)


@dataclass
class DirectMediaShareItem(SerializableAttrs):
    text: str
    # TODO enum?
    media_share_type: str  # tag
    tagged_user_id: int
    media: MediaShareItem


@dataclass
class ClipItem(SerializableAttrs):
    # TODO there are some additional fields in clips
    clip: MediaShareItem


@dataclass
class FelixShareItem(SerializableAttrs):
    video: MediaShareItem
    text: Optional[str] = None


@dataclass
class ProfileItem(BaseResponseUser, SerializableAttrs):
    pass


@dataclass(kw_only=True)
class ThreadItem(SerializableAttrs):
    item_id: Optional[str] = None
    user_id: Optional[int] = None
    timestamp: int = 0
    item_type: Optional[ThreadItemType] = None
    is_shh_mode: bool = False

    text: Optional[str] = None
    client_context: Optional[str] = None
    show_forward_attribution: Optional[bool] = None
    action_log: Optional[ThreadItemActionLog] = None

    replied_to_message: Optional["ThreadItem"] = None

    media: Optional[RegularMediaItem] = None
    voice_media: Optional[VoiceMediaItem] = None
    animated_media: Optional[AnimatedMediaItem] = None
    visual_media: Optional[VisualMedia] = None
    media_share: Optional[MediaShareItem] = None
    direct_media_share: Optional[DirectMediaShareItem] = None
    reel_share: Optional[ReelShareItem] = None
    story_share: Optional[StoryShareItem] = None
    location: Optional[Location] = None
    reactions: Optional[Reactions] = None
    like: Optional[str] = None
    link: Optional[LinkItem] = None
    clip: Optional[ClipItem] = None
    felix_share: Optional[FelixShareItem] = None
    profile: Optional[ProfileItem] = None

    @property
    def timestamp_ms(self) -> int:
        return self.timestamp // 1000

    @classmethod
    def deserialize(cls, data: JSON, catch_errors: bool = True) -> Union["ThreadItem", Obj]:
        if not catch_errors:
            return _dict_to_attrs(cls, data)
        try:
            return _dict_to_attrs(cls, data)
        except SerializerError:
            log.debug("Failed to deserialize ThreadItem %s", data)
            return Obj(**data)

    @property
    def unhandleable_type(self) -> str:
        if self.action_log:
            return "action log"
        return "unknown"

    @property
    def is_handleable(self) -> bool:
        return bool(
            self.media
            or self.animated_media
            or self.voice_media
            or self.visual_media
            or self.location
            or self.profile
            or self.reel_share
            or self.media_share
            or self.direct_media_share
            or self.story_share
            or self.clip
            or self.felix_share
            or self.text
            or self.like
            or self.link
        )


# This resolves the 'ThreadItem' string into an actual type.
# Starting Python 3.10, all type annotations will be strings and have to be resolved like this.
# TODO do this automatically for all SerializableAttrs somewhere in mautrix-python
attr.resolve_types(ThreadItem)
