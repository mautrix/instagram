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
from __future__ import annotations

from typing import Awaitable
import json
import logging

from aiohttp import web

from mauigpapi import AndroidAPI, AndroidState
from mauigpapi.errors import (
    IGBad2FACodeError,
    IGChallengeWrongCodeError,
    IGCheckpointError,
    IGLoginBadPasswordError,
    IGLoginInvalidUserError,
    IGLoginTwoFactorRequiredError,
    IGNotLoggedInError,
)
from mauigpapi.types import ChallengeStateResponse, LoginResponse, LoginResponseUser
from mautrix.types import JSON, UserID
from mautrix.util.logging import TraceLogger

from .. import user as u
from ..commands.auth import get_login_state


class ProvisioningAPI:
    log: TraceLogger = logging.getLogger("mau.web.provisioning")
    app: web.Application

    def __init__(self, shared_secret: str, device_seed: str) -> None:
        self.app = web.Application()
        self.shared_secret = shared_secret
        self.device_seed = device_seed
        self.app.router.add_get("/api/whoami", self.status)
        self.app.router.add_options("/api/login", self.login_options)
        self.app.router.add_options("/api/login/2fa", self.login_options)
        self.app.router.add_options("/api/login/checkpoint", self.login_options)
        self.app.router.add_options("/api/logout", self.login_options)
        self.app.router.add_post("/api/login", self.login)
        self.app.router.add_post("/api/login/2fa", self.login_2fa)
        self.app.router.add_post("/api/login/checkpoint", self.login_checkpoint)
        self.app.router.add_post("/api/logout", self.logout)

    @property
    def _acao_headers(self) -> dict[str, str]:
        return {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization, Content-Type",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
        }

    @property
    def _headers(self) -> dict[str, str]:
        return {
            **self._acao_headers,
            "Content-Type": "application/json",
        }

    def _missing_key_error(self, err: KeyError) -> None:
        raise web.HTTPBadRequest(
            text=json.dumps({"error": f"Missing key {err}"}), headers=self._headers
        )

    async def login_options(self, _: web.Request) -> web.Response:
        return web.Response(status=200, headers=self._headers)

    def check_token(self, request: web.Request) -> Awaitable[u.User]:
        try:
            token = request.headers["Authorization"]
            token = token[len("Bearer ") :]
        except KeyError:
            raise web.HTTPBadRequest(
                text='{"error": "Missing Authorization header"}', headers=self._headers
            )
        except IndexError:
            raise web.HTTPBadRequest(
                text='{"error": "Malformed Authorization header"}', headers=self._headers
            )
        if token != self.shared_secret:
            raise web.HTTPForbidden(text='{"error": "Invalid token"}', headers=self._headers)
        try:
            user_id = request.query["user_id"]
        except KeyError:
            raise web.HTTPBadRequest(
                text='{"error": "Missing user_id query param"}', headers=self._headers
            )

        return u.User.get_by_mxid(UserID(user_id))

    async def status(self, request: web.Request) -> web.Response:
        user = await self.check_token(request)
        data = {
            "permissions": user.permission_level,
            "mxid": user.mxid,
            "instagram": None,
        }
        if await user.is_logged_in():
            try:
                resp = await user.client.current_user()
            except IGNotLoggedInError as e:
                # TODO maybe don't always log out?
                self.log.exception(
                    f"Got error checking current user for %s, logging out. %s",
                    user.mxid,
                    e.body.json(),
                )
                await user.send_bridge_notice(
                    f"You have been logged out of Instagram: {e!s}",
                    important=True,
                    error_code="ig-auth-error",
                    error_message=str(e),
                )
                await user.logout(from_error=True)
            else:
                data["instagram"] = resp.user.serialize()
                pl = user.state.device.payload
                manufacturer, model = pl["manufacturer"], pl["model"]
                data["instagram"]["device_displayname"] = f"{manufacturer} {model}"
                data["instagram"]["mqtt_is_connected"] = user.is_connected
        return web.json_response(data, headers=self._acao_headers)

    async def login(self, request: web.Request) -> web.Response:
        user, data = await self._get_user(request, check_state=False)

        try:
            username = data["username"]
            password = data["password"]
        except KeyError as e:
            raise self._missing_key_error(e)

        self.log.debug("%s is attempting to log in as %s", user.mxid, username)
        api, state = await get_login_state(user, username, self.device_seed)
        try:
            resp = await api.login(username, password)
        except IGLoginTwoFactorRequiredError as e:
            self.log.debug("%s logged in as %s, but needs 2-factor auth", user.mxid, username)
            return web.json_response(
                data={
                    "status": "two-factor",
                    "response": e.body.serialize(),
                },
                status=202,
                headers=self._acao_headers,
            )
        except IGCheckpointError as e:
            self.log.debug("%s logged in as %s, but got a checkpoint", user.mxid, username)
            return await self.start_checkpoint(user, api, e)
        except IGLoginInvalidUserError:
            self.log.debug("%s tried to log in as non-existent user %s", user.mxid, username)
            return web.json_response(
                data={"error": "Invalid username", "status": "invalid-username"},
                status=404,
                headers=self._acao_headers,
            )
        except IGLoginBadPasswordError:
            self.log.debug("%s tried to log in as %s with the wrong password", user.mxid, username)
            return web.json_response(
                data={"error": "Incorrect password", "status": "incorrect-password"},
                status=403,
                headers=self._acao_headers,
            )
        return await self._finish_login(user, state, api, login_resp=resp, after="password")

    async def _get_user(
        self, request: web.Request, check_state: bool = False
    ) -> tuple[u.User, JSON]:
        user = await self.check_token(request)
        if check_state and (not user.command_status or user.command_status["action"] != "Login"):
            raise web.HTTPNotFound(
                text='{"error": "No 2-factor login in progress"}', headers=self._headers
            )

        try:
            data = await request.json()
        except json.JSONDecodeError:
            raise web.HTTPBadRequest(text='{"error": "Malformed JSON"}', headers=self._headers)
        return user, data

    async def login_2fa(self, request: web.Request) -> web.Response:
        user, data = await self._get_user(request, check_state=True)

        try:
            username = data["username"]
            code = data["code"]
            identifier = data["2fa_identifier"]
            is_totp = data["is_totp"]
        except KeyError as e:
            raise self._missing_key_error(e)

        api: AndroidAPI = user.command_status["api"]
        state: AndroidState = user.command_status["state"]
        try:
            resp = await api.two_factor_login(
                username, code=code, identifier=identifier, is_totp=is_totp
            )
        except IGBad2FACodeError:
            self.log.debug("%s submitted an incorrect 2-factor auth code", user.mxid)
            return web.json_response(
                data={
                    "error": "Incorrect 2-factor authentication code",
                    "status": "incorrect-2fa-code",
                },
                status=403,
                headers=self._acao_headers,
            )
        except IGCheckpointError as e:
            self.log.debug("%s submitted a 2-factor auth code, but got a checkpoint", user.mxid)
            return await self.start_checkpoint(user, api, e)
        return await self._finish_login(user, state, api, login_resp=resp, after="2-factor auth")

    async def start_checkpoint(
        self, user: u.User, api: AndroidAPI, err: IGCheckpointError
    ) -> web.Response:
        try:
            resp = await api.challenge_auto(reset=True)
        except Exception as e:
            # Most likely means that the user has to go and verify the login on their phone.
            # Return a 403 in this case so the client knows to show such verbiage.
            self.log.exception("Challenge reset failed for %s", user.mxid)
            return web.json_response(
                data={"status": "checkpoint", "response": e},
                status=403,
                headers=self._acao_headers,
            )
        challenge_data = resp.serialize()
        liu: LoginResponseUser = challenge_data.pop("logged_in_user", None)
        self.log.debug(
            "Challenge state for %s after auto handling: %s (logged in user: %s)",
            user.mxid,
            challenge_data,
            f"{liu.pk}/{liu.username}" if liu else "null",
        )
        return web.json_response(
            data={
                "status": "checkpoint",
                "response": err.body.serialize(),
            },
            status=202,
            headers=self._acao_headers,
        )

    async def login_checkpoint(self, request: web.Request) -> web.Response:
        user, data = await self._get_user(request, check_state=True)

        try:
            code = data["code"]
        except KeyError as e:
            raise self._missing_key_error(e)

        api: AndroidAPI = user.command_status["api"]
        state: AndroidState = user.command_status["state"]
        try:
            resp = await api.challenge_send_security_code(code=code)
        except IGChallengeWrongCodeError:
            self.log.debug("%s submitted an incorrect checkpoint challenge code", user.mxid)
            return web.json_response(
                data={
                    "error": "Incorrect challenge code",
                    "status": "incorrect-challenge-code",
                },
                status=403,
                headers=self._acao_headers,
            )
        challenge_data = resp.serialize()
        liu: LoginResponseUser = challenge_data.pop("logged_in_user", None)
        self.log.debug(
            "Challenge state for %s after sending security code: %s (logged in user: %s)",
            user.mxid,
            challenge_data,
            f"{liu.pk}/{liu.username}" if liu else "null",
        )
        return await self._finish_login(user, state, api, login_resp=resp, after="checkpoint")

    async def _finish_login(
        self,
        user: u.User,
        state: AndroidState,
        api: AndroidAPI,
        login_resp: LoginResponse | ChallengeStateResponse,
        after: str,
    ) -> web.Response:
        self.log.debug(
            "%s finished login after %s, trying to connect "
            "(login response status: %s, logged in user ID: %s)",
            user.mxid,
            after,
            login_resp.status,
            login_resp.logged_in_user.pk if login_resp.logged_in_user else None,
        )
        user.state = state
        pl = state.device.payload
        manufacturer, model = pl["manufacturer"], pl["model"]
        try:
            resp = await api.current_user()
        except IGCheckpointError as e:
            if isinstance(login_resp, ChallengeStateResponse):
                self.log.debug(
                    "%s got a checkpoint after a login that looked successful, "
                    "failing login because we already did some checkpointing",
                    user.mxid,
                )
                # TODO this should probably return a proper error
                # and there might be some cases that can still be handled
                raise
            self.log.debug("%s got a checkpoint after a login that looked successful", user.mxid)
            return await self.start_checkpoint(user, api, e)
        await user.connect()
        return web.json_response(
            data={
                "status": "logged-in",
                "device_displayname": f"{manufacturer} {model}",
                "user": resp.user.serialize() if resp and resp.user else None,
            },
            status=200,
            headers=self._acao_headers,
        )

    async def logout(self, request: web.Request) -> web.Response:
        user = await self.check_token(request)
        await user.logout()
        return web.json_response({}, headers=self._acao_headers)
