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
from mauigpapi.errors import IGNotLoggedInError
from mautrix.bridge.commands import HelpSection, command_handler

from .typehint import CommandEvent

SECTION_CONNECTION = HelpSection("Connection management", 15, "")


@command_handler(
    needs_auth=False,
    management_only=True,
    help_section=SECTION_CONNECTION,
    help_text="Mark this room as your bridge notice room",
)
async def set_notice_room(evt: CommandEvent) -> None:
    evt.sender.notice_room = evt.room_id
    await evt.sender.update()
    await evt.reply("This room has been marked as your bridge notice room")


@command_handler(
    needs_auth=False,
    management_only=True,
    help_section=SECTION_CONNECTION,
    help_text="Check if you're logged into Instagram",
)
async def ping(evt: CommandEvent) -> None:
    if not await evt.sender.is_logged_in():
        await evt.reply("You're not logged into Instagram")
        return
    try:
        user_info = await evt.sender.client.current_user()
    except IGNotLoggedInError as e:
        evt.log.exception("Got error checking current user for %s", evt.sender.mxid)
        await evt.reply("You have been logged out")
        await evt.sender.logout(error=e)
    else:
        user = user_info.user
        await evt.reply(
            f"You're logged in as {user.full_name} ([@{user.username}]"
            f"(https://instagram.com/{user.username}), user ID: {user.pk})"
        )
    if evt.sender.is_connected:
        await evt.reply("MQTT connection is active")
    elif evt.sender.mqtt and evt.sender._listen_task:
        await evt.reply("MQTT connection is reconnecting")
    else:
        await evt.reply("MQTT not connected")


@command_handler(
    needs_auth=True,
    management_only=False,
    help_section=SECTION_CONNECTION,
    help_text="Reconnect to Instagram and synchronize portals",
    aliases=["sync"],
)
async def refresh(evt: CommandEvent) -> None:
    await evt.sender.refresh()
    await evt.reply("Synchronization complete")


@command_handler(
    needs_auth=True,
    management_only=False,
    help_section=SECTION_CONNECTION,
    help_text="Connect to Instagram",
    aliases=["reconnect"],
)
async def connect(evt: CommandEvent) -> None:
    if evt.sender.is_connected:
        await evt.reply("You're already connected to Instagram.")
        return
    await evt.sender.refresh(resync=False)
    await evt.reply("Restarted connection to Instagram.")


@command_handler(
    needs_auth=True,
    management_only=False,
    help_section=SECTION_CONNECTION,
    help_text="Disconnect from Instagram",
)
async def disconnect(evt: CommandEvent) -> None:
    if not evt.sender.mqtt:
        await evt.reply("You're not connected to Instagram.")
    await evt.sender.stop_listen()
    await evt.reply("Successfully disconnected from Instagram.")
