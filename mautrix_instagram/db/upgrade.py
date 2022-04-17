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
from mautrix.util.async_db import UpgradeTable, Connection, Scheme
import re

upgrade_table = UpgradeTable()

async def drop_not_null(conn: Connection, table: str, column: str):
    if conn.scheme == Scheme.SQLITE:
        # Adapted from the "simpler procedure" in SQLite docs here:
        # https://www.sqlite.org/lang_altertable.html#otheralter
        # We'd start a transaction, but we're already in one
        schema_version = await conn.fetchval("PRAGMA schema_version")
        table_sql = await conn.fetchval(
            "SELECT sql FROM sqlite_schema WHERE type='table' AND name=$1",
            table
        )
        new_table_sql = re.sub(f'({column}\\s+\\w+) NOT NULL', r'\1', table_sql)
        await conn.execute("PRAGMA writable_schema=ON")
        await conn.execute(
            "UPDATE sqlite_schema SET sql=$1 WHERE type='table' AND name=$2",
            new_table_sql, table
        )
        await conn.execute(f"PRAGMA schema_version={schema_version + 1}")
        await conn.execute("PRAGMA writable_schema=OFF")
        await conn.execute("PRAGMA integrity_check")
    else:
        await conn.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP NOT NULL")


@upgrade_table.register(description="Initial revision")
async def upgrade_v1(conn: Connection) -> None:
    await conn.execute(
        """CREATE TABLE portal (
        thread_id     TEXT,
        receiver      BIGINT,
        other_user_pk BIGINT,
        mxid          TEXT,
        name          TEXT,
        encrypted     BOOLEAN NOT NULL DEFAULT false,
        PRIMARY KEY (thread_id, receiver)
    )"""
    )
    await conn.execute(
        """CREATE TABLE "user" (
        mxid        TEXT PRIMARY KEY,
        igpk        BIGINT,
        state       jsonb,
        notice_room TEXT
    )"""
    )
    await conn.execute(
        """CREATE TABLE puppet (
        pk            BIGINT PRIMARY KEY,
        name          TEXT,
        username      TEXT,
        photo_id      TEXT,
        photo_mxc     TEXT,
        name_set      BOOLEAN NOT NULL DEFAULT false,
        avatar_set    BOOLEAN NOT NULL DEFAULT false,
        is_registered BOOLEAN NOT NULL DEFAULT false,
        custom_mxid   TEXT,
        access_token  TEXT,
        next_batch    TEXT,
        base_url      TEXT
    )"""
    )
    await conn.execute(
        """CREATE TABLE user_portal (
        "user"          BIGINT,
        portal          TEXT,
        portal_receiver BIGINT,
        in_community    BOOLEAN NOT NULL DEFAULT false,
        FOREIGN KEY (portal, portal_receiver) REFERENCES portal(thread_id, receiver)
            ON UPDATE CASCADE ON DELETE CASCADE
    )"""
    )
    await conn.execute(
        """CREATE TABLE message (
        mxid     TEXT NOT NULL,
        mx_room  TEXT NOT NULL,
        item_id  TEXT,
        receiver BIGINT,
        sender   BIGINT NOT NULL,
        PRIMARY KEY (item_id, receiver),
        UNIQUE (mxid, mx_room)
    )"""
    )
    await conn.execute(
        """CREATE TABLE reaction (
        mxid        TEXT NOT NULL,
        mx_room     TEXT NOT NULL,
        ig_item_id  TEXT,
        ig_receiver BIGINT,
        ig_sender   BIGINT,
        reaction    TEXT NOT NULL,
        PRIMARY KEY (ig_item_id, ig_receiver, ig_sender),
        FOREIGN KEY (ig_item_id, ig_receiver) REFERENCES message(item_id, receiver)
            ON DELETE CASCADE ON UPDATE CASCADE,
        UNIQUE (mxid, mx_room)
    )"""
    )


@upgrade_table.register(description="Add name_set and avatar_set to portal table")
async def upgrade_v2(conn: Connection) -> None:
    await conn.execute("ALTER TABLE portal ADD COLUMN avatar_url TEXT")
    await conn.execute("ALTER TABLE portal ADD COLUMN name_set BOOLEAN NOT NULL DEFAULT false")
    await conn.execute("ALTER TABLE portal ADD COLUMN avatar_set BOOLEAN NOT NULL DEFAULT false")
    await conn.execute("UPDATE portal SET name_set=true WHERE name<>''")


@upgrade_table.register(description="Add relay user field to portal table")
async def upgrade_v3(conn: Connection) -> None:
    await conn.execute("ALTER TABLE portal ADD COLUMN relay_user_id TEXT")


@upgrade_table.register(description="Add client context field to message table")
async def upgrade_v4(conn: Connection) -> None:
    await conn.execute("ALTER TABLE message ADD COLUMN client_context TEXT")


@upgrade_table.register(description="Add ig_timestamp field to message table")
async def upgrade_v5(conn: Connection) -> None:
    await conn.execute("ALTER TABLE message ADD COLUMN ig_timestamp BIGINT")


@upgrade_table.register(description="Allow hidden events in message table")
async def upgrade_v6(conn: Connection) -> None:
    await drop_not_null(conn, "message", "mxid")

@upgrade_table.register(description="Store reaction timestamps")
async def upgrade_v7(conn: Connection) -> None:
    await conn.execute("ALTER TABLE reaction ADD COLUMN mx_timestamp BIGINT")


@upgrade_table.register(description="Store sync sequence ID in user table")
async def upgrade_v8(conn: Connection) -> None:
    await conn.execute('ALTER TABLE "user" ADD COLUMN seq_id BIGINT')
    await conn.execute('ALTER TABLE "user" ADD COLUMN snapshot_at_ms BIGINT')
