# mautrix-twitter - A Matrix-Twitter DM puppeting bridge
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
from mautrix.types import EventID
from mauigpapi.errors import IGNotLoggedInError
from mautrix.bridge.commands import HelpSection, command_handler
from .typehint import CommandEvent

SECTION_CONNECTION = HelpSection("Connection management", 15, "")


@command_handler(needs_auth=False, management_only=True, help_section=SECTION_CONNECTION,
                 help_text="Mark this room as your bridge notice room.")
async def set_notice_room(evt: CommandEvent) -> None:
    evt.sender.notice_room = evt.room_id
    await evt.sender.update()
    await evt.reply("This room has been marked as your bridge notice room")

@command_handler(needs_auth=True, management_only=False, help_section=SECTION_CONNECTION,
                 help_text="Relay messages in this room through your Instagram account.")
async def set_relay(evt: CommandEvent) -> EventID:
    if not evt.config["bridge.relay.enabled"]:
        return await evt.reply("Relay mode is not enable in this instance of the bridge.")
    elif not evt.is_portal:
        return await evt.reply("This is not a portal room.")
    await evt.portal.set_relay_user(evt.sender)
    return await evt.reply("Messages from non-logged-in users in this room will now be bridged "
                           "through your Instagram account.")

@command_handler(needs_auth=True, management_only=False, help_section=SECTION_CONNECTION,
                 help_text="Stop relaying messages in this room.")
async def unset_relay(evt: CommandEvent) -> EventID:
    if not evt.config["bridge.relay.enabled"]:
        return await evt.reply("Relay mode is not enable in this instance of the bridge.")
    elif not evt.is_portal:
        return await evt.reply("This is not a portal room.")
    elif not evt.portal.has_relay:
        return await evt.reply("This room does not have a relay user set.")
    await evt.portal.set_relay_user(None)
    return await evt.reply("Messages from non-logged-in users will no longer be bridged.")

@command_handler(needs_auth=False, management_only=True, help_section=SECTION_CONNECTION,
                 help_text="Check if you're logged into Instagram")
async def ping(evt: CommandEvent) -> None:
    if not await evt.sender.is_logged_in():
        await evt.reply("You're not logged into Instagram")
        return
    try:
        user_info = await evt.sender.client.current_user()
    except IGNotLoggedInError as e:
        # TODO maybe don't always log out?
        evt.log.exception(f"Got error checking current user for %s, logging out. %s",
                          evt.sender.mxid, e.body.json())
        await evt.reply("You have been logged out")
        await evt.sender.logout()
    else:
        user = user_info.user
        await evt.reply(f"You're logged in as {user.full_name} ([@{user.username}]"
                        f"(https://instagram.com/{user.username}), user ID: {user.pk})")
    if evt.sender.is_connected:
        await evt.reply("MQTT connection is active")
    elif evt.sender.mqtt and evt.sender._listen_task:
        await evt.reply("MQTT connection is reconnecting")
    else:
        await evt.reply("MQTT not connected")


@command_handler(needs_auth=True, management_only=False, help_section=SECTION_CONNECTION,
                 help_text="Reconnect to Instagram and synchronize portals", aliases=["sync"])
async def refresh(evt: CommandEvent) -> None:
    await evt.sender.refresh()
    await evt.reply("Synchronization complete")


@command_handler(needs_auth=True, management_only=False, help_section=SECTION_CONNECTION,
                 help_text="Connect to Instagram", aliases=["reconnect"])
async def connect(evt: CommandEvent) -> None:
    if evt.sender.is_connected:
        await evt.reply("You're already connected to Instagram.")
        return
    await evt.sender.refresh(resync=False)
    await evt.reply("Restarted connection to Instagram.")


@command_handler(needs_auth=True, management_only=False, help_section=SECTION_CONNECTION,
                 help_text="Disconnect from Instagram")
async def disconnect(evt: CommandEvent) -> None:
    if not evt.sender.mqtt:
        await evt.reply("You're not connected to Instagram.")
    await evt.sender.stop_listen()
    await evt.reply("Successfully disconnected from Instagram.")
