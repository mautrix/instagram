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
from typing import Any

from attr import dataclass
from mautrix.types import SerializableAttrs


@dataclass
class DirectInboxResponse(SerializableAttrs['DirectInboxFeedResponse']):
    status: str
    seq_id: int
    snapshot_at_ms: int
    pending_requests_total: int
    # TODO
    inbox: Any
    most_recent_inviter: Any = None
