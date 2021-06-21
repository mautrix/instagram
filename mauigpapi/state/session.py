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
from typing import Optional, Union

from attr import dataclass

from mautrix.types import SerializableAttrs


@dataclass
class AndroidSession(SerializableAttrs):
    eu_dc_enabled: Optional[bool] = None
    thumbnail_cache_busting_value: int = 1000
    ads_opt_out: bool = False

    ig_www_claim: Optional[str] = None
    authorization: Optional[str] = None
    password_encryption_pubkey: Optional[str] = None
    password_encryption_key_id: Union[None, str, int] = None
    region_hint: Optional[str] = None

    shbid: Optional[str] = None
    shbts: Optional[str] = None
    ds_user_id: Optional[str] = None
    rur: Optional[str] = None
