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

from typing import TYPE_CHECKING, AsyncGenerator, AsyncIterable, Awaitable, cast
import os.path

from yarl import URL

from mauigpapi.types import BaseResponseUser
from mautrix.appservice import IntentAPI
from mautrix.bridge import BasePuppet, async_getter_lock
from mautrix.types import ContentURI, RoomID, SyncToken, UserID
from mautrix.util.simple_template import SimpleTemplate

from . import portal as p, user as u
from .config import Config
from .db import Puppet as DBPuppet

if TYPE_CHECKING:
    from .__main__ import InstagramBridge


class Puppet(DBPuppet, BasePuppet):
    by_pk: dict[int, Puppet] = {}
    by_custom_mxid: dict[UserID, Puppet] = {}
    hs_domain: str
    mxid_template: SimpleTemplate[int]

    config: Config

    default_mxid_intent: IntentAPI
    default_mxid: UserID

    def __init__(
        self,
        pk: int,
        name: str | None = None,
        username: str | None = None,
        photo_id: str | None = None,
        photo_mxc: ContentURI | None = None,
        name_set: bool = False,
        avatar_set: bool = False,
        is_registered: bool = False,
        custom_mxid: UserID | None = None,
        access_token: str | None = None,
        next_batch: SyncToken | None = None,
        base_url: URL | None = None,
    ) -> None:
        super().__init__(
            pk=pk,
            name=name,
            username=username,
            photo_id=photo_id,
            name_set=name_set,
            photo_mxc=photo_mxc,
            avatar_set=avatar_set,
            is_registered=is_registered,
            custom_mxid=custom_mxid,
            access_token=access_token,
            next_batch=next_batch,
            base_url=base_url,
        )
        self.log = self.log.getChild(str(pk))

        self.default_mxid = self.get_mxid_from_id(pk)
        self.default_mxid_intent = self.az.intent.user(self.default_mxid)
        self.intent = self._fresh_intent()

    @classmethod
    def init_cls(cls, bridge: "InstagramBridge") -> AsyncIterable[Awaitable[None]]:
        cls.config = bridge.config
        cls.loop = bridge.loop
        cls.mx = bridge.matrix
        cls.az = bridge.az
        cls.hs_domain = cls.config["homeserver.domain"]
        cls.mxid_template = SimpleTemplate(
            cls.config["bridge.username_template"],
            "userid",
            prefix="@",
            suffix=f":{cls.hs_domain}",
            type=int,
        )
        cls.sync_with_custom_puppets = cls.config["bridge.sync_with_custom_puppets"]
        cls.homeserver_url_map = {
            server: URL(url)
            for server, url in cls.config["bridge.double_puppet_server_map"].items()
        }
        cls.allow_discover_url = cls.config["bridge.double_puppet_allow_discovery"]
        cls.login_shared_secret_map = {
            server: secret.encode("utf-8")
            for server, secret in cls.config["bridge.login_shared_secret_map"].items()
        }
        cls.login_device_name = "Instagram Bridge"
        return (puppet.try_start() async for puppet in cls.all_with_custom_mxid())

    @property
    def igpk(self) -> int:
        return self.pk

    def intent_for(self, portal: p.Portal) -> IntentAPI:
        if portal.other_user_pk == self.pk:
            return self.default_mxid_intent
        return self.intent

    def need_backfill_invite(self, portal: p.Portal) -> bool:
        return (
            portal.other_user_pk != self.pk
            and (self.is_real_user or portal.is_direct)
            and self.config["bridge.backfill.invite_own_puppet"]
        )

    async def update_info(self, info: BaseResponseUser, source: u.User) -> None:
        update = False
        update = await self._update_name(info) or update
        update = await self._update_avatar(info, source) or update
        if update:
            await self.update()

    @classmethod
    def _get_displayname(cls, info: BaseResponseUser) -> str:
        return cls.config["bridge.displayname_template"].format(
            displayname=info.full_name or info.username, id=info.pk, username=info.username
        )

    async def _update_name(self, info: BaseResponseUser) -> bool:
        name = self._get_displayname(info)
        if name != self.name:
            self.name = name
            try:
                await self.default_mxid_intent.set_displayname(self.name)
                self.name_set = True
            except Exception:
                self.log.exception("Failed to update displayname")
                self.name_set = False
            return True
        return False

    async def _update_avatar(self, info: BaseResponseUser, source: u.User) -> bool:
        pic_id = (
            f"id_{info.profile_pic_id}.jpg"
            if info.profile_pic_id
            else os.path.basename(URL(info.profile_pic_url).path)
        )
        if pic_id != self.photo_id or not self.avatar_set:
            self.photo_id = pic_id
            if info.has_anonymous_profile_picture:
                mxc = None
            else:
                async with source.client.raw_http_get(info.profile_pic_url) as resp:
                    content_type = resp.headers["Content-Type"]
                    resp_data = await resp.read()
                mxc = await self.default_mxid_intent.upload_media(
                    data=resp_data,
                    mime_type=content_type,
                    filename=pic_id,
                    async_upload=self.config["homeserver.async_media"],
                )
            try:
                await self.default_mxid_intent.set_avatar_url(mxc)
                self.avatar_set = True
                self.photo_mxc = mxc
            except Exception:
                self.log.exception("Failed to update avatar")
                self.avatar_set = False
            return True
        return False

    async def default_puppet_should_leave_room(self, room_id: RoomID) -> bool:
        portal = await p.Portal.get_by_mxid(room_id)
        return portal and portal.other_user_pk != self.pk

    # region Database getters

    def _add_to_cache(self) -> None:
        self.by_pk[self.pk] = self
        if self.custom_mxid:
            self.by_custom_mxid[self.custom_mxid] = self

    async def save(self) -> None:
        await self.update()

    @classmethod
    async def get_by_mxid(cls, mxid: UserID, create: bool = True) -> Puppet | None:
        pk = cls.get_id_from_mxid(mxid)
        if pk:
            return await cls.get_by_pk(pk, create=create)
        return None

    @classmethod
    @async_getter_lock
    async def get_by_custom_mxid(cls, mxid: UserID) -> Puppet | None:
        try:
            return cls.by_custom_mxid[mxid]
        except KeyError:
            pass

        puppet = cast(cls, await super().get_by_custom_mxid(mxid))
        if puppet:
            puppet._add_to_cache()
            return puppet

        return None

    @classmethod
    def get_id_from_mxid(cls, mxid: UserID) -> int | None:
        return cls.mxid_template.parse(mxid)

    @classmethod
    def get_mxid_from_id(cls, pk: int) -> UserID:
        return UserID(cls.mxid_template.format_full(pk))

    @classmethod
    @async_getter_lock
    async def get_by_pk(cls, pk: int, *, create: bool = True) -> Puppet | None:
        try:
            return cls.by_pk[pk]
        except KeyError:
            pass

        puppet = cast(cls, await super().get_by_pk(pk))
        if puppet is not None:
            puppet._add_to_cache()
            return puppet

        if create:
            puppet = cls(pk)
            await puppet.insert()
            puppet._add_to_cache()
            return puppet

        return None

    @classmethod
    async def all_with_custom_mxid(cls) -> AsyncGenerator[Puppet, None]:
        puppets = await super().all_with_custom_mxid()
        puppet: cls
        for index, puppet in enumerate(puppets):
            try:
                yield cls.by_pk[puppet.pk]
            except KeyError:
                puppet._add_to_cache()
                yield puppet

    # endregion
