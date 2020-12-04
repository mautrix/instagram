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
from typing import Any, Optional, List

from attr import dataclass

from mautrix.types import SerializableAttrs

from .account import BaseResponseUser


@dataclass
class LoginResponseNametag(SerializableAttrs['LoginResponseNametag']):
    mode: int
    gradient: str
    emoji: str
    selfie_sticker: str


@dataclass
class LoginResponseUser(BaseResponseUser, SerializableAttrs['LoginResponseUser']):
    can_boost_post: bool
    can_see_organic_insights: bool
    show_insights_terms: bool
    has_placed_orders: bool
    nametag: LoginResponseNametag
    allow_contacts_sync: bool

    # These are from manually observed responses rather than igpapi
    total_igtv_videos: int
    interop_messaging_user_fbid: int
    is_using_unified_inbox_for_direct: bool
    can_see_primary_country_in_settings: str
    professional_conversion_suggested_account_type: Optional[int]


@dataclass
class LoginResponse(SerializableAttrs['LoginResponse']):
    logged_in_user: LoginResponseUser
    status: str


@dataclass
class LogoutResponse(SerializableAttrs['LogoutResponse']):
    status: str
    login_nonce: Optional[str] = None
