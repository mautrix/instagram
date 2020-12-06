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
from typing import (Dict, Optional, AsyncIterable, Awaitable, AsyncGenerator, List, TYPE_CHECKING,
                    cast)
from collections import defaultdict
import asyncio
import logging

from mauigpapi.mqtt import (AndroidMQTT, Connect, Disconnect, GraphQLSubscription,
                            SkywalkerSubscription)
from mauigpapi.http import AndroidAPI
from mauigpapi.state import AndroidState
from mauigpapi.types import CurrentUser, MessageSyncEvent
from mauigpapi.errors import IGNotLoggedInError
from mautrix.bridge import BaseUser
from mautrix.types import UserID, RoomID, EventID, TextMessageEventContent, MessageType
from mautrix.appservice import AppService
from mautrix.util.opt_prometheus import Summary, Gauge, async_time

from .db import User as DBUser, Portal as DBPortal
from .config import Config
from . import puppet as pu, portal as po

if TYPE_CHECKING:
    from .__main__ import InstagramBridge

METRIC_MESSAGE = Summary("bridge_on_message", "calls to handle_message")
METRIC_RECEIPT = Summary("bridge_on_receipt", "calls to handle_receipt")
METRIC_LOGGED_IN = Gauge("bridge_logged_in", "Users logged into the bridge")
METRIC_CONNECTED = Gauge("bridge_connected", "Bridged users connected to Instagram")


class User(DBUser, BaseUser):
    by_mxid: Dict[UserID, 'User'] = {}
    by_igpk: Dict[int, 'User'] = {}
    config: Config
    az: AppService
    loop: asyncio.AbstractEventLoop

    client: Optional[AndroidAPI]
    mqtt: Optional[AndroidMQTT]
    _listen_task: Optional[asyncio.Task] = None

    permission_level: str
    username: Optional[str]

    _notice_room_lock: asyncio.Lock
    _notice_send_lock: asyncio.Lock
    _is_logged_in: bool

    def __init__(self, mxid: UserID, igpk: Optional[int] = None,
                 state: Optional[AndroidState] = None, notice_room: Optional[RoomID] = None
                 ) -> None:
        super().__init__(mxid=mxid, igpk=igpk, state=state, notice_room=notice_room)
        self._notice_room_lock = asyncio.Lock()
        self._notice_send_lock = asyncio.Lock()
        perms = self.config.get_permissions(mxid)
        self.is_whitelisted, self.is_admin, self.permission_level = perms
        self.log = self.log.getChild(self.mxid)
        self.client = None
        self.username = None
        self.dm_update_lock = asyncio.Lock()
        self._metric_value = defaultdict(lambda: False)
        self._is_logged_in = False
        self._listen_task = None
        self.command_status = None

    @classmethod
    def init_cls(cls, bridge: 'InstagramBridge') -> AsyncIterable[Awaitable[None]]:
        cls.bridge = bridge
        cls.config = bridge.config
        cls.az = bridge.az
        cls.loop = bridge.loop
        return (user.try_connect() async for user in cls.all_logged_in())

    # region Connection management

    async def is_logged_in(self) -> bool:
        return bool(self.client) and self._is_logged_in

    async def try_connect(self) -> None:
        try:
            await self.connect()
        except Exception:
            self.log.exception("Error while connecting to Instagram")

    async def connect(self) -> None:
        client = AndroidAPI(self.state)

        try:
            resp = await client.current_user()
        except IGNotLoggedInError as e:
            self.log.warning(f"Failed to connect to Instagram: {e}")
            # TODO show reason?
            await self.send_bridge_notice("You have been logged out of Instagram")
            return
        self.client = client
        self._is_logged_in = True
        self.igpk = resp.user.pk
        self.username = resp.user.username
        self._track_metric(METRIC_LOGGED_IN, True)
        self.by_igpk[self.igpk] = self

        self.mqtt = AndroidMQTT(self.state, loop=self.loop,
                                log=logging.getLogger("mau.instagram.mqtt").getChild(self.mxid))
        self.mqtt.add_event_handler(Connect, self.on_connect)
        self.mqtt.add_event_handler(Disconnect, self.on_disconnect)
        self.mqtt.add_event_handler(MessageSyncEvent, self.handle_message)

        await self.update()

        self.loop.create_task(self._try_sync_puppet(resp.user))
        self.loop.create_task(self._try_sync())

    async def on_connect(self, evt: Connect) -> None:
        self._track_metric(METRIC_CONNECTED, True)

    async def on_disconnect(self, evt: Disconnect) -> None:
        self._track_metric(METRIC_CONNECTED, False)

    # TODO this stuff could probably be moved to mautrix-python
    async def get_notice_room(self) -> RoomID:
        if not self.notice_room:
            async with self._notice_room_lock:
                # If someone already created the room while this call was waiting,
                # don't make a new room
                if self.notice_room:
                    return self.notice_room
                self.notice_room = await self.az.intent.create_room(
                    is_direct=True, invitees=[self.mxid],
                    topic="Instagram bridge notices")
                await self.update()
        return self.notice_room

    async def send_bridge_notice(self, text: str, edit: Optional[EventID] = None,
                                 important: bool = False) -> Optional[EventID]:
        event_id = None
        try:
            self.log.debug("Sending bridge notice: %s", text)
            content = TextMessageEventContent(body=text, msgtype=(MessageType.TEXT if important
                                                                  else MessageType.NOTICE))
            if edit:
                content.set_edit(edit)
            # This is locked to prevent notices going out in the wrong order
            async with self._notice_send_lock:
                event_id = await self.az.intent.send_message(await self.get_notice_room(), content)
        except Exception:
            self.log.warning("Failed to send bridge notice", exc_info=True)
        return edit or event_id

    async def _try_sync_puppet(self, user_info: CurrentUser) -> None:
        puppet = await pu.Puppet.get_by_pk(self.igpk)
        try:
            await puppet.update_info(user_info)
        except Exception:
            self.log.exception("Failed to update own puppet info")
        try:
            if puppet.custom_mxid != self.mxid and puppet.can_auto_login(self.mxid):
                self.log.info(f"Automatically enabling custom puppet")
                await puppet.switch_mxid(access_token="auto", mxid=self.mxid)
        except Exception:
            self.log.exception("Failed to automatically enable custom puppet")

    async def _try_sync(self) -> None:
        try:
            await self.sync()
        except Exception:
            self.log.exception("Exception while syncing")

    async def get_direct_chats(self) -> Dict[UserID, List[RoomID]]:
        return {
            pu.Puppet.get_mxid_from_id(portal.other_user_pk): [portal.mxid]
            for portal in await DBPortal.find_private_chats_of(self.igpk)
            if portal.mxid
        }

    async def sync(self) -> None:
        resp = await self.client.get_inbox()
        limit = self.config["bridge.initial_conversation_sync"]
        threads = sorted(resp.inbox.threads, key=lambda thread: thread.last_activity_at)
        if limit < 0:
            limit = len(threads)
        for i, thread in enumerate(threads):
            portal = await po.Portal.get_by_thread(thread, self.igpk)
            if portal.mxid or i < limit:
                await portal.create_matrix_room(self, thread)
        await self.update_direct_chats()

        self._listen_task = self.loop.create_task(self.mqtt.listen(
            graphql_subs={GraphQLSubscription.app_presence(),
                          GraphQLSubscription.direct_typing(self.state.user_id),
                          GraphQLSubscription.direct_status()},
            skywalker_subs={SkywalkerSubscription.direct_sub(self.state.user_id),
                            SkywalkerSubscription.live_sub(self.state.user_id)},
            seq_id=resp.seq_id, snapshot_at_ms=resp.snapshot_at_ms))

    async def stop(self) -> None:
        if self.mqtt:
            self.mqtt.disconnect()
        self._track_metric(METRIC_CONNECTED, False)
        await self.update()

    async def logout(self) -> None:
        if self.mqtt:
            self.mqtt.disconnect()
        self._track_metric(METRIC_CONNECTED, False)
        self._track_metric(METRIC_LOGGED_IN, False)
        puppet = await pu.Puppet.get_by_pk(self.igpk, create=False)
        if puppet and puppet.is_real_user:
            await puppet.switch_mxid(None, None)
        try:
            del self.by_igpk[self.igpk]
        except KeyError:
            pass
        self.client = None
        self.mqtt = None
        self.state = None
        self._is_logged_in = False
        await self.update()

    # endregion
    # region Event handlers

    @async_time(METRIC_MESSAGE)
    async def handle_message(self, evt: MessageSyncEvent) -> None:
        # We don't care about messages with no sender
        if not evt.message.user_id:
            return
        portal = await po.Portal.get_by_thread_id(evt.message.thread_id, receiver=self.igpk)
        if not portal.mxid:
            # TODO try to find the thread?
            self.log.warning(f"Ignoring message to unknown thread {evt.message.thread_id}")
            return
        sender = await pu.Puppet.get_by_pk(evt.message.user_id)
        await portal.handle_instagram_item(self, sender, evt.message)

    # @async_time(METRIC_RECEIPT)
    # async def handle_receipt(self, evt: ConversationReadEntry) -> None:
    #     portal = await po.Portal.get_by_twid(evt.conversation_id, self.twid,
    #                                          conv_type=evt.conversation.type)
    #     if not portal.mxid:
    #         return
    #     sender = await pu.Puppet.get_by_twid(self.twid)
    #     await portal.handle_twitter_receipt(sender, int(evt.last_read_event_id))

    # endregion
    # region Database getters

    def _add_to_cache(self) -> None:
        self.by_mxid[self.mxid] = self
        if self.igpk:
            self.by_igpk[self.igpk] = self

    @classmethod
    async def get_by_mxid(cls, mxid: UserID, create: bool = True) -> Optional['User']:
        # Never allow ghosts to be users
        if pu.Puppet.get_id_from_mxid(mxid):
            return None
        try:
            return cls.by_mxid[mxid]
        except KeyError:
            pass

        user = cast(cls, await super().get_by_mxid(mxid))
        if user is not None:
            user._add_to_cache()
            return user

        if create:
            user = cls(mxid)
            await user.insert()
            user._add_to_cache()
            return user

        return None

    @classmethod
    async def get_by_igpk(cls, igpk: int) -> Optional['User']:
        try:
            return cls.by_igpk[igpk]
        except KeyError:
            pass

        user = cast(cls, await super().get_by_igpk(igpk))
        if user is not None:
            user._add_to_cache()
            return user

        return None

    @classmethod
    async def all_logged_in(cls) -> AsyncGenerator['User', None]:
        users = await super().all_logged_in()
        user: cls
        for index, user in enumerate(users):
            try:
                yield cls.by_mxid[user.mxid]
            except KeyError:
                user._add_to_cache()
                yield user

    # endregion
