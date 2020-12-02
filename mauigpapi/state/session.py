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

from mautrix.types import SerializableAttrs, dataclass, field


@dataclass
class AndroidSession(SerializableAttrs['AndroidSession']):
    eu_dc_enabled: Optional[bool] = field(default=None, json="euDCEnabled")
    thumbnail_cache_busting_value: int = field(default=1000, json="thumbnailCacheBustingValue")
    ads_opt_out: bool = field(default=None, json="adsOptOut")

    ig_www_claim: Optional[str] = field(default=None, json="igWWWClaim")
    authorization: Optional[str] = None
    password_encryption_pubkey: Optional[str] = field(default=None, json="passwordEncryptionPubKey")
    password_encryption_key_id: Union[None, str, int] = field(default=None, json="passwordEncryptionKeyId")
    region_hint: Optional[str] = field(default=None, json="regionHint")
