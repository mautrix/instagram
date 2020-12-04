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
from typing import List, Awaitable, Any
import random

from ..types import LoginResponse
from .account import AccountAPI
from .login import LoginAPI
from .qe import QeSyncAPI
from .zr import ZRTokenAPI
from .attribution import LogAttributionAPI
from .launcher import LauncherSyncAPI


class LoginSimulateAPI(AccountAPI, LogAttributionAPI, QeSyncAPI, ZRTokenAPI, LoginAPI,
                       LauncherSyncAPI):
    @property
    def _pre_login_flow_requests(self) -> List[Awaitable[Any]]:
        return [
            self.read_msisdn_header(),
            self.msisdn_header_bootstrap("ig_select_app"),
            self.zr_token_result(),
            self.contact_point_prefill("prefill"),
            self.launcher_pre_login_sync(),
            self.qe_sync_login_experiments(),
            self.log_attribution(),
            self.get_prefill_candidates(),
        ]

    @property
    def _post_login_flow_requests(self) -> List[Awaitable[Any]]:
        return [
            self.zr_token_result(),
            self.launcher_post_login_sync(),
            self.qe_sync_experiments(),
            self.log_attribution(),
            self.log_resurrect_attribution(),

            self._facebook_ota(),
        ]

    async def simulate_pre_login_flow(self) -> None:
        items = self._pre_login_flow_requests
        random.shuffle(items)
        for item in items:
            await item

    async def simulate_post_login_flow(self) -> None:
        items = self._post_login_flow_requests
        random.shuffle(items)
        for item in items:
            await item

    async def _facebook_ota(self):
        query = {
            "fields": self.state.application.FACEBOOK_OTA_FIELDS,
            "custom_user_id": self.state.cookies.user_id,
            "signed_body": "SIGNATURE.",
            "version_code": self.state.application.APP_VERSION_CODE,
            "version_name": self.state.application.APP_VERSION,
            "custom_app_id": self.state.application.FACEBOOK_ORCA_APPLICATION_ID,
            "custom_device_id": self.state.device.uuid,
        }
        # TODO parse response?
        return await self.std_http_get("/api/v1/facebook_ota/", query=query)

    async def upgrade_login(self) -> LoginResponse:
        user_id = self.state.cookies.user_id
        resp = await self.logout(one_tap_app_login=True)
        return await self.one_tap_app_login(user_id, resp.login_nonce)
