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

import random
import time

from yarl import URL

from ..types import FacebookUploadResponse
from .base import BaseAndroidAPI


class UploadAPI(BaseAndroidAPI):
    rupload_fb = URL("https://rupload.facebook.com")

    def _make_rupload_headers(self, length: int, name: str, mime: str) -> dict[str, str]:
        return {
            **self._rupload_headers,
            "x-entity-length": str(length),
            "x-entity-name": name,
            "x-entity-type": mime,
            "offset": "0",
            "Content-Type": "application/octet-stream",
            "priority": "u=6, i",
        }

    async def upload(
        self,
        data: bytes,
        mimetype: str,
        upload_id: str | None = None,
    ) -> FacebookUploadResponse:
        upload_id = upload_id or str(int(time.time() * 1000))
        name = f"{upload_id}_0_{random.randint(1000000000, 9999999999)}"
        headers = self._make_rupload_headers(len(data), name, mimetype)
        if mimetype.startswith("image/"):
            path_type = "messenger_gif" if mimetype == "image/gif" else "messenger_image"
            headers["image_type"] = "FILE_ATTACHMENT"
        elif mimetype.startswith("video/"):
            path_type = "messenger_video"
            headers["video_type"] = "FILE_ATTACHMENT"
        elif mimetype.startswith("audio/"):
            path_type = "messenger_audio"
            headers["audio_type"] = "VOICE_MESSAGE"
        else:
            path_type = "messenger_file"
            headers["file_type"] = "FILE_ATTACHMENT"
        return await self.std_http_post(
            f"/{path_type}/{name}",
            url_override=self.rupload_fb,
            default_headers=False,
            headers=headers,
            data=data,
            raw=True,
            response_type=FacebookUploadResponse,
        )
