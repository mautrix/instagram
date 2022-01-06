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
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from attr import dataclass

from mautrix.types import EventID, RoomID
from mautrix.util.async_db import Database

fake_db = Database.create("") if TYPE_CHECKING else None


@dataclass
class Message:
    db: ClassVar[Database] = fake_db

    mxid: EventID
    mx_room: RoomID
    item_id: str
    receiver: int
    sender: int

    async def insert(self) -> None:
        q = (
            "INSERT INTO message (mxid, mx_room, item_id, receiver, sender) "
            "VALUES ($1, $2, $3, $4, $5)"
        )
        await self.db.execute(q, self.mxid, self.mx_room, self.item_id, self.receiver, self.sender)

    async def delete(self) -> None:
        q = "DELETE FROM message WHERE item_id=$1 AND receiver=$2"
        await self.db.execute(q, self.item_id, self.receiver)

    @classmethod
    async def delete_all(cls, room_id: RoomID) -> None:
        await cls.db.execute("DELETE FROM message WHERE mx_room=$1", room_id)

    @classmethod
    async def get_by_mxid(cls, mxid: EventID, mx_room: RoomID) -> Message | None:
        q = (
            "SELECT mxid, mx_room, item_id, receiver, sender "
            "FROM message WHERE mxid=$1 AND mx_room=$2"
        )
        row = await cls.db.fetchrow(q, mxid, mx_room)
        if not row:
            return None
        return cls(**row)

    @classmethod
    async def get_by_item_id(cls, item_id: str, receiver: int) -> Message | None:
        q = (
            "SELECT mxid, mx_room, item_id, receiver, sender "
            "FROM message WHERE item_id=$1 AND receiver=$2"
        )
        row = await cls.db.fetchrow(q, item_id, receiver)
        if not row:
            return None
        return cls(**row)

    @property
    def is_internal(self) -> bool:
        return self.item_id.startswith("fi.mau.instagram.")
