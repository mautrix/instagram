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
from mautrix.bridge.commands import HelpSection, command_handler

from .. import puppet as pu
from .typehint import CommandEvent

SECTION_MISC = HelpSection("Miscellaneous", 40, "")


@command_handler(
    needs_auth=True,
    management_only=False,
    help_section=SECTION_MISC,
    help_text="Search for Instagram users",
    help_args="<_query_>",
)
async def search(evt: CommandEvent) -> None:
    if len(evt.args) < 1:
        await evt.reply("**Usage:** `$cmdprefix+sp search <query>`")
        return
    resp = await evt.sender.client.search_users(" ".join(evt.args))
    if not resp.users:
        await evt.reply("No results :(")
        return
    response_list = []
    for user in resp.users[:10]:
        puppet = await pu.Puppet.get_by_pk(user.pk, create=True)
        await puppet.update_info(user, evt.sender)
        response_list.append(
            f"* [{puppet.name}](https://matrix.to/#/{puppet.mxid})"
            f" ([@{user.username}](https://instagram.com/{user.username}))"
        )
    await evt.reply("\n".join(response_list))
