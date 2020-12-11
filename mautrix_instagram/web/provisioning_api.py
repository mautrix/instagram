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
from typing import Awaitable, Dict, Tuple
import logging
import asyncio
import json

from aiohttp import web

from mauigpapi import AndroidState, AndroidAPI
from mauigpapi.types import BaseResponseUser
from mauigpapi.errors import (IGLoginTwoFactorRequiredError, IGLoginBadPasswordError,
                              IGLoginInvalidUserError, IGBad2FACodeError, IGNotLoggedInError,
                              IGCheckpointError, IGChallengeWrongCodeError)
from mautrix.types import UserID, JSON
from mautrix.util.logging import TraceLogger

from ..commands.auth import get_login_state
from .. import user as u


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
        self.app.router.add_options("/api/logout", self.login_options)
        self.app.router.add_post("/api/login", self.login)
        self.app.router.add_post("/api/login/2fa", self.login_2fa)
        self.app.router.add_post("/api/logout", self.logout)

    @property
    def _acao_headers(self) -> Dict[str, str]:
        return {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization, Content-Type",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
        }

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            **self._acao_headers,
            "Content-Type": "application/json",
        }

    async def login_options(self, _: web.Request) -> web.Response:
        return web.Response(status=200, headers=self._headers)

    def check_token(self, request: web.Request) -> Awaitable['u.User']:
        try:
            token = request.headers["Authorization"]
            token = token[len("Bearer "):]
        except KeyError:
            raise web.HTTPBadRequest(text='{"error": "Missing Authorization header"}',
                                     headers=self._headers)
        except IndexError:
            raise web.HTTPBadRequest(text='{"error": "Malformed Authorization header"}',
                                     headers=self._headers)
        if token != self.shared_secret:
            raise web.HTTPForbidden(text='{"error": "Invalid token"}', headers=self._headers)
        try:
            user_id = request.query["user_id"]
        except KeyError:
            raise web.HTTPBadRequest(text='{"error": "Missing user_id query param"}',
                                     headers=self._headers)

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
                self.log.exception(f"Got error checking current user for %s, logging out. %s",
                                   user.mxid, e.body.json())
                await user.logout()
            else:
                data["instagram"] = resp.user.serialize()
                pl = user.state.device.payload
                manufacturer, model = pl["manufacturer"], pl["model"]
                data["instagram"]["device_displayname"] = f"{manufacturer} {model}"
        return web.json_response(data, headers=self._acao_headers)

    async def login(self, request: web.Request) -> web.Response:
        user, data = await self._get_user(request, check_state=False)

        try:
            username = data["username"]
            password = data["password"]
        except KeyError:
            raise web.HTTPBadRequest(text='{"error": "Missing keys"}', headers=self._headers)

        api, state = await get_login_state(user, username, self.device_seed)
        try:
            resp = await api.login(username, password)
        except IGLoginTwoFactorRequiredError as e:
            return web.json_response(data={
                "status": "two-factor",
                "response": e.body.serialize(),
            }, status=202, headers=self._acao_headers)
        except IGCheckpointError as e:
            await api.challenge_auto(reset=True)
            return web.json_response(data={
                "status": "checkpoint",
                "response": e.body.serialize(),
            }, status=202, headers=self._acao_headers)
        except IGLoginInvalidUserError:
            return web.json_response(data={"status": "invalid-username"},
                                     status=404, headers=self._acao_headers)
        except IGLoginBadPasswordError:
            return web.json_response(data={"status": "incorrect-password"},
                                     status=403, headers=self._acao_headers)
        return await self._finish_login(user, state, resp.logged_in_user)

    async def _get_user(self, request: web.Request, check_state: bool = False
                        ) -> Tuple['u.User', JSON]:
        user = await self.check_token(request)
        if check_state and (not user.command_status or user.command_status["action"] != "Login"):
            raise web.HTTPNotFound(text='{"error": "No 2-factor login in progress}',
                                   headers=self._headers)

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
        except KeyError:
            raise web.HTTPBadRequest(text='{"error": "Missing keys"}', headers=self._headers)

        api: AndroidAPI = user.command_status["api"]
        state: AndroidState = user.command_status["state"]
        try:
            resp = await api.two_factor_login(username, code=code, identifier=identifier,
                                              is_totp=is_totp)
        except IGBad2FACodeError:
            return web.json_response(data={
                "status": "incorrect-2fa-code",
            }, status=403, headers=self._acao_headers)
        except IGCheckpointError as e:
            await api.challenge_auto(reset=True)
            return web.json_response(data={
                "status": "checkpoint",
                "response": e.body.serialize(),
            }, status=202, headers=self._acao_headers)
        return await self._finish_login(user, state, resp.logged_in_user)

    async def login_checkpoint(self, request: web.Request) -> web.Response:
        user, data = await self._get_user(request, check_state=True)

        try:
            code = data["code"]
        except KeyError:
            raise web.HTTPBadRequest(text='{"error": "Missing keys"}', headers=self._headers)

        api: AndroidAPI = user.command_status["api"]
        state: AndroidState = user.command_status["state"]
        try:
            resp = await api.challenge_send_security_code(code=code)
        except IGChallengeWrongCodeError:
            return web.json_response(data={
                "status": "incorrect-challenge-code",
            }, status=403, headers=self._acao_headers)
        return await self._finish_login(user, state, resp.logged_in_user)

    async def _finish_login(self, user: 'u.User', state: AndroidState, resp_user: BaseResponseUser
                            ) -> web.Response:
        user.state = state
        pl = state.device.payload
        manufacturer, model = pl["manufacturer"], pl["model"]
        asyncio.create_task(user.try_connect())
        return web.json_response(data={
            "status": "logged-in",
            "device_displayname": f"{manufacturer} {model}",
            "user": resp_user.serialize(),
        }, status=200, headers=self._acao_headers)

    async def logout(self, request: web.Request) -> web.Response:
        user = await self.check_token(request)
        await user.logout()
        return web.json_response({}, headers=self._acao_headers)
