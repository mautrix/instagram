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
        self.log.debug("Fetching current challenge state")
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
        self.log.debug(f"Selecting challenge method {choice} (replay: {is_replay})")
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
        self.log.debug("Sending challenge phone number")
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
            self.log.debug("Sending challenge security code")
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
        self.log.debug("Resetting challenge")
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
            self.log.debug(
                "Got select_verify_method challenge step, "
                f"auto-selecting {challenge.step_data.choice}"
            )
            return await self.challenge_select_method(challenge.step_data.choice)
        elif challenge.step_name == "delta_login_review":
            self.log.debug("Got delta_login_review challenge step, auto-selecting was_me=True")
            return await self.challenge_delta_review(was_me=True)
        else:
            self.log.debug(f"Got unknown challenge step {challenge.step_name}, not doing anything")
        return challenge

    def __handle_resp(self, resp: ChallengeStateResponse) -> ChallengeStateResponse:
        if resp.action == "close":
            self.log.debug(
                f"Challenge closed (step: {resp.step_name}, has user: {bool(resp.logged_in_user)})"
            )
            self.state.challenge = None
            self.state.challenge_path = None
        else:
            self.state.challenge = resp
        return resp
