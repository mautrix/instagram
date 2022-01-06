# mautrix-instagram - A Matrix-Instagram puppeting bridge.
# Copyright (C) 2022 Tulir Asokan
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
from __future__ import annotations

from ..errors import IGChallengeWrongCodeError, IGResponseError
from ..types import ChallengeStateResponse
from .base import BaseAndroidAPI


class ChallengeAPI(BaseAndroidAPI):
    @property
    def __path(self) -> str:
        return f"/api/v1{self.state.challenge_path}"

    async def challenge_get_state(self) -> ChallengeStateResponse:
        query = {
            "guid": self.state.device.uuid,
            "device_id": self.state.device.id,
        }
        return self.__handle_resp(
            await self.std_http_get(self.__path, query=query, response_type=ChallengeStateResponse)
        )

    async def challenge_select_method(
        self, choice: str, is_replay: bool = False
    ) -> ChallengeStateResponse:
        path = self.__path
        if is_replay:
            path = path.replace("/challenge/", "/challenge/replay/")
        req = {
            "choice": choice,
            "_csrftoken": self.state.cookies.csrf_token,
            "guid": self.state.device.uuid,
            "device_id": self.state.device.id,
        }
        return self.__handle_resp(
            await self.std_http_post(path, data=req, response_type=ChallengeStateResponse)
        )

    async def challenge_delta_review(self, was_me: bool = True) -> ChallengeStateResponse:
        return await self.challenge_select_method("0" if was_me else "1")

    async def challenge_send_phone_number(self, phone_number: str) -> ChallengeStateResponse:
        req = {
            "phone_number": phone_number,
            "_csrftoken": self.state.cookies.csrf_token,
            "guid": self.state.device.uuid,
            "device_id": self.state.device.id,
        }
        return self.__handle_resp(
            await self.std_http_post(self.__path, data=req, response_type=ChallengeStateResponse)
        )

    async def challenge_send_security_code(self, code: str | int) -> ChallengeStateResponse:
        req = {
            "security_code": code,
            "_csrftoken": self.state.cookies.csrf_token,
            "guid": self.state.device.uuid,
            "device_id": self.state.device.id,
        }
        try:
            return self.__handle_resp(
                await self.std_http_post(
                    self.__path, data=req, response_type=ChallengeStateResponse
                )
            )
        except IGResponseError as e:
            if e.response.status == 400:
                raise IGChallengeWrongCodeError((await e.response.json())["message"]) from e
            raise

    async def challenge_reset(self) -> ChallengeStateResponse:
        req = {
            "_csrftoken": self.state.cookies.csrf_token,
            "guid": self.state.device.uuid,
            "device_id": self.state.device.id,
        }
        return self.__handle_resp(
            await self.std_http_post(
                self.__path.replace("/challenge/", "/challenge/reset/"),
                data=req,
                response_type=ChallengeStateResponse,
            )
        )

    async def challenge_auto(self, reset: bool = False) -> ChallengeStateResponse:
        if reset:
            await self.challenge_reset()
        challenge = self.state.challenge or await self.challenge_get_state()
        if challenge.step_name == "select_verify_method":
            return await self.challenge_select_method(challenge.step_data.choice)
        elif challenge.step_name == "delta_login_review":
            return await self.challenge_delta_review(was_me=True)
        return challenge

    def __handle_resp(self, resp: ChallengeStateResponse) -> ChallengeStateResponse:
        if resp.action == "close":
            self.state.challenge = None
            self.state.challenge_path = None
        else:
            self.state.challenge = resp
        return resp
