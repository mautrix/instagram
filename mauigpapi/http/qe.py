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
from ..errors import IGCookieNotFoundError
from ..types import QeSyncResponse
from .base import BaseAndroidAPI


class QeSyncAPI(BaseAndroidAPI):
    async def qe_sync_experiments(self) -> QeSyncResponse:
        return await self.__sync(self.state.application.EXPERIMENTS)

    async def qe_sync_login_experiments(self) -> QeSyncResponse:
        return await self.__sync(self.state.application.LOGIN_EXPERIMENTS)

    async def __sync(self, experiments: str) -> QeSyncResponse:
        try:
            uid = self.state.cookies.user_id
        except IGCookieNotFoundError:
            req = {"id": self.state.device.uuid}
        else:
            req = {
                "_csrftoken": self.state.cookies.csrf_token,
                "id": uid,
                "_uid": uid,
                "_uuid": self.state.device.uuid,
            }
        req["experiments"] = experiments
        resp = await self.std_http_post("/api/v1/qe/sync/", data=req, response_type=QeSyncResponse)
        self.state.experiments.update(resp)
        return resp
