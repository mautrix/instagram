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
import attr

from mautrix.types import SerializableAttrs


@dataclass
class AndroidSession(SerializableAttrs['AndroidSession']):
    eu_dc_enabled: Optional[bool] = attr.ib(default=None, metadata={"json": "euDCEnabled"})
    thumbnail_cache_busting_value: int = attr.ib(default=1000, metadata={"json": "thumbnailCacheBustingValue"})
    ads_opt_out: bool = attr.ib(default=None, metadata={"json": "adsOptOut"})

    ig_www_claim: Optional[str] = attr.ib(default=None, metadata={"json": "igWWWClaim"})
    authorization: Optional[str] = None
    password_encryption_pubkey: Optional[str] = attr.ib(default=None, metadata={"json": "passwordEncryptionPubKey"})
    password_encryption_key_id: Union[None, str, int] = attr.ib(default=None, metadata={"json": "passwordEncryptionKeyId"})
    region_hint: Optional[str] = attr.ib(default=None, metadata={"json": "regionHint"})
