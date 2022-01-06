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

from uuid import uuid4
import json
import random
import time

from ..types import FinishUploadResponse, MediaType, UploadPhotoResponse, UploadVideoResponse
from .base import BaseAndroidAPI


class UploadAPI(BaseAndroidAPI):
    async def upload_photo(
        self,
        data: bytes,
        mime: str,
        upload_id: str | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> UploadPhotoResponse:
        upload_id = upload_id or str(int(time.time() * 1000))
        name = f"{upload_id}_0_{random.randint(1000000000, 9999999999)}"
        params = {
            "retry_context": json.dumps(
                {
                    "num_step_auto_retry": 0,
                    "num_reupload": 0,
                    "num_step_manual_retry": 0,
                }
            ),
            "media_type": str(MediaType.IMAGE.value),
            "upload_id": upload_id,
            "xsharing_user_ids": json.dumps([]),
        }
        if mime == "image/jpeg":
            params["image_compression"] = json.dumps(
                {"lib_name": "moz", "lib_version": "3.1.m", "quality": 80}
            )
        if width and height:
            params["original_width"] = str(width)
            params["original_height"] = str(height)
        headers = {
            "X_FB_PHOTO_WATERFALL_ID": str(uuid4()),
            "X-Entity-Type": mime,
            "Offset": "0",
            "X-Instagram-Rupload-Params": json.dumps(params),
            "X-Entity-Name": name,
            "X-Entity-Length": str(len(data)),
            "Content-Type": "application/octet-stream",
            "priority": "u=6, i",
        }
        return await self.std_http_post(
            f"/rupload_igphoto/{name}",
            headers=headers,
            data=data,
            raw=True,
            response_type=UploadPhotoResponse,
        )

    async def upload_mp4(
        self,
        data: bytes,
        upload_id: str | None = None,
        audio: bool = False,
        duration_ms: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> tuple[UploadVideoResponse, str]:
        upload_id = upload_id or str(int(time.time() * 1000))
        name = f"{upload_id}_0_{random.randint(1000000000, 9999999999)}"
        media_type = MediaType.AUDIO if audio else MediaType.VIDEO
        params: dict[str, str] = {
            "retry_context": json.dumps(
                {
                    "num_step_auto_retry": 0,
                    "num_reupload": 0,
                    "num_step_manual_retry": 0,
                }
            ),
            "media_type": str(media_type.value),
            "upload_id": upload_id,
            "xsharing_user_ids": json.dumps([]),
        }
        if duration_ms:
            params["upload_media_duration_ms"] = str(duration_ms)
        if audio:
            params["is_direct_voice"] = "1"
        else:
            params["direct_v2"] = "1"
            params["for_direct_story"] = "1"
            params["content_tags"] = "use_default_cover"
            params["extract_cover_frame"] = "1"
            if width and height:
                params["upload_media_width"] = str(width)
                params["upload_media_height"] = str(height)
        headers = {
            "X_FB_VIDEO_WATERFALL_ID": str(uuid4()),
            "X-Entity-Type": "audio/mp4" if audio else "video/mp4",
            "Offset": "0",
            "X-Instagram-Rupload-Params": json.dumps(params),
            "X-Entity-Name": name,
            "X-Entity-Length": str(len(data)),
            "Content-Type": "application/octet-stream",
            "priority": "u=6, i",
        }
        if not audio:
            headers["segment-type"] = "3"
            headers["segment-start-offset"] = "0"
        return (
            await self.std_http_post(
                f"/rupload_igvideo/{name}",
                headers=headers,
                data=data,
                raw=True,
                response_type=UploadVideoResponse,
            ),
            upload_id,
        )

    async def finish_upload(
        self, upload_id: str, source_type: str, video: bool = False
    ) -> FinishUploadResponse:
        headers = {
            "retry_context": json.dumps(
                {
                    "num_step_auto_retry": 0,
                    "num_reupload": 0,
                    "num_step_manual_retry": 0,
                }
            ),
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
        query = {}
        if video:
            query["video"] = "1"
        return await self.std_http_post(
            "/api/v1/media/upload_finish/",
            headers=headers,
            data=req,
            query=query,
            response_type=FinishUploadResponse,
        )
