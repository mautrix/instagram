# mautrix-instagram - A Matrix-Instagram puppeting bridge.
# Copyright (C) 2022 Tulir Asokan, Sumner Evans
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
from mautrix.util.async_db import Connection

from . import upgrade_table


@upgrade_table.register(description="Add name_set and avatar_set to portal table")
async def upgrade_v2(conn: Connection) -> None:
    await conn.execute("ALTER TABLE portal ADD COLUMN avatar_url TEXT")
    await conn.execute("ALTER TABLE portal ADD COLUMN name_set BOOLEAN NOT NULL DEFAULT false")
    await conn.execute("ALTER TABLE portal ADD COLUMN avatar_set BOOLEAN NOT NULL DEFAULT false")
    await conn.execute("UPDATE portal SET name_set=true WHERE name<>''")
