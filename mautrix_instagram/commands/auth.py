# mautrix-instagram - A Matrix-Instagram puppeting bridge.
# Copyright (C) 2023 Tulir Asokan
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

import base64
import hashlib
import hmac
import zlib

from mauigpapi.errors import (
    IGBad2FACodeError,
    IGChallengeError,
    IGChallengeWrongCodeError,
    IGLoginBadPasswordError,
    IGLoginInvalidCredentialsError,
    IGLoginInvalidUserError,
    IGLoginTwoFactorRequiredError,
)
from mauigpapi.http import AndroidAPI
from mauigpapi.proxy import proxy_with_retry
from mauigpapi.state import AndroidState
from mauigpapi.types import BaseResponseUser
from mautrix.bridge.commands import HelpSection, command_handler
from mautrix.types import EventID

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
        api = AndroidAPI(state, log=user.api_log, proxy_handler=user.proxy_handler)
        await proxy_with_retry(
            lambda: api.get_mobile_config(),
            logger=user.log,
            proxy_handler=user.proxy_handler,
            on_proxy_change=user.on_proxy_update,
        )
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
    help_text="Log into Instagram",
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
    await evt.redact()
    api, state = await get_login_state(evt.sender, evt.config["instagram.device_seed"])
    try:
        resp = await api.login(username, password)
    except IGLoginTwoFactorRequiredError as e:
        tfa_info = e.body.two_factor_info
        msg = "Username and password accepted, but you have two-factor authentication enabled.\n"
        if tfa_info.totp_two_factor_on:
            msg += "Send the code from your authenticator app here."
            if tfa_info.sms_two_factor_on:
                msg += f" Alternatively, send `resend-sms` to get an SMS code to •••{tfa_info.obfuscated_phone_number}"
        elif tfa_info.sms_two_factor_on:
            msg += (
                f"Send the code sent to •••{tfa_info.obfuscated_phone_number} here."
                " You can also send `resend-sms` if you didn't receive the code."
            )
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
            "has_sms": tfa_info.sms_two_factor_on,
            "2fa_identifier": tfa_info.two_factor_identifier,
        }
        await evt.reply(msg)
    except IGChallengeError:
        await evt.reply(
            "Login challenges aren't currently supported. "
            "Please set up real two-factor authentication."
        )
        await api.challenge_auto()
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
    except IGLoginInvalidCredentialsError:
        await evt.reply("Incorrect username or password")
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
    has_sms = evt.sender.command_status["has_sms"]
    code = "".join(evt.args).lower()
    if has_sms and code == "resend-sms":
        try:
            resp = await api.send_two_factor_login_sms(username, identifier=identifier)
        except Exception as e:
            evt.log.exception("Failed to re-request SMS code")
            await evt.reply(f"Failed to re-request SMS code: {e}")
        else:
            await evt.reply(
                f"Re-requested SMS code to {resp.two_factor_info.obfuscated_phone_number}"
            )
            evt.sender.command_status[
                "2fa_identifier"
            ] = resp.two_factor_info.two_factor_identifier
            evt.sender.command_status["is_totp"] = False
        return
    try:
        resp = await api.two_factor_login(
            username, code=code, identifier=identifier, is_totp=is_totp
        )
    except IGBad2FACodeError:
        await evt.reply(
            "Invalid 2-factor authentication code. Please try again "
            "or use `$cmdprefix+sp cancel` to cancel."
        )
    except IGChallengeError:
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


@command_handler(
    needs_auth=False,
    management_only=True,
    help_section=SECTION_AUTH,
    help_text="Log into Instagram with a pre-generated session blob",
    help_args="<_blob_>",
)
async def login_blob(evt: CommandEvent) -> EventID:
    if await evt.sender.is_logged_in():
        return await evt.reply("You're already logged in")
    elif len(evt.args) < 1:
        return await evt.reply("**Usage:** `$cmdprefix+sp login-blob <blob>`")
    await evt.redact()
    try:
        state = AndroidState.parse_json(zlib.decompress(base64.b64decode("".join(evt.args))))
    except Exception:
        evt.log.exception(f"{evt.sender} provided an invalid login blob")
        return await evt.reply("Invalid blob")
    evt.sender.state = state
    await evt.reply("Connecting...")
    await evt.sender.try_connect()
    await evt.reply("Maybe connected now, try pinging?")
