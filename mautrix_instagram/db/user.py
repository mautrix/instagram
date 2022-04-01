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
import asyncpg

from mauigpapi.state import AndroidState
from mautrix.types import RoomID, UserID
from mautrix.util.async_db import Database

fake_db = Database.create("") if TYPE_CHECKING else None


@dataclass
class User:
    db: ClassVar[Database] = fake_db

    mxid: UserID
    igpk: int | None
    state: AndroidState | None
    notice_room: RoomID | None

    async def insert(self) -> None:
        q = 'INSERT INTO "user" (mxid, igpk, state, notice_room) VALUES ($1, $2, $3, $4)'
        await self.db.execute(
            q, self.mxid, self.igpk, self.state.json() if self.state else None, self.notice_room
        )

    async def update(self) -> None:
        q = 'UPDATE "user" SET igpk=$2, state=$3, notice_room=$4 WHERE mxid=$1'
        await self.db.execute(
            q, self.mxid, self.igpk, self.state.json() if self.state else None, self.notice_room
        )

    @classmethod
    def _from_row(cls, row: asyncpg.Record) -> User:
        data = {**row}
        state_str = data.pop("state")
        return cls(state=AndroidState.parse_json(state_str) if state_str else None, **data)

    @classmethod
    async def get_by_mxid(cls, mxid: UserID) -> User | None:
        q = 'SELECT mxid, igpk, state, notice_room FROM "user" WHERE mxid=$1'
        row = await cls.db.fetchrow(q, mxid)
        if not row:
            return None
        return cls._from_row(row)

    @classmethod
    async def get_by_igpk(cls, igpk: int) -> User | None:
        q = 'SELECT mxid, igpk, state, notice_room FROM "user" WHERE igpk=$1'
        row = await cls.db.fetchrow(q, igpk)
        if not row:
            return None
        return cls._from_row(row)

    @classmethod
    async def all_logged_in(cls) -> list[User]:
        q = 'SELECT mxid, igpk, state, notice_room FROM "user" WHERE igpk IS NOT NULL'
        rows = await cls.db.fetch(q)
        return [cls._from_row(row) for row in rows]
