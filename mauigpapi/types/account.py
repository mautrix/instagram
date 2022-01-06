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

from mautrix.types import SerializableAttrs, SerializableEnum


@dataclass(kw_only=True)
class FriendshipStatus(SerializableAttrs):
    following: bool
    outgoing_request: bool
    is_bestie: bool
    is_restricted: bool
    blocking: Optional[bool] = None
    incoming_request: Optional[bool] = None
    is_private: Optional[bool] = None


@dataclass(kw_only=True)
class UserIdentifier(SerializableAttrs):
    pk: int
    username: str


@dataclass(kw_only=True)
class BaseResponseUser(UserIdentifier, SerializableAttrs):
    full_name: str
    is_private: bool = False
    is_verified: bool = False
    profile_pic_url: str
    profile_pic_id: Optional[str] = None
    has_anonymous_profile_picture: bool = False
    # TODO find type
    account_badges: Optional[List[Any]] = None

    # TODO enum? only present for self
    reel_auto_archive: Optional[str] = None
    # Only present for not-self
    friendship_status: Optional[FriendshipStatus] = None
    # Not exactly sure when this is present
    latest_reel_media: Optional[int] = None
    has_highlight_reels: bool = False
    follow_friction_type: Optional[int] = None


@dataclass(kw_only=True)
class BaseFullResponseUser(BaseResponseUser, SerializableAttrs):
    phone_number: str
    country_code: Optional[int] = None
    national_number: Optional[int] = None

    # TODO enum?
    allowed_commenter_type: str

    # These are at least in login and current_user, might not be in other places though
    is_business: bool
    # TODO enum?
    account_type: int


@dataclass
class EntityText(SerializableAttrs):
    raw_text: str
    # TODO figure out type
    entities: List[Any]


@dataclass
class HDProfilePictureVersion(SerializableAttrs):
    url: str
    width: int
    height: int


@dataclass
class ProfileEditParams(SerializableAttrs):
    should_show_confirmation_dialog: bool
    is_pending_review: bool
    confirmation_dialog_text: str
    disclaimer_text: str


class Gender(SerializableEnum):
    MALE = 1
    FEMALE = 2
    UNSET = 3
    CUSTOM = 4


@dataclass(kw_only=True)
class CurrentUser(BaseFullResponseUser, SerializableAttrs):
    biography: str
    can_link_entities_in_bio: bool
    biography_with_entities: EntityText
    biography_product_mentions: List[Any]
    external_url: str
    has_biography_translation: bool = False
    hd_profile_pic_versions: List[HDProfilePictureVersion] = attr.ib(factory=lambda: [])
    hd_profile_pic_url_info: HDProfilePictureVersion
    show_conversion_edit_entry: bool
    # TODO type
    # birthday: Any
    gender: Gender
    custom_gender: str
    email: str
    profile_edit_params: Dict[str, ProfileEditParams]


@dataclass
class CurrentUserResponse(SerializableAttrs):
    status: str
    user: CurrentUser
