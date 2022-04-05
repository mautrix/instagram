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
    client_context: str | None
    receiver: int
    sender: int
    ig_timestamp: int | None

    async def insert(self) -> None:
        q = """
            INSERT INTO message (mxid, mx_room, item_id, client_context, receiver, sender,
                                 ig_timestamp)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """
        await self.db.execute(
            q,
            self.mxid,
            self.mx_room,
            self.item_id,
            self.client_context,
            self.receiver,
            self.sender,
            self.ig_timestamp,
        )

    async def delete(self) -> None:
        q = "DELETE FROM message WHERE item_id=$1 AND receiver=$2"
        await self.db.execute(q, self.item_id, self.receiver)

    @classmethod
    async def delete_all(cls, room_id: RoomID) -> None:
        await cls.db.execute("DELETE FROM message WHERE mx_room=$1", room_id)

    _columns = "mxid, mx_room, item_id, client_context, receiver, sender, ig_timestamp"

    @classmethod
    async def get_by_mxid(cls, mxid: EventID, mx_room: RoomID) -> Message | None:
        q = f"SELECT {cls._columns} FROM message WHERE mxid=$1 AND mx_room=$2"
        row = await cls.db.fetchrow(q, mxid, mx_room)
        if not row:
            return None
        return cls(**row)

    @classmethod
    async def get_last(cls, mx_room: RoomID) -> Message | None:
        q = f"""
        SELECT {cls._columns} FROM message
        WHERE mx_room=$1 AND ig_timestamp IS NOT NULL AND item_id NOT LIKE 'fi.mau.instagram.%'
        ORDER BY ig_timestamp DESC LIMIT 1
        """
        row = await cls.db.fetchrow(q, mx_room)
        if not row:
            return None
        return cls(**row)

    @classmethod
    async def get_closest(cls, mx_room: RoomID, before_ts: int) -> Message | None:
        q = f"""
        SELECT {cls._columns} FROM message
        WHERE mx_room=$1 AND ig_timestamp<=$2 AND item_id NOT LIKE 'fi.mau.instagram.%'
        ORDER BY ig_timestamp DESC LIMIT 1
        """
        row = await cls.db.fetchrow(q, mx_room, before_ts)
        if not row:
            return None
        return cls(**row)

    @classmethod
    async def get_by_item_id(cls, item_id: str, receiver: int) -> Message | None:
        q = f"SELECT {cls._columns} FROM message WHERE item_id=$1 AND receiver=$2"
        row = await cls.db.fetchrow(q, item_id, receiver)
        if not row:
            return None
        return cls(**row)

    @property
    def is_internal(self) -> bool:
        return self.item_id.startswith("fi.mau.instagram.")
