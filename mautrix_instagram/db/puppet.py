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
from yarl import URL
import asyncpg

from mautrix.types import ContentURI, SyncToken, UserID
from mautrix.util.async_db import Database

fake_db = Database.create("") if TYPE_CHECKING else None


@dataclass
class Puppet:
    db: ClassVar[Database] = fake_db

    pk: int
    name: str | None
    username: str | None
    photo_id: str | None
    photo_mxc: ContentURI | None
    name_set: bool
    avatar_set: bool

    is_registered: bool

    custom_mxid: UserID | None
    access_token: str | None
    next_batch: SyncToken | None
    base_url: URL | None

    @property
    def _values(self):
        return (
            self.pk,
            self.name,
            self.username,
            self.photo_id,
            self.photo_mxc,
            self.name_set,
            self.avatar_set,
            self.is_registered,
            self.custom_mxid,
            self.access_token,
            self.next_batch,
            str(self.base_url) if self.base_url else None,
        )

    async def insert(self) -> None:
        q = (
            "INSERT INTO puppet (pk, name, username, photo_id, photo_mxc, name_set, avatar_set,"
            "                    is_registered, custom_mxid, access_token, next_batch, base_url) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)"
        )
        await self.db.execute(q, *self._values)

    async def update(self) -> None:
        q = (
            "UPDATE puppet SET name=$2, username=$3, photo_id=$4, photo_mxc=$5, name_set=$6,"
            "                  avatar_set=$7, is_registered=$8, custom_mxid=$9, access_token=$10,"
            "                  next_batch=$11, base_url=$12 "
            "WHERE pk=$1"
        )
        await self.db.execute(q, *self._values)

    @classmethod
    def _from_row(cls, row: asyncpg.Record) -> Puppet:
        data = {**row}
        base_url_str = data.pop("base_url")
        base_url = URL(base_url_str) if base_url_str is not None else None
        return cls(base_url=base_url, **data)

    @classmethod
    async def get_by_pk(cls, pk: int) -> Puppet | None:
        q = (
            "SELECT pk, name, username, photo_id, photo_mxc, name_set, avatar_set, is_registered,"
            "       custom_mxid, access_token, next_batch, base_url "
            "FROM puppet WHERE pk=$1"
        )
        row = await cls.db.fetchrow(q, pk)
        if not row:
            return None
        return cls._from_row(row)

    @classmethod
    async def get_by_custom_mxid(cls, mxid: UserID) -> Puppet | None:
        q = (
            "SELECT pk, name, username, photo_id, photo_mxc, name_set, avatar_set, is_registered,"
            "       custom_mxid, access_token, next_batch, base_url "
            "FROM puppet WHERE custom_mxid=$1"
        )
        row = await cls.db.fetchrow(q, mxid)
        if not row:
            return None
        return cls._from_row(row)

    @classmethod
    async def all_with_custom_mxid(cls) -> list[Puppet]:
        q = (
            "SELECT pk, name, username, photo_id, photo_mxc, name_set, avatar_set, is_registered,"
            "       custom_mxid, access_token, next_batch, base_url "
            "FROM puppet WHERE custom_mxid IS NOT NULL"
        )
        rows = await cls.db.fetch(q)
        return [cls._from_row(row) for row in rows]
