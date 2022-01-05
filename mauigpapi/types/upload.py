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
from typing import Any, List, Optional

from attr import dataclass

from mautrix.types import SerializableAttrs


@dataclass
class FinishUploadResponse(SerializableAttrs):
    status: str


@dataclass
class UploadPhotoResponse(SerializableAttrs):
    upload_id: str
    status: str
    xsharing_nonces: Any


@dataclass
class UploadVideoResponse(SerializableAttrs):
    status: str
    xsharing_nonces: Any


@dataclass(kw_only=True)
class ShareVoiceResponseMessage(SerializableAttrs):
    thread_id: Optional[str] = None
    item_id: Optional[str] = None
    timestamp: Optional[str] = None
    client_context: Optional[str] = None
    participant_ids: Optional[List[int]] = None
    message: Optional[str] = None


@dataclass
class ShareVoiceResponse(SerializableAttrs):
    message_metadata: List[ShareVoiceResponseMessage]
    status: str
    upload_id: str

    @property
    def payload(self) -> ShareVoiceResponseMessage:
        return self.message_metadata[0]
