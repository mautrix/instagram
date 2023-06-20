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
    APP_VERSION: str = "287.0.0.25.77"
    APP_VERSION_CODE: str = "483850216"
    FACEBOOK_ANALYTICS_APPLICATION_ID: str = "567067343352427"

    BLOKS_VERSION_ID: str = "2ea4bf9bc876166cf5827959414cb0ac923a49e48c8b91e3e4ad3f92efd4fa4c"
    CAPABILITIES: str = "3brTv10="
