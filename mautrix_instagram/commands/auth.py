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
from mautrix.bridge.commands import HelpSection, command_handler
from mauigpapi.state import AndroidState
from mauigpapi.http import AndroidAPI
from mauigpapi.errors import (IGLoginTwoFactorRequiredError, IGLoginBadPasswordError,
                              IGLoginInvalidUserError, IGBad2FACodeError)
from mauigpapi.types import BaseResponseUser

from .typehint import CommandEvent

SECTION_AUTH = HelpSection("Authentication", 10, "")


@command_handler(needs_auth=False, management_only=True, help_section=SECTION_AUTH,
                 help_text="Log in to Instagram", help_args="<_username_> <_password_>")
async def login(evt: CommandEvent) -> None:
    if await evt.sender.is_logged_in():
        await evt.reply("You're already logged in")
        return
    elif len(evt.args) < 2:
        await evt.reply("**Usage:** `$cmdprefix+sp login <username> <password>`")
        return
    username = evt.args[0]
    password = " ".join(evt.args[1:])
    if evt.sender.command_status and evt.sender.command_status["action"] == "Login":
        api: AndroidAPI = evt.sender.command_status["api"]
        state: AndroidState = evt.sender.command_status["state"]
    else:
        evt.log.trace(f"Generating new device for {username}")
        state = AndroidState()
        state.device.generate(username)
        api = AndroidAPI(state)
        await api.simulate_pre_login_flow()
        evt.sender.command_status = {
            "action": "Login",
            "room_id": evt.room_id,
            "state": state,
            "api": api,
        }
    try:
        resp = await api.login(username, password)
    except IGLoginTwoFactorRequiredError as e:
        tfa_info = e.body.two_factor_info
        msg = "Username and password accepted, but you have two-factor authentication enabled.\n"
        if tfa_info.totp_two_factor_on:
            msg += "Send the code from your authenticator app here."
        elif tfa_info.sms_two_factor_on:
            msg += f"Send the code sent to {tfa_info.obfuscated_phone_number} here."
        else:
            msg += ("Unfortunately, none of your two-factor authentication methods are currently "
                    "supported by the bridge.")
            return
        evt.sender.command_status = {
            **evt.sender.command_status,
            "next": enter_login_2fa,
            "username": tfa_info.username,
            "is_totp": tfa_info.totp_two_factor_on,
            "2fa_identifier": tfa_info.two_factor_identifier,
        }
        await evt.reply(msg)
    except IGLoginInvalidUserError:
        await evt.reply("Invalid username")
    except IGLoginBadPasswordError:
        await evt.reply("Incorrect password")
    else:
        await _post_login(evt, api, state, resp.logged_in_user)


async def enter_login_2fa(evt: CommandEvent) -> None:
    api: AndroidAPI = evt.sender.command_status["api"]
    state: AndroidState = evt.sender.command_status["state"]
    identifier = evt.sender.command_status["2fa_identifier"]
    username = evt.sender.command_status["username"]
    is_totp = evt.sender.command_status["is_totp"]
    try:
        resp = await api.two_factor_login(username, code="".join(evt.args), identifier=identifier,
                                          is_totp=is_totp)
    except IGBad2FACodeError:
        await evt.reply("Invalid 2-factor authentication code. Please try again "
                        "or use `$cmdprefix+sp cancel` to cancel.")
    except Exception as e:
        await evt.reply(f"Failed to log in: {e}")
        evt.log.exception("Failed to log in")
        evt.sender.command_status = None
    else:
        evt.sender.command_status = None
        await _post_login(evt, api, state, resp.logged_in_user)


async def _post_login(evt: CommandEvent, api: AndroidAPI, state: AndroidState,
                      user: BaseResponseUser) -> None:
    await api.simulate_post_login_flow()
    evt.sender.state = state
    pl = state.device.payload
    manufacturer, model = pl["manufacturer"], pl["model"]
    await evt.reply(f"Successfully logged in as {user.full_name} ([@{user.username}]"
                    f"(https://instagram.com/{user.username}), user ID: {user.pk}).\n\n"
                    f"The bridge will show up on Instagram as {manufacturer} {model}.")
    await evt.sender.try_connect()


@command_handler(needs_auth=True, help_section=SECTION_AUTH, help_text="Disconnect the bridge from"
                                                                       "your Instagram account")
async def logout(evt: CommandEvent) -> None:
    await evt.sender.logout()
    await evt.reply("Successfully logged out")
