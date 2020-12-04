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
from .base import BaseAndroidAPI


class ZRTokenAPI(BaseAndroidAPI):
    async def zr_token_result(self):
        url = (self.url / "api/v1/zr/token/result/").with_query({
            "device_id": self.state.device.id,
            "token_hash": "",
            "custom_device_id": self.state.device.uuid,
            "fetch_reason": "token_expired",
        })
        resp = await self.http.get(url)
        # TODO parse response content
        return await self.handle_response(resp)
