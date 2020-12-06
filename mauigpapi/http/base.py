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
from typing import Optional, Dict, Any, TypeVar, Type
import random
import time
import json

from aiohttp import ClientSession, ClientResponse
from yarl import URL
from mautrix.types import JSON, Serializable

from ..state import AndroidState
from ..errors import (IGActionSpamError, IGNotFoundError, IGRateLimitError, IGCheckpointError,
                      IGUserHasLoggedOutError, IGLoginRequiredError, IGPrivateUserError,
                      IGSentryBlockError, IGInactiveUserError, IGResponseError, IGBad2FACodeError,
                      IGLoginBadPasswordError, IGLoginInvalidUserError,
                      IGLoginTwoFactorRequiredError)

T = TypeVar('T')


class BaseAndroidAPI:
    url = URL("https://i.instagram.com")
    http: ClientSession
    state: AndroidState

    def __init__(self, state: AndroidState) -> None:
        self.http = ClientSession(cookie_jar=state.cookies.jar)
        self.state = state

    @staticmethod
    def sign(req: Any, filter_nulls: bool = False) -> Dict[str, str]:
        if isinstance(req, Serializable):
            req = req.serialize()
        if isinstance(req, dict):
            def remove_nulls(d: dict) -> dict:
                return {k: remove_nulls(v) if isinstance(v, dict) else v
                        for k, v in d.items() if v is not None}

            req = json.dumps(remove_nulls(req) if filter_nulls else req)
        return {"signed_body": f"SIGNATURE.{req}"}

    @property
    def _headers(self) -> Dict[str, str]:
        headers = {
            "User-Agent": self.state.user_agent,
            "X-Ads-Opt-Out": str(int(self.state.session.ads_opt_out)),
            # "X-DEVICE-ID": self.state.device.uuid,
            "X-CM-Bandwidth-KBPS": "-1.000",
            "X-CM-Latency": "-1.000",
            "X-IG-App-Locale": self.state.device.language,
            "X-IG-Device-Locale": self.state.device.language,
            "X-Pigeon-Session-Id": self.state.pigeon_session_id,
            "X-Pigeon-Rawclienttime": str(round(time.time(), 3)),
            "X-IG-Connection-Speed": f"{random.randint(1000, 3700)}kbps",
            "X-IG-Bandwidth-Speed-KBPS": "-1.000",
            "X-IG-Bandwidth-TotalBytes-B": "0",
            "X-IG-Bandwidth-TotalTime-MS": "0",
            "X-IG-EU-DC-ENABLED": (str(self.state.session.eu_dc_enabled).lower()
                                   if self.state.session.eu_dc_enabled is not None else None),
            "X-IG-Extended-CDN-Thumbnail-Cache-Busting-Value":
                str(self.state.session.thumbnail_cache_busting_value),
            "X-Bloks-Version-Id": self.state.application.BLOKS_VERSION_ID,
            "X-MID": self.state.cookies.get_value("mid"),
            "X-IG-WWW-Claim": self.state.session.ig_www_claim or "0",
            "X-Bloks-Is-Layout-RTL": str(self.state.device.is_layout_rtl).lower(),
            "X-IG-Connection-Type": self.state.device.connection_type,
            "X-Ig-Capabilities": self.state.application.CAPABILITIES,
            "X-IG-App-Id": self.state.application.FACEBOOK_ANALYTICS_APPLICATION_ID,
            "X-IG-Device-ID": self.state.device.uuid,
            "X-IG-Android-ID": self.state.device.id,
            "Accept-Language": self.state.device.language.replace("_", "-"),
            "X-FB-HTTP-Engine": "Liger",
            "Authorization": self.state.session.authorization,
            "Accept-Encoding": "gzip",
            "Connection": "close",
        }
        return {k: v for k, v in headers.items() if v is not None}

    async def std_http_post(self, path: str, data: Optional[JSON] = None, raw: bool = False,
                            filter_nulls: bool = False, headers: Optional[Dict[str, str]] = None,
                            response_type: Optional[Type[T]] = JSON) -> T:
        headers = {**self._headers, **headers} if headers else self._headers
        if not raw:
            data = self.sign(data, filter_nulls=filter_nulls)
        resp = await self.http.post(url=self.url.with_path(path), headers=headers, data=data)
        print(f"{path} response: {await resp.text()}")
        if response_type is str or response_type is None:
            self._handle_response_headers(resp)
            if response_type is str:
                return await resp.text()
            return None
        json_data = await self._handle_response(resp)
        if response_type is not JSON:
            return response_type.deserialize(json_data)
        return json_data

    async def std_http_get(self, path: str, query: Optional[Dict[str, str]] = None,
                           headers: Optional[Dict[str, str]] = None,
                           response_type: Optional[Type[T]] = JSON) -> T:
        headers = {**self._headers, **headers} if headers else self._headers
        query = {k: v for k, v in (query or {}).items() if v is not None}
        resp = await self.http.get(url=self.url.with_path(path).with_query(query), headers=headers)
        print(f"{path} response: {await resp.text()}")
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
        if body["status"] == "ok":
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

        raise IGResponseError(resp, data)

    def _handle_response_headers(self, resp: ClientResponse) -> None:
        fields = {
            "X-IG-Set-WWW-Claim": "ig_www_claim",
            "IG-Set-Authorization": "authorization",
            "IG-Set-Password-Encryption-Key-ID": "password_encryption_key_id",
            "IG-Set-Password-Encryption-Pub-Key": "password_encryption_pubkey",
            "IG-Set-IG-U-IG-Direct-Region-Hint": "region_hint"
        }
        for header, field in fields.items():
            value = resp.headers.get(header)
            if value and (header != "IG-Set-Authorization" or not value.endswith(":")):
                setattr(self.state.session, field, value)
