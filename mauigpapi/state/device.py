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
from uuid import UUID
import json
import pkgutil
import random
import string
import time

from attr import dataclass
import attr

from mautrix.types import SerializableAttrs

builds = json.loads(pkgutil.get_data("mauigpapi.state", "samples/builds.json"))
descriptors = json.loads(pkgutil.get_data("mauigpapi.state", "samples/devices.json"))


@dataclass
class AndroidDevice(SerializableAttrs):
    id: Optional[str] = None
    descriptor: Optional[str] = None
    uuid: Optional[str] = None
    phone_id: Optional[str] = attr.ib(default=None, metadata={"json": "phoneId"})
    # Google Play advertising ID
    adid: Optional[str] = None
    build: Optional[str] = None

    language: str = "en_US"
    radio_type: str = "wifi-none"
    connection_type: str = "WIFI"
    timezone_offset: str = str(-time.timezone)
    is_layout_rtl: bool = False

    @property
    def battery_level(self) -> int:
        rand = random.Random(self.id)
        percent_time = rand.randint(200, 600)
        return 100 - round(time.time() / percent_time) % 100

    @property
    def is_charging(self) -> bool:
        rand = random.Random(f"{self.id}{round(time.time() / 10800)}")
        return rand.choice([True, False])

    @property
    def payload(self) -> dict:
        device_parts = self.descriptor.split(";")
        android_version, android_release, *_ = device_parts[0].split("/")
        manufacturer, *_ = device_parts[3].split("/")
        model = device_parts[4]
        return {
            "android_version": android_version,
            "android_release": android_release,
            "manufacturer": manufacturer,
            "model": model,
        }

    def generate(self, seed: Union[str, bytes]) -> None:
        rand = random.Random(seed)
        self.phone_id = str(UUID(int=rand.getrandbits(128), version=4))
        self.adid = str(UUID(int=rand.getrandbits(128), version=4))
        self.id = f"android-{''.join(rand.choices(string.hexdigits, k=16))}"
        self.descriptor = rand.choice(descriptors)
        self.uuid = str(UUID(int=rand.getrandbits(128), version=4))
        self.build = rand.choice(builds)
