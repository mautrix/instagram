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

from typing import Any, Type, TypeVar
import json
import logging
import random
import time

from aiohttp import ClientResponse, ClientSession
from yarl import URL

from mautrix.types import JSON, Serializable
from mautrix.util.logging import TraceLogger

from ..errors import (
    IGActionSpamError,
    IGBad2FACodeError,
    IGCheckpointError,
    IGConsentRequiredError,
    IGFBNoContactPointFoundError,
    IGInactiveUserError,
    IGLoginBadPasswordError,
    IGLoginInvalidUserError,
    IGLoginRequiredError,
    IGLoginTwoFactorRequiredError,
    IGNotFoundError,
    IGPrivateUserError,
    IGRateLimitError,
    IGResponseError,
    IGSentryBlockError,
    IGUserHasLoggedOutError,
)
from ..state import AndroidState

T = TypeVar("T")


def remove_nulls(d: dict) -> dict:
    return {
        k: remove_nulls(v) if isinstance(v, dict) else v for k, v in d.items() if v is not None
    }


class BaseAndroidAPI:
    url = URL("https://i.instagram.com")
    http: ClientSession
    state: AndroidState
    log: TraceLogger

    def __init__(self, state: AndroidState, log: TraceLogger | None = None) -> None:
        self.http = ClientSession(cookie_jar=state.cookies.jar)
        self.state = state
        self.log = log or logging.getLogger("mauigpapi.http")

    @staticmethod
    def sign(req: Any, filter_nulls: bool = False) -> dict[str, str]:
        if isinstance(req, Serializable):
            req = req.serialize()
        if isinstance(req, dict):
            req = json.dumps(remove_nulls(req) if filter_nulls else req)
        return {"signed_body": f"SIGNATURE.{req}"}

    @property
    def _headers(self) -> dict[str, str]:
        headers = {
            "x-ads-opt-out": str(int(self.state.session.ads_opt_out)),
            "x-device-id": self.state.device.uuid,
            "x-ig-app-locale": self.state.device.language,
            "x-ig-device-locale": self.state.device.language,
            "x-pigeon-session-id": self.state.pigeon_session_id,
            "x-pigeon-rawclienttime": str(round(time.time(), 3)),
            "x-ig-connection-speed": f"{random.randint(1000, 3700)}kbps",
            "x-ig-bandwidth-speed-kbps": "-1.000",
            "x-ig-bandwidth-totalbytes-b": "0",
            "x-ig-bandwidth-totaltime-ms": "0",
            "x-ig-eu-dc-enabled": (
                str(self.state.session.eu_dc_enabled).lower()
                if self.state.session.eu_dc_enabled is not None
                else None
            ),
            "x-ig-app-startup-country": self.state.device.language.split("_")[1],
            "x-bloks-version-id": self.state.application.BLOKS_VERSION_ID,
            "x-ig-www-claim": self.state.session.ig_www_claim or "0",
            "x-bloks-is-layout-rtl": str(self.state.device.is_layout_rtl).lower(),
            "x-bloks-is-panorama-enabled": "true",
            "x-ig-device-id": self.state.device.uuid,
            "x-ig-android-id": self.state.device.id,
            "x-ig-connection-type": self.state.device.connection_type,
            "x-ig-capabilities": self.state.application.CAPABILITIES,
            "x-ig-app-id": self.state.application.FACEBOOK_ANALYTICS_APPLICATION_ID,
            "user-agent": self.state.user_agent,
            "accept-language": self.state.device.language.replace("_", "-"),
            "authorization": self.state.session.authorization,
            "x-mid": self.state.cookies.get_value("mid"),
            "ig-u-ig-direct-region-hint": self.state.session.region_hint,
            "ig-u-shbid": self.state.session.shbid,
            "ig-u-shbts": self.state.session.shbts,
            "ig-u-ds-user-id": self.state.session.ds_user_id,
            "ig-u-rur": self.state.session.rur,
            "x-fb-http-engine": "Liger",
            "x-fb-client-ip": "True",
            "accept-encoding": "gzip",
        }
        return {k: v for k, v in headers.items() if v is not None}

    def raw_http_get(self, url: URL | str):
        if isinstance(url, str):
            url = URL(url, encoded=True)
        return self.http.get(
            url,
            headers={
                "user-agent": self.state.user_agent,
                "accept-language": self.state.device.language.replace("_", "-"),
            },
        )

    async def std_http_post(
        self,
        path: str,
        data: JSON = None,
        raw: bool = False,
        filter_nulls: bool = False,
        headers: dict[str, str] | None = None,
        query: dict[str, str] | None = None,
        response_type: Type[T] | None = JSON,
    ) -> T:
        headers = {**self._headers, **headers} if headers else self._headers
        if not raw:
            data = self.sign(data, filter_nulls=filter_nulls)
        url = self.url.with_path(path).with_query(query or {})
        resp = await self.http.post(url=url, headers=headers, data=data)
        self.log.trace(f"{path} response: {await resp.text()}")
        if response_type is str or response_type is None:
            self._handle_response_headers(resp)
            if response_type is str:
                return await resp.text()
            return None
        json_data = await self._handle_response(resp)
        if response_type is not JSON:
            return response_type.deserialize(json_data)
        return json_data

    async def std_http_get(
        self,
        path: str,
        query: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        response_type: Type[T] | None = JSON,
    ) -> T:
        headers = {**self._headers, **headers} if headers else self._headers
        query = {k: v for k, v in (query or {}).items() if v is not None}
        resp = await self.http.get(url=self.url.with_path(path).with_query(query), headers=headers)
        self.log.trace(f"{path} response: {await resp.text()}")
        if response_type is None:
            self._handle_response_headers(resp)
            return None
        json_data = await self._handle_response(resp)
        if response_type is not JSON:
            return response_type.deserialize(json_data)
        return json_data

    async def _handle_response(self, resp: ClientResponse) -> JSON:
        self._handle_response_headers(resp)
        body = await resp.json()
        if body.get("status", "fail") == "ok":
            return body
        else:
            await self._raise_response_error(resp)

    async def _raise_response_error(self, resp: ClientResponse) -> None:
        try:
            data = await resp.json()
        except json.JSONDecodeError:
            data = {}

        if data.get("spam", False):
            raise IGActionSpamError(resp, data)
        elif data.get("two_factor_required", False):
            raise IGLoginTwoFactorRequiredError(resp, data)
        elif resp.status == 404:
            raise IGNotFoundError(resp, data)
        elif resp.status == 429:
            raise IGRateLimitError(resp, data)

        message = data.get("message")
        if isinstance(message, str):
            if message == "challenge_required":
                err = IGCheckpointError(resp, data)
                self.state.challenge_path = err.url
                raise err
            elif message == "consent_required":
                raise IGConsentRequiredError(resp, data)
            elif message == "user_has_logged_out":
                raise IGUserHasLoggedOutError(resp, data)
            elif message == "login_required":
                raise IGLoginRequiredError(resp, data)
            elif message.lower() == "not authorized to view user":
                raise IGPrivateUserError(resp, data)

        error_type = data.get("error_type")
        if error_type == "sentry_block":
            raise IGSentryBlockError(resp, data)
        elif error_type == "inactive_user":
            raise IGInactiveUserError(resp, data)
        elif error_type == "bad_password":
            raise IGLoginBadPasswordError(resp, data)
        elif error_type == "invalid_user":
            raise IGLoginInvalidUserError(resp, data)
        elif error_type == "sms_code_validation_code_invalid":
            raise IGBad2FACodeError(resp, data)
        elif error_type == "fb_no_contact_point_found":
            raise IGFBNoContactPointFoundError(resp, data)

        raise IGResponseError(resp, data)

    def _handle_response_headers(self, resp: ClientResponse) -> None:
        fields = {
            "x-ig-set-www-claim": "ig_www_claim",
            "ig-set-authorization": "authorization",
            "ig-set-password-encryption-key-id": "password_encryption_key_id",
            "ig-set-password-encryption-pub-key": "password_encryption_pubkey",
            "ig-set-ig-u-ig-direct-region-hint": "region_hint",
            "ig-set-ig-u-shbid": "shbid",
            "ig-set-ig-u-shbts": "shbts",
            "ig-set-ig-u-rur": "rur",
            "ig-set-ig-u-ds-user-id": "ds_user_id",
        }
        for header, field in fields.items():
            value = resp.headers.get(header)
            if value and (header != "IG-Set-Authorization" or not value.endswith(":")):
                setattr(self.state.session, field, value)
