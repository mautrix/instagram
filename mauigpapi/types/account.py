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
from typing import Any, List, Optional, Dict

from attr import dataclass

from mautrix.types import SerializableAttrs


@dataclass(kw_only=True)
class BaseResponseUser(SerializableAttrs['BaseResponseUser']):
    pk: int
    username: str
    full_name: str
    is_private: bool
    profile_pic_url: str
    # When this doesn't exist, the profile picture is probably the default one
    profile_pic_id: Optional[str] = None
    is_verified: bool
    has_anonymous_profile_picture: bool

    phone_number: str
    country_code: Optional[int] = None
    national_number: Optional[int] = None

    # TODO enum both of these?
    reel_auto_archive: str
    allowed_commenter_type: str

    # These are at least in login and current_user, might not be in other places though
    is_business: bool
    # TODO enum?
    account_type: int
    is_call_to_action_enabled: Any
    account_badges: List[Any]


@dataclass
class EntityText(SerializableAttrs['EntityText']):
    raw_text: str
    # TODO figure out type
    entities: List[Any]


@dataclass
class HDProfilePictureVersion(SerializableAttrs['HDProfilePictureVersion']):
    url: str
    width: int
    height: int


@dataclass
class ProfileEditParams(SerializableAttrs['ProfileEditParams']):
    should_show_confirmation_dialog: bool
    is_pending_review: bool
    confirmation_dialog_text: str
    disclaimer_text: str


@dataclass(kw_only=True)
class CurrentUser(BaseResponseUser, SerializableAttrs['CurrentUser']):
    biography: str
    can_link_entities_in_bio: bool
    biography_with_entities: EntityText
    biography_product_mentions: List[Any]
    external_url: str
    has_biography_translation: bool = False
    hd_profile_pic_versions: List[HDProfilePictureVersion]
    hd_profile_pic_url_info: HDProfilePictureVersion
    show_conversion_edit_entry: bool
    birthday: Any
    gender: int
    custom_gender: str
    email: str
    profile_edit_params: Dict[str, ProfileEditParams]


@dataclass
class CurrentUserResponse(SerializableAttrs['CurrentUserResponse']):
    status: str
    user: CurrentUser
