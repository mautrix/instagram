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
from typing import List, Optional

from attr import dataclass

from mautrix.types import SerializableAttrs

from .account import BaseResponseUser


@dataclass
class SearchResultUser(BaseResponseUser, SerializableAttrs):
    mutual_followers_count: Optional[int] = None
    social_context: Optional[str] = None
    search_social_context: Optional[str] = None


@dataclass
class UserSearchResponse(SerializableAttrs):
    num_results: int
    users: List[SearchResultUser]
    has_more: bool
    rank_token: str
    status: str
