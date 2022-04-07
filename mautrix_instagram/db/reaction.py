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
class Reaction:
    db: ClassVar[Database] = fake_db

    mxid: EventID
    mx_room: RoomID
    ig_item_id: str
    ig_receiver: int
    ig_sender: int
    reaction: str
    mx_timestamp: int | None

    async def insert(self) -> None:
        q = """
        INSERT INTO reaction (mxid, mx_room, ig_item_id, ig_receiver, ig_sender, reaction,
                              mx_timestamp)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """
        await self.db.execute(
            q,
            self.mxid,
            self.mx_room,
            self.ig_item_id,
            self.ig_receiver,
            self.ig_sender,
            self.reaction,
            self.mx_timestamp,
        )

    async def edit(self, mx_room: RoomID, mxid: EventID, reaction: str, mx_timestamp: int) -> None:
        q = """
        UPDATE reaction SET mxid=$1, mx_room=$2, reaction=$3, mx_timestamp=$4
        WHERE ig_item_id=$5 AND ig_receiver=$6 AND ig_sender=$7
        """
        await self.db.execute(
            q,
            mxid,
            mx_room,
            reaction,
            mx_timestamp,
            self.ig_item_id,
            self.ig_receiver,
            self.ig_sender,
        )

    async def delete(self) -> None:
        q = "DELETE FROM reaction WHERE ig_item_id=$1 AND ig_receiver=$2 AND ig_sender=$3"
        await self.db.execute(q, self.ig_item_id, self.ig_receiver, self.ig_sender)

    _columns = "mxid, mx_room, ig_item_id, ig_receiver, ig_sender, reaction, mx_timestamp"

    @classmethod
    async def get_by_mxid(cls, mxid: EventID, mx_room: RoomID) -> Reaction | None:
        q = f"SELECT {cls._columns} FROM reaction WHERE mxid=$1 AND mx_room=$2"
        row = await cls.db.fetchrow(q, mxid, mx_room)
        if not row:
            return None
        return cls(**row)

    @classmethod
    async def get_by_item_id(
        cls, ig_item_id: str, ig_receiver: int, ig_sender: int
    ) -> Reaction | None:
        q = (
            f"SELECT {cls._columns} FROM reaction"
            " WHERE ig_item_id=$1 AND ig_sender=$2 AND ig_receiver=$3"
        )
        row = await cls.db.fetchrow(q, ig_item_id, ig_sender, ig_receiver)
        if not row:
            return None
        return cls(**row)

    @classmethod
    async def count(cls, ig_item_id: str, ig_receiver: int) -> int:
        q = "SELECT COUNT(*) FROM reaction WHERE ig_item_id=$1 AND ig_receiver=$2"
        return await cls.db.fetchval(q, ig_item_id, ig_receiver)

    @classmethod
    async def get_all_by_item_id(cls, ig_item_id: str, ig_receiver: int) -> list[Reaction]:
        q = f"SELECT {cls._columns} FROM reaction WHERE ig_item_id=$1 AND ig_receiver=$2"
        rows = await cls.db.fetch(q, ig_item_id, ig_receiver)
        return [cls(**row) for row in rows]

    @classmethod
    async def get_closest(cls, mx_room: RoomID, before_ts: int) -> Reaction | None:
        q = f"""
        SELECT {cls._columns} FROM reaction WHERE mx_room=$1 AND mx_timestamp<=$2
        ORDER BY mx_timestamp DESC LIMIT 1
        """
        row = await cls.db.fetchrow(q, mx_room, before_ts)
        if not row:
            return None
        return cls(**row)
