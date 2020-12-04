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
from ..errors import IGResponseError


class LogAttributionAPI(BaseAndroidAPI):
    async def log_attribution(self):
        resp = await self.http.get(self.url / "api/v1/attribution/log_attribution/",
                                   data=self.sign({"adid": self.state.device.adid}))
        # TODO parse response content
        return await self.handle_response(resp)

    async def log_resurrect_attribution(self):
        req = {
            "_csrftoken": self.state.cookies.csrf_token,
            "_uid": self.state.cookies.user_id,
            "adid": self.state.device.adid,
            "_uuid": self.state.device.uuid,
        }
        resp = await self.http.get(self.url / "api/v1/attribution/log_resurrect_attribution/",
                                   data=self.sign(req))
        # Apparently this throws an error in the official app, so we catch it and return the error
        try:
            return await self.handle_response(resp)
        except IGResponseError as e:
            return e
