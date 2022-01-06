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

from typing import Type, TypeVar
import json

from ..types import CurrentUserResponse
from .base import BaseAndroidAPI

T = TypeVar("T")


class AccountAPI(BaseAndroidAPI):
    async def current_user(self) -> CurrentUserResponse:
        return await self.std_http_get(
            f"/api/v1/accounts/current_user/",
            query={"edit": "true"},
            response_type=CurrentUserResponse,
        )

    async def set_biography(self, text: str) -> CurrentUserResponse:
        # TODO entities?
        return await self.__command("set_biography", device_id=self.state.device.id, raw_text=text)

    async def set_profile_picture(self, upload_id: str) -> CurrentUserResponse:
        return await self.__command(
            "change_profile_picture", use_fbuploader="true", upload_id=upload_id
        )

    async def remove_profile_picture(self) -> CurrentUserResponse:
        return await self.__command("remove_profile_picture")

    async def set_private(self, private: bool) -> CurrentUserResponse:
        return await self.__command("set_private" if private else "set_public")

    async def confirm_email(self, slug: str) -> CurrentUserResponse:
        # slug can contain slashes, but it shouldn't start or end with one
        return await self.__command(f"confirm_email/{slug}")

    async def send_recovery_flow_email(self, query: str):
        req = {
            "_csrftoken": self.state.cookies.csrf_token,
            "adid": "",
            "guid": self.state.device.uuid,
            "device_id": self.state.device.id,
            "query": query,
        }
        # TODO parse response content
        return await self.std_http_post(f"/api/v1/accounts/send_recovery_flow_email/", data=req)

    async def edit_profile(
        self,
        external_url: str | None = None,
        gender: str | None = None,
        phone_number: str | None = None,
        username: str | None = None,
        # TODO should there be a last_name?
        first_name: str | None = None,
        biography: str | None = None,
        email: str | None = None,
    ) -> CurrentUserResponse:
        return await self.__command(
            "edit_profile",
            device_id=self.state.device.id,
            email=email,
            external_url=external_url,
            first_name=first_name,
            username=username,
            phone_number=phone_number,
            gender=gender,
            biography=biography,
        )

    async def __command(
        self, command: str, response_type: Type[T] = CurrentUserResponse, **kwargs: str
    ) -> T:
        req = {
            "_csrftoken": self.state.cookies.csrf_token,
            "_uid": self.state.cookies.user_id,
            "_uuid": self.state.device.uuid,
            **kwargs,
        }
        return await self.std_http_post(
            f"/api/v1/accounts/{command}/",
            data=req,
            filter_nulls=True,
            response_type=response_type,
        )

    async def read_msisdn_header(self, usage: str = "default"):
        req = {
            "mobile_subno_usage": usage,
            "device_id": self.state.device.uuid,
        }
        return await self.std_http_post("/api/v1/accounts/read_msisdn_header/", data=req)

    async def msisdn_header_bootstrap(self, usage: str = "default"):
        req = {
            "mobile_subno_usage": usage,
            "device_id": self.state.device.uuid,
        }
        return await self.std_http_post("/api/v1/accounts/msisdn_header_bootstrap/", data=req)

    async def contact_point_prefill(self, usage: str = "default"):
        req = {
            "mobile_subno_usage": usage,
            "device_id": self.state.device.uuid,
        }
        return await self.std_http_post("/api/v1/accounts/contact_point_prefill/", data=req)

    async def get_prefill_candidates(self):
        req = {
            "android_device_id": self.state.device.id,
            "usages": json.dumps(["account_recovery_omnibox"]),
            "device_id": self.state.device.uuid,
        }
        # TODO parse response content
        return await self.std_http_post("/api/v1/accounts/get_prefill_candidates/", data=req)

    async def process_contact_point_signals(self):
        req = {
            "phone_id": self.state.device.phone_id,
            "_csrftoken": self.state.cookies.csrf_token,
            "_uid": self.state.cookies.user_id,
            "device_id": self.state.device.uuid,
            "_uuid": self.state.device.uuid,
            "google_tokens": json.dumps([]),
        }
        return await self.std_http_post(
            "/api/v1/accounts/process_contact_point_signals/", data=req
        )
