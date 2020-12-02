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
from typing import Optional, Dict
import random
import time

from aiohttp import ClientSession, ClientResponse
from yarl import URL
from mautrix.types import JSON

from ..state import AndroidState


class BaseAndroidAPI:
    url = URL("https://i.instagram.com")
    http: ClientSession
    state: AndroidState

    def __init__(self, state: AndroidState) -> None:
        self.http = ClientSession(cookie_jar=state.cookies.jar)
        self.state = state

    @property
    def headers(self) -> Dict[str, str]:
        headers = {
            "User-Agent": self.state.user_agent,
            "X-Ads-Opt-Out": str(int(self.state.session.ads_opt_out)),
            #"X-DEVICE--ID": self.state.device.uuid,
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
                                   if self.state.session.eu_dc_enabled else None),
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

    async def handle_response(self, resp: ClientResponse) -> JSON:
        self._handle_response_headers(resp)
        body = await resp.json()
        if body["status"] == "ok":
            return body
        else:
            await self._raise_response_error(resp)

    async def _raise_response_error(self, resp: ClientResponse) -> None:
        # TODO handle all errors
        print("Error:", resp.status)
        print(await resp.json())
        raise Exception("oh noes")

    def _handle_response_headers(self, resp: ClientResponse) -> None:
        fields = {
            "X-IG-Set-WWW-Claim": "ig_www_claim",
            "IG-Set-Authorization": "authorization",
            "IG-Set-Password-Encryption-Key-ID": "password_encryption_key_id",
            "IG-Set-Password-Encryption-Pub-Key": "password_encryption_pubkey",
            "IG-Set-IG-U-IG-Direct-Region-Hint": "region_hint"
        }
        for header, field in fields.items():
            try:
                value = resp.headers[header]
            except KeyError:
                pass
            else:
                if value:
                    setattr(self.state.session, field, value)
