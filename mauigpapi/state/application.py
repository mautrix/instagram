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
    APP_VERSION: str = "294.0.0.33.87"
    APP_VERSION_CODE: str = "500160596"
    FACEBOOK_ANALYTICS_APPLICATION_ID: str = "567067343352427"

    BLOKS_VERSION_ID: str = "4cf8328dae765ededd07d166b6774eeb1eb23c13979a715d6bd2ea9d06bb0560"
    CAPABILITIES: str = "3brTv10="
