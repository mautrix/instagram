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
from asyncpg import Connection

from mautrix.util.async_db import UpgradeTable

upgrade_table = UpgradeTable()


@upgrade_table.register(description="Latest revision", upgrades_to=8)
async def upgrade_latest(conn: Connection) -> None:
    await conn.execute(
        """CREATE TABLE portal (
            thread_id     TEXT,
            receiver      BIGINT,
            other_user_pk BIGINT,
            mxid          TEXT,
            name          TEXT,
            avatar_url    TEXT,
            name_set      BOOLEAN NOT NULL DEFAULT false,
            avatar_set    BOOLEAN NOT NULL DEFAULT false,
            encrypted     BOOLEAN NOT NULL DEFAULT false,
            relay_user_id TEXT,
            PRIMARY KEY (thread_id, receiver)
        )"""
    )
    await conn.execute(
        """CREATE TABLE "user" (
            mxid           TEXT PRIMARY KEY,
            igpk           BIGINT,
            state          jsonb,
            seq_id         BIGINT,
            snapshot_at_ms BIGINT,
            notice_room    TEXT
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
            mxid     TEXT,
            mx_room  TEXT NOT NULL,
            item_id  TEXT,
            receiver BIGINT,
            sender   BIGINT NOT NULL,

            client_context TEXT,
            ig_timestamp   BIGINT,
            PRIMARY KEY (item_id, receiver),
            UNIQUE (mxid, mx_room)
        )"""
    )
    await conn.execute(
        """CREATE TABLE reaction (
            mxid         TEXT NOT NULL,
            mx_room      TEXT NOT NULL,
            ig_item_id   TEXT,
            ig_receiver  BIGINT,
            ig_sender    BIGINT,
            reaction     TEXT NOT NULL,
            mx_timestamp BIGINT,
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
    await conn.execute("ALTER TABLE message ALTER COLUMN mxid DROP NOT NULL")


@upgrade_table.register(description="Store reaction timestamps")
async def upgrade_v7(conn: Connection) -> None:
    await conn.execute("ALTER TABLE reaction ADD COLUMN mx_timestamp BIGINT")


@upgrade_table.register(description="Store sync sequence ID in user table")
async def upgrade_v8(conn: Connection) -> None:
    await conn.execute('ALTER TABLE "user" ADD COLUMN seq_id BIGINT')
    await conn.execute('ALTER TABLE "user" ADD COLUMN snapshot_at_ms BIGINT')
