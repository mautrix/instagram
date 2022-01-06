# mautrix-instagram - A Matrix-Instagram puppeting bridge.
# Copyright (C) 2021 Tulir Asokan
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
from typing import Optional
from uuid import UUID
import random
import time

from attr import dataclass

from mautrix.types import SerializableAttrs, field

from ..errors import IGCookieNotFoundError, IGNoCheckpointError, IGUserIDNotFoundError
from ..types import ChallengeStateResponse
from .application import AndroidApplication
from .cookies import Cookies
from .device import AndroidDevice
from .experiments import AndroidExperiments
from .session import AndroidSession


@dataclass
class AndroidState(SerializableAttrs):
    device: AndroidDevice = field(factory=lambda: AndroidDevice())
    session: AndroidSession = field(factory=lambda: AndroidSession())
    application: AndroidApplication = field(factory=lambda: AndroidApplication())
    experiments: AndroidExperiments = field(factory=lambda: AndroidExperiments(), hidden=True)
    client_session_id_lifetime: int = 1_200_000
    pigeon_session_id_lifetime: int = 1_200_000
    challenge: Optional[ChallengeStateResponse] = None
    _challenge_path: Optional[str] = field(default=None, json="challenge_path")
    cookies: Cookies = field(factory=lambda: Cookies())

    def __attrs_post_init__(self) -> None:
        if self.application.APP_VERSION_CODE != AndroidApplication().APP_VERSION_CODE:
            self.application = AndroidApplication()

    @property
    def client_session_id(self) -> str:
        return str(self._gen_temp_uuid("clientSessionId", self.client_session_id_lifetime))

    @property
    def pigeon_session_id(self) -> str:
        return str(self._gen_temp_uuid("pigeonSessionId", self.pigeon_session_id_lifetime))

    @property
    def user_agent(self) -> str:
        return (
            f"Instagram {self.application.APP_VERSION} Android ({self.device.descriptor}; "
            f"{self.device.language}; {self.application.APP_VERSION_CODE})"
        )

    @property
    def user_id(self) -> str:
        try:
            return self.cookies.user_id
        except IGCookieNotFoundError:
            if not self.challenge or not self.challenge.user_id:
                raise IGUserIDNotFoundError()
            return str(self.challenge.user_id)

    @property
    def challenge_path(self) -> str:
        if not self._challenge_path:
            raise IGNoCheckpointError()
        return self._challenge_path

    @challenge_path.setter
    def challenge_path(self, val: str) -> None:
        self._challenge_path = val

    @staticmethod
    def gen_client_context() -> str:
        return str((int(time.time() * 1000) << 22) + random.randint(10000, 5000000))

    def _gen_temp_uuid(self, seed: str, lifetime: int) -> UUID:
        rand = random.Random(f"{seed}{self.device.id}{round(time.time() * 1000 / lifetime)}")
        return UUID(int=rand.getrandbits(128), version=4)
