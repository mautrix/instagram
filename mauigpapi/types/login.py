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
from typing import Any, List, Optional

from attr import dataclass

from mautrix.types import SerializableAttrs

from .account import BaseFullResponseUser


@dataclass
class LoginResponseNametag(SerializableAttrs):
    mode: Optional[int] = None
    emoji: Optional[str] = None
    emoji_color: Optional[str] = None
    selfie_sticker: Optional[str] = None
    gradient: Optional[str] = None


@dataclass
class LoginResponseUser(BaseFullResponseUser, SerializableAttrs):
    can_boost_post: bool
    can_see_organic_insights: bool
    show_insights_terms: bool
    has_placed_orders: bool
    nametag: LoginResponseNametag
    allow_contacts_sync: bool

    total_igtv_videos: int
    interop_messaging_user_fbid: int
    is_using_unified_inbox_for_direct: bool
    can_see_primary_country_in_settings: str
    professional_conversion_suggested_account_type: Optional[int]


@dataclass
class LoginResponse(SerializableAttrs):
    logged_in_user: LoginResponseUser
    status: str


@dataclass
class FacebookLoginResponse(LoginResponse, SerializableAttrs):
    code: int = 0
    fb_access_token: Optional[str] = None
    fb_user_id: Optional[str] = None
    session_flush_nonce: Optional[str] = None


@dataclass
class LogoutResponse(SerializableAttrs):
    status: str
    login_nonce: Optional[str] = None
