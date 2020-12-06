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
from mauigpapi.errors import IGNotLoggedInError
from mautrix.bridge.commands import HelpSection, command_handler
from .typehint import CommandEvent

SECTION_CONNECTION = HelpSection("Connection management", 15, "")


@command_handler(needs_auth=False, management_only=True, help_section=SECTION_CONNECTION,
                 help_text="Mark this room as your bridge notice room")
async def set_notice_room(evt: CommandEvent) -> None:
    evt.sender.notice_room = evt.room_id
    await evt.sender.update()
    await evt.reply("This room has been marked as your bridge notice room")


@command_handler(needs_auth=False, management_only=True, help_section=SECTION_CONNECTION,
                 help_text="Check if you're logged into Instagram")
async def ping(evt: CommandEvent) -> None:
    if not await evt.sender.is_logged_in():
        await evt.reply("You're not logged into Instagram")
        return
    try:
        user_info = await evt.sender.client.current_user()
    except IGNotLoggedInError:
        await evt.reply("You have been logged out")
        await evt.sender.logout()
    else:
        user = user_info.user
        await evt.reply(f"You're logged in as {user.full_name} ([@{user.username}]"
                        f"(https://instagram.com/{user.username}), user ID: {user.pk})")


@command_handler(needs_auth=True, management_only=False, help_section=SECTION_CONNECTION,
                 help_text="Synchronize portals")
async def sync(evt: CommandEvent) -> None:
    await evt.sender.sync()
    await evt.reply("Synchronization complete")


# TODO connect/disconnect MQTT commands
