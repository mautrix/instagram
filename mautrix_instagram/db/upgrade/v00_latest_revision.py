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
from mautrix.util.async_db import Connection, Scheme

from . import upgrade_table


@upgrade_table.register(description="Latest revision", upgrades_to=10)
async def upgrade_latest(conn: Connection, scheme: Scheme) -> None:
    await conn.execute(
        """CREATE TABLE portal (
            thread_id                           TEXT,
            receiver                            BIGINT,
            other_user_pk                       BIGINT,
            mxid                                TEXT,
            name                                TEXT,
            avatar_url                          TEXT,
            name_set                            BOOLEAN NOT NULL DEFAULT false,
            avatar_set                          BOOLEAN NOT NULL DEFAULT false,
            encrypted                           BOOLEAN NOT NULL DEFAULT false,
            relay_user_id                       TEXT,
            first_event_id                      TEXT,
            next_batch_id                       TEXT,
            historical_base_insertion_event_id  TEXT,
            cursor                              TEXT,
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

    gen = ""
    if scheme in (Scheme.POSTGRES, Scheme.COCKROACH):
        gen = "GENERATED ALWAYS AS IDENTITY"
    await conn.execute(
        f"""
        CREATE TABLE backfill_queue (
            queue_id            INTEGER PRIMARY KEY {gen},
            user_mxid           TEXT,
            priority            INTEGER NOT NULL,
            portal_thread_id    TEXT,
            portal_receiver     BIGINT,
            num_pages           INTEGER NOT NULL,
            page_delay          INTEGER NOT NULL,
            post_batch_delay    INTEGER NOT NULL,
            max_total_pages     INTEGER NOT NULL,
            dispatch_time       TIMESTAMP,
            completed_at        TIMESTAMP,
            cooldown_timeout    TIMESTAMP,

            FOREIGN KEY (user_mxid) REFERENCES "user"(mxid) ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (portal_thread_id, portal_receiver)
                REFERENCES portal(thread_id, receiver) ON DELETE CASCADE
        )
        """
    )
