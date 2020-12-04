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
from typing import Any, List

from attr import dataclass

from mautrix.types import SerializableAttrs


@dataclass
class BaseResponseUser(SerializableAttrs['BaseResponseUser']):
    pk: int
    username: str
    full_name: str
    is_private: bool
    profile_pic_url: str
    profile_pic_id: str
    is_verified: bool
    has_anonymous_profile_picture: bool

    phone_number: str
    country_code: int
    national_number: int

    reel_auto_archive: str
    allowed_commenter_type: str


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


# Not sure if these are actually the same
HDProfilePictureURLInfo = HDProfilePictureVersion


@dataclass
class CurrentUser(SerializableAttrs['CurrentUser']):
    biography: str
    can_link_entities_in_bio: bool
    biography_with_entities: EntityText
    external_url: str
    has_biography_translation: bool
    hd_profile_pic_versions: HDProfilePictureVersion
    hd_profile_pic_url_info: HDProfilePictureURLInfo
    show_conversion_edit_entry: bool
    birthday: Any
    gender: int
    email: str

@dataclass
class CurrentUserResponse(SerializableAttrs['CurrentUserResponse']):
    status: str
    user: CurrentUser
