# mautrix-instagram - A Matrix-Instagram puppeting bridge.
# Copyright (C) 2023 Tulir Asokan
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
from attr import dataclass

from mautrix.types import SerializableAttrs


@dataclass
class AndroidApplication(SerializableAttrs):
    APP_VERSION: str = "279.0.0.23.112"
    APP_VERSION_CODE: str = "466535821"
    FACEBOOK_ANALYTICS_APPLICATION_ID: str = "567067343352427"

    BLOKS_VERSION_ID: str = "2fecedb8f3d321e9fc9b22f9693830c31650ff5b50516bdde984ff1b2090d2ac"
    CAPABILITIES: str = "3brTv10="
