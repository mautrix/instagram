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

    async def insert(self) -> None:
        q = (
            "INSERT INTO reaction (mxid, mx_room, ig_item_id, ig_receiver, ig_sender, reaction) "
            "VALUES ($1, $2, $3, $4, $5, $6)"
        )
        await self.db.execute(
            q,
            self.mxid,
            self.mx_room,
            self.ig_item_id,
            self.ig_receiver,
            self.ig_sender,
            self.reaction,
        )

    async def edit(self, mx_room: RoomID, mxid: EventID, reaction: str) -> None:
        q = (
            "UPDATE reaction SET mxid=$1, mx_room=$2, reaction=$3 "
            "WHERE ig_item_id=$4 AND ig_receiver=$5 AND ig_sender=$6"
        )
        await self.db.execute(
            q, mxid, mx_room, reaction, self.ig_item_id, self.ig_receiver, self.ig_sender
        )

    async def delete(self) -> None:
        q = "DELETE FROM reaction WHERE ig_item_id=$1 AND ig_receiver=$2 AND ig_sender=$3"
        await self.db.execute(q, self.ig_item_id, self.ig_receiver, self.ig_sender)

    @classmethod
    async def get_by_mxid(cls, mxid: EventID, mx_room: RoomID) -> Reaction | None:
        q = (
            "SELECT mxid, mx_room, ig_item_id, ig_receiver, ig_sender, reaction "
            "FROM reaction WHERE mxid=$1 AND mx_room=$2"
        )
        row = await cls.db.fetchrow(q, mxid, mx_room)
        if not row:
            return None
        return cls(**row)

    @classmethod
    async def get_by_item_id(
        cls, ig_item_id: str, ig_receiver: int, ig_sender: int
    ) -> Reaction | None:
        q = (
            "SELECT mxid, mx_room, ig_item_id, ig_receiver, ig_sender, reaction "
            "FROM reaction WHERE ig_item_id=$1 AND ig_sender=$2 AND ig_receiver=$3"
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
        q = (
            "SELECT mxid, mx_room, ig_item_id, ig_receiver, ig_sender, reaction "
            "FROM reaction WHERE ig_item_id=$1 AND ig_receiver=$2"
        )
        rows = await cls.db.fetch(q, ig_item_id, ig_receiver)
        return [cls(**row) for row in rows]
