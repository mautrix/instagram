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
import asyncpg

from mautrix.types import ContentURI, RoomID, UserID
from mautrix.util.async_db import Database

fake_db = Database.create("") if TYPE_CHECKING else None


@dataclass
class Portal:
    db: ClassVar[Database] = fake_db

    thread_id: str
    receiver: int
    other_user_pk: int | None
    mxid: RoomID | None
    name: str | None
    avatar_url: ContentURI | None
    encrypted: bool
    name_set: bool
    avatar_set: bool
    relay_user_id: UserID | None

    @property
    def _values(self):
        return (
            self.thread_id,
            self.receiver,
            self.other_user_pk,
            self.mxid,
            self.name,
            self.avatar_url,
            self.encrypted,
            self.name_set,
            self.avatar_set,
            self.relay_user_id,
        )

    async def insert(self) -> None:
        q = (
            "INSERT INTO portal (thread_id, receiver, other_user_pk, mxid, name, avatar_url, "
            "                    encrypted, name_set, avatar_set, relay_user_id) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)"
        )
        await self.db.execute(q, *self._values)

    async def update(self) -> None:
        q = (
            "UPDATE portal SET other_user_pk=$3, mxid=$4, name=$5, avatar_url=$6, encrypted=$7,"
            "                  name_set=$8, avatar_set=$9, relay_user_id=$10 "
            "WHERE thread_id=$1 AND receiver=$2"
        )
        await self.db.execute(q, *self._values)

    @classmethod
    def _from_row(cls, row: asyncpg.Record) -> Portal:
        return cls(**row)

    @classmethod
    async def get_by_mxid(cls, mxid: RoomID) -> Portal | None:
        q = (
            "SELECT thread_id, receiver, other_user_pk, mxid, name, avatar_url, encrypted, "
            "       name_set, avatar_set, relay_user_id "
            "FROM portal WHERE mxid=$1"
        )
        row = await cls.db.fetchrow(q, mxid)
        if not row:
            return None
        return cls._from_row(row)

    @classmethod
    async def get_by_thread_id(
        cls, thread_id: str, receiver: int, rec_must_match: bool = True
    ) -> Portal | None:
        q = (
            "SELECT thread_id, receiver, other_user_pk, mxid, name, avatar_url, encrypted, "
            "       name_set, avatar_set, relay_user_id "
            "FROM portal WHERE thread_id=$1 AND receiver=$2"
        )
        if not rec_must_match:
            q = (
                "SELECT thread_id, receiver, other_user_pk, mxid, name, avatar_url, encrypted, "
                "       name_set, avatar_set "
                "FROM portal WHERE thread_id=$1 AND (receiver=$2 OR receiver=0)"
            )
        row = await cls.db.fetchrow(q, thread_id, receiver)
        if not row:
            return None
        return cls._from_row(row)

    @classmethod
    async def find_private_chats_of(cls, receiver: int) -> list[Portal]:
        q = (
            "SELECT thread_id, receiver, other_user_pk, mxid, name, avatar_url, encrypted, "
            "       name_set, avatar_set, relay_user_id "
            "FROM portal WHERE receiver=$1 AND other_user_pk IS NOT NULL"
        )
        rows = await cls.db.fetch(q, receiver)
        return [cls._from_row(row) for row in rows]

    @classmethod
    async def find_private_chats_with(cls, other_user: int) -> list[Portal]:
        q = (
            "SELECT thread_id, receiver, other_user_pk, mxid, name, avatar_url, encrypted, "
            "       name_set, avatar_set, relay_user_id "
            "FROM portal WHERE other_user_pk=$1"
        )
        rows = await cls.db.fetch(q, other_user)
        return [cls._from_row(row) for row in rows]

    @classmethod
    async def find_private_chat_id(cls, receiver: int, other_user: int) -> str | None:
        q = "SELECT thread_id FROM portal WHERE receiver=$1 AND other_user_pk=$2"
        return await cls.db.fetchval(q, receiver, other_user)

    @classmethod
    async def all_with_room(cls) -> list[Portal]:
        q = (
            "SELECT thread_id, receiver, other_user_pk, mxid, name, avatar_url, encrypted, "
            "       name_set, avatar_set, relay_user_id "
            "FROM portal WHERE mxid IS NOT NULL"
        )
        rows = await cls.db.fetch(q)
        return [cls._from_row(row) for row in rows]
