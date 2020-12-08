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
from typing import Optional, Dict, Any
from uuid import uuid4
import random
import time
import json

from .base import BaseAndroidAPI
from ..types import UploadPhotoResponse, MediaType


class UploadAPI(BaseAndroidAPI):
    async def upload_jpeg_photo(self, data: bytes, upload_id: Optional[str] = None,
                                is_sidecar: bool = False, waterfall_id: Optional[str] = None,
                                media_type: MediaType = MediaType.IMAGE) -> UploadPhotoResponse:
        upload_id = upload_id or str(int(time.time() * 1000))
        name = f"{upload_id}_0_{random.randint(1000000000, 9999999999)}"
        params = {
            "retry_context": json.dumps({
                "num_step_auto_retry": 0,
                "num_reupload": 0,
                "num_step_manual_retry": 0,
            }),
            "media_type": str(media_type.value),
            "upload_id": upload_id,
            "xsharing_user_ids": json.dumps([]),
            "image_compression": json.dumps({
                "lib_name": "moz",
                "lib_version": "3.1.m",
                "quality": 80
            }),
        }
        if is_sidecar:
            params["is_sidecar"] = "1"
        headers = {
            "X_FB_PHOTO_WATERFALL_ID": waterfall_id or str(uuid4()),
            "X-Entity-Type": "image/jpeg",
            "Offset": "0",
            "X-Instagram-Rupload-Params": json.dumps(params),
            "X-Entity-Name": name,
            "X-Entity-Length": str(len(data)),
            "Content-Type": "application/octet-stream",
        }
        return await self.std_http_post(f"/rupload_igphoto/{name}", headers=headers, data=data,
                                        raw=True, response_type=UploadPhotoResponse)

    async def finish_upload(self, upload_id: str, source_type: str):
        headers = {
            "retry_context": json.dumps({
                "num_step_auto_retry": 0,
                "num_reupload": 0,
                "num_step_manual_retry": 0,
            }),
        }
        req = {
            "timezone_offset": self.state.device.timezone_offset,
            "_csrftoken": self.state.cookies.csrf_token,
            "source_type": source_type,
            "_uid": self.state.cookies.user_id,
            "device_id": self.state.device.id,
            "_uuid": self.state.device.uuid,
            "upload_id": upload_id,
            "device": self.state.device.payload,
        }
        return await self.std_http_post("/api/v1/media/upload_finish/", headers=headers, data=req)
