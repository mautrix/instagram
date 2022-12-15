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

from asyncpg import Record
from attr import dataclass

from mautrix.types import BatchID, ContentURI, EventID, RoomID, UserID
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
    first_event_id: EventID | None
    next_batch_id: BatchID | None
    historical_base_insertion_event_id: EventID | None
    cursor: str | None
    thread_image_id: int | None

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
            self.first_event_id,
            self.next_batch_id,
            self.historical_base_insertion_event_id,
            self.cursor,
            self.thread_image_id,
        )

    column_names = ",".join(
        (
            "thread_id",
            "receiver",
            "other_user_pk",
            "mxid",
            "name",
            "avatar_url",
            "encrypted",
            "name_set",
            "avatar_set",
            "relay_user_id",
            "first_event_id",
            "next_batch_id",
            "historical_base_insertion_event_id",
            "cursor",
            "thread_image_id",
        )
    )

    async def insert(self) -> None:
        q = (
            f"INSERT INTO portal ({self.column_names}) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)"
        )
        await self.db.execute(q, *self._values)

    async def update(self) -> None:
        q = (
            "UPDATE portal SET other_user_pk=$3, mxid=$4, name=$5, avatar_url=$6, encrypted=$7,"
            "                  name_set=$8, avatar_set=$9, relay_user_id=$10, first_event_id=$11,"
            "                  next_batch_id=$12, historical_base_insertion_event_id=$13,"
            "                  cursor=$14, thread_image_id=$15 "
            "WHERE thread_id=$1 AND receiver=$2"
        )
        await self.db.execute(q, *self._values)

    @classmethod
    def _from_row(cls, row: Record | None) -> Portal | None:
        if row is None:
            return None
        return cls(**row)

    @classmethod
    async def get_by_mxid(cls, mxid: RoomID) -> Portal | None:
        q = f"SELECT {cls.column_names} FROM portal WHERE mxid=$1"
        row = await cls.db.fetchrow(q, mxid)
        return cls._from_row(row)

    @classmethod
    async def get_by_thread_id(
        cls, thread_id: str, receiver: int, rec_must_match: bool = True
    ) -> Portal | None:
        q = f"SELECT {cls.column_names} FROM portal WHERE thread_id=$1 AND receiver=$2"
        if not rec_must_match:
            q = f"""
                SELECT {cls.column_names}
                FROM portal
                WHERE thread_id=$1
                    AND (receiver=$2 OR receiver=0)
            """
        row = await cls.db.fetchrow(q, thread_id, receiver)
        return cls._from_row(row)

    @classmethod
    async def find_private_chats_of(cls, receiver: int) -> list[Portal]:
        q = f"""
            SELECT {cls.column_names}
            FROM portal
            WHERE receiver=$1
                AND other_user_pk IS NOT NULL
        """
        rows = await cls.db.fetch(q, receiver)
        return [cls._from_row(row) for row in rows]

    @classmethod
    async def find_private_chats_with(cls, other_user: int) -> list[Portal]:
        q = f"""
            SELECT {cls.column_names}
            FROM portal
            WHERE other_user_pk=$1
        """
        rows = await cls.db.fetch(q, other_user)
        return [cls._from_row(row) for row in rows]

    @classmethod
    async def find_private_chat_id(cls, receiver: int, other_user: int) -> str | None:
        q = "SELECT thread_id FROM portal WHERE receiver=$1 AND other_user_pk=$2"
        return await cls.db.fetchval(q, receiver, other_user)

    @classmethod
    async def all_with_room(cls) -> list[Portal]:
        q = f"""
            SELECT {cls.column_names}
            FROM portal
            WHERE mxid IS NOT NULL
        """
        rows = await cls.db.fetch(q)
        return [cls._from_row(row) for row in rows]
