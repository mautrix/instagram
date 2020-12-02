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
from typing import Optional
from http.cookies import Morsel, SimpleCookie

from aiohttp import CookieJar
from yarl import URL
from mautrix.types import Serializable, JSON

from ..errors import IGCookieNotFoundError

ig_url = URL("https://instagram.com")


class Cookies(Serializable):
    jar: CookieJar

    def __init__(self) -> None:
        self.jar = CookieJar()

    def serialize(self) -> JSON:
        return {
            "version": "tough-cookie@4.0.0",
            "storeType": "MemoryCookieStore",
            "rejectPublicSuffixes": True,
            "cookies": [{
                **morsel,
                "key": key,
                "value": morsel.value,
            } for key, morsel in self.jar.filter_cookies(ig_url).items()],
        }

    @classmethod
    def deserialize(cls, raw: JSON) -> 'Cookies':
        cookie = SimpleCookie()
        for item in raw["cookies"]:
            key = item.pop("key")
            cookie[key] = item.pop("value")
            item.pop("hostOnly", None)
            item.pop("lastAccessed", None)
            item.pop("creation", None)
            try:
                # Morsel.update() is case-insensitive, but not dash-insensitive
                item["max-age"] = item.pop("maxAge")
            except KeyError:
                pass
            cookie[key].update(item)
        cookies = cls()
        cookies.jar.update_cookies(cookie, ig_url)
        return cookies

    @property
    def csrf_token(self) -> str:
        try:
            return self["csrftoken"]
        except IGCookieNotFoundError:
            return "missing"

    @property
    def user_id(self) -> str:
        return self["ds_user_id"]

    @property
    def username(self) -> str:
        return self["ds_username"]

    def get(self, key: str) -> Morsel:
        filtered = self.jar.filter_cookies(ig_url)
        return filtered.get(key)

    def get_value(self, key: str) -> Optional[str]:
        cookie = self.get(key)
        return cookie.value if cookie else None

    def __getitem__(self, key: str) -> str:
        cookie = self.get(key)
        if not cookie:
            raise IGCookieNotFoundError(key)
        return cookie.value
