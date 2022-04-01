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

import hashlib
import hmac

from mauigpapi.errors import (
    IGBad2FACodeError,
    IGChallengeWrongCodeError,
    IGCheckpointError,
    IGLoginBadPasswordError,
    IGLoginInvalidUserError,
    IGLoginTwoFactorRequiredError,
)
from mauigpapi.http import AndroidAPI
from mauigpapi.state import AndroidState
from mauigpapi.types import BaseResponseUser
from mautrix.bridge.commands import HelpSection, command_handler

from .. import user as u
from .typehint import CommandEvent

SECTION_AUTH = HelpSection("Authentication", 10, "")


async def get_login_state(user: u.User, seed: str) -> tuple[AndroidAPI, AndroidState]:
    if user.command_status and user.command_status["action"] == "Login":
        api: AndroidAPI = user.command_status["api"]
        state: AndroidState = user.command_status["state"]
    else:
        state = AndroidState()
        seed = hmac.new(seed.encode("utf-8"), user.mxid.encode("utf-8"), hashlib.sha256).digest()
        state.device.generate(seed)
        api = AndroidAPI(state, log=user.api_log)
        await api.qe_sync_login_experiments()
        user.command_status = {
            "action": "Login",
            "state": state,
            "api": api,
        }
    return api, state


@command_handler(
    needs_auth=False,
    management_only=True,
    help_section=SECTION_AUTH,
    help_text="Log in to Instagram",
    help_args="<_username_> <_password_>",
)
async def login(evt: CommandEvent) -> None:
    if await evt.sender.is_logged_in():
        await evt.reply("You're already logged in")
        return
    elif len(evt.args) < 2:
        await evt.reply("**Usage:** `$cmdprefix+sp login <username> <password>`")
        return
    username = evt.args[0]
    password = " ".join(evt.args[1:])
    api, state = await get_login_state(evt.sender, evt.config["instagram.device_seed"])
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
            msg += (
                "Unfortunately, none of your two-factor authentication methods are currently "
                "supported by the bridge."
            )
            return
        evt.sender.command_status = {
            **evt.sender.command_status,
            "next": enter_login_2fa,
            "username": tfa_info.username,
            "is_totp": tfa_info.totp_two_factor_on,
            "2fa_identifier": tfa_info.two_factor_identifier,
        }
        await evt.reply(msg)
    except IGCheckpointError:
        await api.challenge_auto(reset=True)
        evt.sender.command_status = {
            **evt.sender.command_status,
            "next": enter_login_security_code,
        }
        await evt.reply(
            "Username and password accepted, but Instagram wants to verify it's really"
            " you. Please confirm the login and enter the security code here."
        )
    except IGLoginInvalidUserError:
        await evt.reply("Invalid username")
    except IGLoginBadPasswordError:
        await evt.reply("Incorrect password")
    except Exception as e:
        evt.log.exception("Failed to log in")
        await evt.reply(f"Failed to log in: {e}")
    else:
        await _post_login(evt, state, resp.logged_in_user)


async def enter_login_2fa(evt: CommandEvent) -> None:
    api: AndroidAPI = evt.sender.command_status["api"]
    state: AndroidState = evt.sender.command_status["state"]
    identifier = evt.sender.command_status["2fa_identifier"]
    username = evt.sender.command_status["username"]
    is_totp = evt.sender.command_status["is_totp"]
    try:
        resp = await api.two_factor_login(
            username, code="".join(evt.args), identifier=identifier, is_totp=is_totp
        )
    except IGBad2FACodeError:
        await evt.reply(
            "Invalid 2-factor authentication code. Please try again "
            "or use `$cmdprefix+sp cancel` to cancel."
        )
    except IGCheckpointError:
        await api.challenge_auto(reset=True)
        evt.sender.command_status = {
            **evt.sender.command_status,
            "next": enter_login_security_code,
        }
        await evt.reply(
            "2-factor authentication code accepted, but Instagram wants to verify it's"
            " really you. Please confirm the login and enter the security code here."
        )
    except Exception as e:
        evt.log.exception("Failed to log in")
        await evt.reply(f"Failed to log in: {e}")
        evt.sender.command_status = None
    else:
        evt.sender.command_status = None
        await _post_login(evt, state, resp.logged_in_user)


async def enter_login_security_code(evt: CommandEvent) -> None:
    api: AndroidAPI = evt.sender.command_status["api"]
    state: AndroidState = evt.sender.command_status["state"]
    try:
        resp = await api.challenge_send_security_code("".join(evt.args))
    except IGChallengeWrongCodeError as e:
        await evt.reply(f"Incorrect security code: {e}")
    except Exception as e:
        evt.log.exception("Failed to log in")
        await evt.reply(f"Failed to log in: {e}")
        evt.sender.command_status = None
    else:
        if not resp.logged_in_user:
            evt.log.error(
                f"Didn't get logged_in_user in challenge response "
                f"after entering security code: {resp.serialize()}"
            )
            await evt.reply("An unknown error occurred. Please check the bridge logs.")
            return
        evt.sender.command_status = None
        await _post_login(evt, state, resp.logged_in_user)


async def _post_login(evt: CommandEvent, state: AndroidState, user: BaseResponseUser) -> None:
    evt.sender.state = state
    pl = state.device.payload
    manufacturer, model = pl["manufacturer"], pl["model"]
    await evt.reply(
        f"Successfully logged in as {user.full_name} ([@{user.username}]"
        f"(https://instagram.com/{user.username}), user ID: {user.pk}).\n\n"
        f"The bridge will show up on Instagram as {manufacturer} {model}."
    )
    await evt.sender.try_connect()


@command_handler(
    needs_auth=True,
    help_section=SECTION_AUTH,
    help_text="Disconnect the bridge from your Instagram account",
)
async def logout(evt: CommandEvent) -> None:
    await evt.sender.logout()
    await evt.reply("Successfully logged out")
