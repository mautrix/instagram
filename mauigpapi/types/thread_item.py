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
from typing import List, Optional, Union
import logging

import attr
from attr import dataclass
from mautrix.types import SerializableAttrs, SerializableEnum, JSON, SerializerError, Obj
from mautrix.types.util.serializable_attrs import _dict_to_attrs

from .account import BaseResponseUser, UserIdentifier


log = logging.getLogger("mauigpapi.types")


class ThreadItemType(SerializableEnum):
    DELETION = "deletion"
    MEDIA = "media"
    TEXT = "text"
    LIKE = "like"
    HASHTAG = "hashtag"
    PROFILE = "profile"
    MEDIA_SHARE = "media_share"
    CONFIGURE_PHOTO = "configure_photo"
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


@dataclass(kw_only=True)
class ThreadItemActionLog(SerializableAttrs['ThreadItemActionLog']):
    description: str
    # TODO bold, text_attributes


class ViewMode(SerializableEnum):
    ONCE = "once"
    REPLAYABLE = "replayable"
    PERMANENT = "permanent"


@dataclass(kw_only=True)
class CreativeConfig(SerializableAttrs['CreativeConfig']):
    capture_type: str
    camera_facing: str
    should_render_try_it_on: bool


@dataclass(kw_only=True)
class CreateModeAttribution(SerializableAttrs['CreateModeAttribution']):
    type: str
    name: str


@dataclass(kw_only=True)
class ImageVersion(SerializableAttrs['ImageVersion']):
    width: int
    height: int
    url: str
    estimated_scan_sizes: Optional[List[int]] = None


@dataclass(kw_only=True)
class ImageVersions(SerializableAttrs['ImageVersions']):
    candidates: List[ImageVersion]


@dataclass(kw_only=True)
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


@dataclass(kw_only=True)
class ExpiredMediaItem(SerializableAttrs['ExpiredMediaItem']):
    media_type: Optional[MediaType] = None


@dataclass(kw_only=True)
class RegularMediaItem(SerializableAttrs['RegularMediaItem']):
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

    # TODO carousel_media shares

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
    user: BaseResponseUser
    did_report_as_spam: bool
    share_enabled: bool
    media_id: int


@dataclass
class Location(SerializableAttrs['Location']):
    pk: int
    short_name: str
    facebook_places_id: int
    # TODO enum?
    external_source: str  # facebook_places
    name: str
    address: str
    city: str
    lng: float
    lat: float


@dataclass(kw_only=True)
class MediaShareItem(RegularMediaItem, SerializableAttrs['MediaShareItem']):
    taken_at: int
    pk: int
    device_timestamp: int
    code: str
    client_cache_key: str
    filter_type: int
    user: BaseResponseUser
    # Not present in reel shares
    can_viewer_reshare: Optional[bool] = None
    caption_is_edited: bool
    comment_likes_enabled: bool
    comment_threading_enabled: bool
    has_more_comments: bool
    max_num_visible_preview_comments: int
    # preview_comments: List[TODO]
    can_view_more_preview_comments: bool
    comment_count: int
    like_count: int
    has_liked: bool
    photo_of_you: bool
    caption: Optional[Caption] = None
    can_viewer_save: bool
    location: Optional[Location] = None


@dataclass
class SharingFrictionInfo(SerializableAttrs['SharingFrictionInfo']):
    should_have_sharing_friction: bool
    bloks_app_url: Optional[str]


# The fields in this class have been observed in reel share items, but may exist elsewhere too.
# If they're observed in other types, they should be moved to MediaShareItem.
@dataclass(kw_only=True)
class ReelMediaShareItem(MediaShareItem, SerializableAttrs['ReelMediaShareItem']):
    # These three are apparently sometimes not present
    # TODO enum?
    caption_position: Optional[int] = None
    is_reel_media: Optional[bool] = None
    timezone_offset: Optional[int] = None
    # likers: List[TODO]
    can_see_insights_as_brand: bool
    expiring_at: int
    sharing_friction_info: SharingFrictionInfo
    is_in_profile_grid: bool
    profile_grid_control_enabled: bool
    is_shop_the_look_eligible: bool
    # TODO enum?
    deleted_reason: int
    integrity_review_decision: str
    # Not present in story_share, only reel_share
    story_is_saved_to_archive: Optional[bool] = None


@dataclass(kw_only=True)
class ReplayableMediaItem(SerializableAttrs['ReplayableMediaItem']):
    view_mode: ViewMode
    seen_count: int
    seen_user_ids: List[int]
    replay_expiring_at_us: Optional[int] = None


@dataclass(kw_only=True)
class VisualMedia(ReplayableMediaItem, SerializableAttrs['VisualMedia']):
    url_expire_at_secs: Optional[int] = None
    playback_duration_secs: Optional[int] = None
    media: Union[RegularMediaItem, ExpiredMediaItem]

    @classmethod
    def deserialize(cls, data: JSON) -> 'VisualMedia':
        data = {**data}
        if "id" not in data["media"]:
            data["media"] = ExpiredMediaItem.deserialize(data["media"])
        else:
            data["media"] = RegularMediaItem.deserialize(data["media"])
        return _dict_to_attrs(cls, data)


@dataclass(kw_only=True)
class AudioInfo(SerializableAttrs['AudioInfo']):
    audio_src: str
    duration: int
    waveform_data: List[int]
    waveform_sampling_frequency_hz: int


@dataclass(kw_only=True)
class VoiceMediaData(SerializableAttrs['VoiceMediaData']):
    id: str
    audio: AudioInfo
    organic_tracking_token: str
    user: UserIdentifier
    # TODO enum?
    product_type: str  # "direct_audio"
    media_type: MediaType  # MediaType.AUDIO


@dataclass(kw_only=True)
class VoiceMediaItem(ReplayableMediaItem, SerializableAttrs['VoiceMediaItem']):
    media: VoiceMediaData


@dataclass(kw_only=True)
class AnimatedMediaImage(SerializableAttrs['AnimatedMediaImage']):
    height: str
    mp4: str
    mp4_size: str
    size: str
    url: str
    webp: str
    webp_size: str
    width: str


@dataclass(kw_only=True)
class AnimatedMediaImages(SerializableAttrs['AnimatedMediaImages']):
    fixed_height: Optional[AnimatedMediaImage] = None


@dataclass(kw_only=True)
class AnimatedMediaItem(SerializableAttrs['AnimatedMediaItem']):
    id: str
    is_random: str
    is_sticker: str
    images: AnimatedMediaImages


@dataclass
class Reaction(SerializableAttrs['Reaction']):
    sender_id: int
    timestamp: int
    client_context: int
    emoji: str = "❤️"
    super_react_type: Optional[str] = None


@dataclass
class Reactions(SerializableAttrs['Reactions']):
    likes_count: int = 0
    likes: List[Reaction] = attr.ib(factory=lambda: [])
    emojis: List[Reaction] = attr.ib(factory=lambda: [])


@dataclass
class LinkContext(SerializableAttrs['LinkContext']):
    link_url: str
    link_title: str
    link_summary: str
    link_image_url: str


@dataclass
class LinkItem(SerializableAttrs['LinkItem']):
    text: str
    link_context: LinkContext
    client_context: str
    mutation_token: str


class ReelShareType(SerializableEnum):
    REPLY = "reply"
    REACTION = "reaction"
    MENTION = "mention"


@dataclass
class ReelShareReactionInfo(SerializableAttrs['ReelShareReactionInfo']):
    emoji: str
    # TODO find type
    # intensity: Any


@dataclass
class ReelShareItem(SerializableAttrs['ReelShareItem']):
    text: str
    type: ReelShareType
    reel_owner_id: int
    is_reel_persisted: int
    reel_type: str
    media: ReelMediaShareItem
    reaction_info: Optional[ReelShareReactionInfo] = None


@dataclass
class StoryShareItem(SerializableAttrs['StoryShareItem']):
    text: str
    is_reel_persisted: bool
    # TODO enum?
    reel_type: str  # user_reel
    reel_id: str
    # TODO enum?
    story_share_type: str  # default
    media: ReelMediaShareItem


@dataclass(kw_only=True)
class ThreadItem(SerializableAttrs['ThreadItem']):
    item_id: Optional[str] = None
    user_id: Optional[int] = None
    timestamp: Optional[int] = None
    item_type: Optional[ThreadItemType] = None
    is_shh_mode: bool = False

    text: Optional[str] = None
    client_context: Optional[str] = None
    show_forward_attribution: Optional[bool] = None
    action_log: Optional[ThreadItemActionLog] = None

    media: Optional[RegularMediaItem] = None
    voice_media: Optional[VoiceMediaItem] = None
    animated_media: Optional[AnimatedMediaItem] = None
    visual_media: Optional[VisualMedia] = None
    media_share: Optional[MediaShareItem] = None
    reel_share: Optional[ReelShareItem] = None
    story_share: Optional[StoryShareItem] = None
    location: Optional[Location] = None
    reactions: Optional[Reactions] = None
    like: Optional[str] = None
    link: Optional[LinkItem] = None

    @classmethod
    def deserialize(cls, data: JSON, catch_errors: bool = True) -> Union['ThreadItem', Obj]:
        if not catch_errors:
            return _dict_to_attrs(cls, data)
        try:
            return _dict_to_attrs(cls, data)
        except SerializerError:
            log.debug("Failed to deserialize ThreadItem %s", data)
            return Obj(**data)
