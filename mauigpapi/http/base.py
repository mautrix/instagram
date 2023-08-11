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

from typing import Any, Awaitable, Callable, Type, TypeVar
from functools import partial
import json
import logging
import time

from aiohttp import ClientResponse, ClientSession, ContentTypeError, CookieJar
from yarl import URL

from mautrix.types import JSON, Serializable
from mautrix.util.logging import TraceLogger
from mautrix.util.proxy import ProxyHandler, proxy_with_retry

from ..errors import (
    IG2FACodeExpiredError,
    IGActionSpamError,
    IGBad2FACodeError,
    IGChallengeError,
    IGCheckpointError,
    IGConsentRequiredError,
    IGFBEmailTaken,
    IGFBNoContactPointFoundError,
    IGFBSSODisabled,
    IGInactiveUserError,
    IGLoginBadPasswordError,
    IGLoginInvalidCredentialsError,
    IGLoginInvalidUserError,
    IGLoginRequiredError,
    IGLoginTwoFactorRequiredError,
    IGLoginUnusablePasswordError,
    IGNotFoundError,
    IGPrivateUserError,
    IGRateLimitError,
    IGResponseError,
    IGSentryBlockError,
    IGUnknownError,
    IGUserHasLoggedOutError,
)
from ..state import AndroidState
from ..types import ChallengeContext

try:
    from aiohttp_socks import ProxyConnector
except ImportError:
    ProxyConnector = None

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

    def __init__(
        self,
        state: AndroidState,
        log: TraceLogger | None = None,
        proxy_handler: ProxyHandler | None = None,
        on_proxy_update: Callable[[], Awaitable[None]] | None = None,
        on_response_error: Callable[[IGResponseError], Awaitable[None]] | None = None,
    ) -> None:
        self.log = log or logging.getLogger("mauigpapi.http")

        self.proxy_handler = proxy_handler
        self.on_proxy_update = on_proxy_update
        self.on_response_error = on_response_error
        self.setup_http(cookie_jar=state.cookies.jar)

        self.state = state

        self.proxy_with_retry = partial(
            proxy_with_retry,
            logger=self.log,
            proxy_handler=self.proxy_handler,
            on_proxy_change=self.on_proxy_update,
            # Wait 1s * errors, max 10s for fast failure
            max_wait_seconds=10,
            multiply_wait_seconds=1,
        )

    @staticmethod
    def sign(req: Any, filter_nulls: bool = False) -> dict[str, str]:
        if isinstance(req, Serializable):
            req = req.serialize()
        if isinstance(req, dict):
            req = json.dumps(remove_nulls(req) if filter_nulls else req)
        return {"signed_body": f"SIGNATURE.{req}"}

    @property
    def _rupload_headers(self) -> dict[str, str]:
        headers = {
            "user-agent": self.state.user_agent,
            "accept-language": self.state.device.language.replace("_", "-"),
            "authorization": self.state.session.authorization,
            "x-mid": self.state.cookies.get_value("mid"),
            "ig-u-shbid": self.state.session.shbid,
            "ig-u-shbts": self.state.session.shbts,
            "ig-u-ds-user-id": self.state.session.ds_user_id,
            "ig-u-rur": self.state.session.rur,
            "ig-intended-user-id": self.state.session.ds_user_id or "0",
            "x-fb-http-engine": "Liger",
            "x-fb-client-ip": "True",
            "x-fb-server-cluster": "True",
            "accept-encoding": "gzip",
        }
        return {k: v for k, v in headers.items() if v is not None}

    @property
    def _headers(self) -> dict[str, str]:
        headers = {
            "x-ads-opt-out": str(int(self.state.session.ads_opt_out)),
            "x-device-id": self.state.device.uuid,
            "x-ig-app-locale": self.state.device.language,
            "x-ig-device-locale": self.state.device.language,
            "x-ig-mapped-locale": self.state.device.language,
            "x-pigeon-session-id": f"UFS-{self.state.pigeon_session_id}-0",
            "x-pigeon-rawclienttime": str(round(time.time(), 3)),
            "x-ig-bandwidth-speed-kbps": "-1.000",
            "x-ig-bandwidth-totalbytes-b": "0",
            "x-ig-bandwidth-totaltime-ms": "0",
            "x-ig-app-startup-country": self.state.device.language.split("_")[1],
            "x-bloks-version-id": self.state.application.BLOKS_VERSION_ID,
            "x-ig-www-claim": self.state.session.ig_www_claim or "0",
            "x-bloks-is-layout-rtl": str(self.state.device.is_layout_rtl).lower(),
            "x-ig-timezone-offset": self.state.device.timezone_offset,
            "x-ig-device-id": self.state.device.uuid,
            "x-ig-family-device-id": self.state.device.fdid,
            "x-ig-android-id": self.state.device.id,
            "x-ig-connection-type": self.state.device.connection_type,
            "x-fb-connection-type": self.state.device.connection_type,
            "x-ig-capabilities": self.state.application.CAPABILITIES,
            "x-ig-app-id": self.state.application.FACEBOOK_ANALYTICS_APPLICATION_ID,
            "ig-client-endpoint": "unknown",
            "x-fb-rmd": "cached=0;state=NO_MATCH",
            "x-tigon-is-retry": "False",
            "ig-u-ig-direct-region-hint": self.state.session.region_hint,
            **self._rupload_headers,
        }
        return {k: v for k, v in headers.items() if v is not None}

    def setup_http(self, cookie_jar: CookieJar) -> None:
        connector = None
        http_proxy = self.proxy_handler.get_proxy_url() if self.proxy_handler else None
        if http_proxy:
            if ProxyConnector:
                connector = ProxyConnector.from_url(http_proxy)
            else:
                self.log.warning("http_proxy is set, but aiohttp-socks is not installed")

        self.http = ClientSession(connector=connector, cookie_jar=cookie_jar)
        return None

    def raw_http_get(self, url: URL | str, **kwargs):
        if isinstance(url, str):
            url = URL(url, encoded=True)
        return self.http.get(
            url,
            headers={
                "user-agent": self.state.user_agent,
                "accept-language": self.state.device.language.replace("_", "-"),
            },
            **kwargs,
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
        default_headers: bool = True,
        url_override: URL | None = None,
    ) -> T:
        if default_headers:
            headers = {**self._headers, **headers} if headers else self._headers
        if not raw:
            data = self.sign(data, filter_nulls=filter_nulls)
        url = (url_override or self.url).with_path(path).with_query(query or {})
        resp = await self.proxy_with_retry(
            f"AndroidAPI.std_http_post: {url}",
            lambda: self.http.post(url=url, headers=headers, data=data),
        )
        self.log.trace(f"{path} response: {await resp.text()}")
        if response_type is str or response_type is None:
            self._handle_response_headers(resp)
            if response_type is str:
                return await resp.text()
            return None
        json_data = await self._handle_response(resp, is_external=bool(url_override))
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
        url = self.url.with_path(path).with_query(query)
        resp = await self.proxy_with_retry(
            f"AndroidAPI.std_http_get: {url}",
            lambda: self.http.get(url=url, headers=headers),
        )
        self.log.trace(f"{path} response: {await resp.text()}")
        if response_type is None:
            self._handle_response_headers(resp)
            return None
        json_data = await self._handle_response(resp, is_external=False)
        if response_type is not JSON:
            return response_type.deserialize(json_data)
        return json_data

    async def _handle_response(self, resp: ClientResponse, is_external: bool) -> JSON:
        if not is_external:
            self._handle_response_headers(resp)
        try:
            body = await resp.json()
        except (json.JSONDecodeError, ContentTypeError) as e:
            raise IGUnknownError(resp) from e
        if not is_external and body.get("status", "fail") == "ok":
            return body
        elif is_external and 200 <= resp.status < 300:
            return body
        else:
            err = await self._get_response_error(resp)
            if self.on_response_error:
                await self.on_response_error(err)
            raise err

    async def _get_response_error(self, resp: ClientResponse) -> IGResponseError:
        try:
            data = await resp.json()
        except json.JSONDecodeError:
            data = {}

        if data.get("spam", False):
            return IGActionSpamError(resp, data)
        elif data.get("two_factor_required", False):
            return IGLoginTwoFactorRequiredError(resp, data)
        elif resp.status == 404:
            return IGNotFoundError(resp, data)
        elif resp.status == 429:
            return IGRateLimitError(resp, data)

        message = data.get("message")
        if isinstance(message, str):
            if message == "challenge_required":
                err = IGChallengeError(resp, data)
                self.log.debug(f"Storing challenge URL {err.url}")
                self.state.challenge_path = err.url
                try:
                    self.state.challenge_context = ChallengeContext.parse_json(
                        err.body.challenge.challenge_context
                    )
                except Exception:
                    self.log.exception(
                        "Failed to deserialize challenge_context %s",
                        err.body.challenge.challenge_context,
                    )
                return err
            elif message == "checkpoint_required":
                return IGCheckpointError(resp, data)
            elif message == "consent_required":
                return IGConsentRequiredError(resp, data)
            elif message == "user_has_logged_out":
                return IGUserHasLoggedOutError(resp, data)
            elif message == "login_required":
                return IGLoginRequiredError(resp, data)
            elif message.lower() == "not authorized to view user":
                return IGPrivateUserError(resp, data)

        error_type = data.get("error_type")
        if error_type == "sentry_block":
            return IGSentryBlockError(resp, data)
        elif error_type == "inactive_user":
            return IGInactiveUserError(resp, data)
        elif error_type == "bad_password":
            return IGLoginBadPasswordError(resp, data)
        elif error_type == "unusable_password":
            return IGLoginUnusablePasswordError(resp, data)
        elif error_type == "invalid_user":
            return IGLoginInvalidUserError(resp, data)
        elif error_type == "sms_code_validation_code_invalid":
            return IGBad2FACodeError(resp, data)
        elif error_type == "invalid_nonce":
            return IG2FACodeExpiredError(resp, data)
        elif error_type == "fb_no_contact_point_found":
            return IGFBNoContactPointFoundError(resp, data)
        elif error_type == "fb_email_taken":
            return IGFBEmailTaken(resp, data)
        elif error_type == "sso_disabled":
            return IGFBSSODisabled(resp, data)
        elif error_type == "rate_limit_error":
            return IGRateLimitError(resp, data)

        exception_name = data.get("exception_name")
        if exception_name == "UserInvalidCredentials":
            return IGLoginInvalidCredentialsError(resp, data)

        return IGResponseError(resp, data)

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
