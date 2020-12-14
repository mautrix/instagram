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
import time

from mauigpapi import AndroidAPI, AndroidState, AndroidMQTT
from mauigpapi.mqtt import Connect, Disconnect, GraphQLSubscription, SkywalkerSubscription
from mauigpapi.types import (CurrentUser, MessageSyncEvent, Operation, RealtimeDirectEvent,
                             ActivityIndicatorData, TypingStatus, ThreadSyncEvent)
from mauigpapi.errors import IGNotLoggedInError, MQTTNotLoggedIn, MQTTNotConnected
from mautrix.bridge import BaseUser
from mautrix.types import UserID, RoomID, EventID, TextMessageEventContent, MessageType
from mautrix.appservice import AppService
from mautrix.util.opt_prometheus import Summary, Gauge, async_time
from mautrix.util.logging import TraceLogger

from .db import User as DBUser, Portal as DBPortal
from .config import Config
from . import puppet as pu, portal as po

if TYPE_CHECKING:
    from .__main__ import InstagramBridge

METRIC_MESSAGE = Summary("bridge_on_message", "calls to handle_message")
METRIC_THREAD_SYNC = Summary("bridge_on_thread_sync", "calls to handle_thread_sync")
METRIC_RTD = Summary("bridge_on_rtd", "calls to handle_rtd")
METRIC_LOGGED_IN = Gauge("bridge_logged_in", "Users logged into the bridge")
METRIC_CONNECTED = Gauge("bridge_connected", "Bridged users connected to Instagram")


class User(DBUser, BaseUser):
    ig_base_log: TraceLogger = logging.getLogger("mau.instagram")
    _activity_indicator_ids: Dict[str, int] = {}
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
    _is_connected: bool
    shutdown: bool
    remote_typing_status: Optional[TypingStatus]

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
        self.mqtt = None
        self.username = None
        self.dm_update_lock = asyncio.Lock()
        self._metric_value = defaultdict(lambda: False)
        self._is_logged_in = False
        self._is_connected = False
        self.shutdown = False
        self._listen_task = None
        self.command_status = None
        self.remote_typing_status = None

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

    @property
    def api_log(self) -> TraceLogger:
        return self.ig_base_log.getChild("http").getChild(self.mxid)

    @property
    def is_connected(self) -> bool:
        return bool(self.client) and bool(self.mqtt) and self._is_connected

    async def connect(self) -> None:
        client = AndroidAPI(self.state, log=self.api_log)

        try:
            resp = await client.current_user()
        except IGNotLoggedInError as e:
            self.log.warning(f"Failed to connect to Instagram: {e}")
            # TODO show reason?
            await self.send_bridge_notice("You have been logged out of Instagram",
                                          important=True)
            return
        self.client = client
        self._is_logged_in = True
        self.igpk = resp.user.pk
        self.username = resp.user.username
        self._track_metric(METRIC_LOGGED_IN, True)
        self.by_igpk[self.igpk] = self

        self.mqtt = AndroidMQTT(self.state, loop=self.loop,
                                log=self.ig_base_log.getChild("mqtt").getChild(self.mxid))
        self.mqtt.add_event_handler(Connect, self.on_connect)
        self.mqtt.add_event_handler(Disconnect, self.on_disconnect)
        self.mqtt.add_event_handler(MessageSyncEvent, self.handle_message)
        self.mqtt.add_event_handler(ThreadSyncEvent, self.handle_thread_sync)
        self.mqtt.add_event_handler(RealtimeDirectEvent, self.handle_rtd)

        await self.update()

        self.loop.create_task(self._try_sync_puppet(resp.user))
        self.loop.create_task(self._try_sync())

    async def on_connect(self, evt: Connect) -> None:
        self.log.debug("Connected to Instagram")
        self._track_metric(METRIC_CONNECTED, True)
        self._is_connected = True
        await self.send_bridge_notice("Connected to Instagram")

    async def on_disconnect(self, evt: Disconnect) -> None:
        self.log.debug("Disconnected from Instagram")
        self._track_metric(METRIC_CONNECTED, False)
        self._is_connected = False

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
        if not important and not self.config["bridge.unimportant_bridge_notices"]:
            self.log.debug("Not sending unimportant bridge notice: %s", text)
            return
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
            await puppet.update_info(user_info, self)
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
        max_age = self.config["bridge.portal_create_max_age"] * 1_000_000
        limit = self.config["bridge.chat_sync_limit"]
        min_active_at = (time.time() * 1_000_000) - max_age
        i = 0
        async for thread in self.client.iter_inbox(start_at=resp):
            portal = await po.Portal.get_by_thread(thread, self.igpk)
            if portal.mxid:
                self.log.debug(f"{thread.thread_id} has a portal, syncing and backfilling...")
                await portal.update_matrix_room(self, thread, backfill=True)
            elif thread.last_activity_at > min_active_at:
                self.log.debug(f"{thread.thread_id} has been active recently, creating portal...")
                await portal.create_matrix_room(self, thread)
            else:
                self.log.debug(f"{thread.thread_id} is not active and doesn't have a portal")
            i += 1
            if i >= limit:
                break
        await self.update_direct_chats()

        if not self._listen_task:
            await self.start_listen(resp.seq_id, resp.snapshot_at_ms)

    async def start_listen(self, seq_id: Optional[int] = None, snapshot_at_ms: Optional[int] = None) -> None:
        if not seq_id:
            resp = await self.client.get_inbox(limit=1)
            seq_id, snapshot_at_ms = resp.seq_id, resp.snapshot_at_ms
        task = self.listen(seq_id=seq_id, snapshot_at_ms=snapshot_at_ms)
        self._listen_task = self.loop.create_task(task)

    async def listen(self, seq_id: int, snapshot_at_ms: int) -> None:
        try:
            await self.mqtt.listen(
                graphql_subs={GraphQLSubscription.app_presence(),
                              GraphQLSubscription.direct_typing(self.state.user_id),
                              GraphQLSubscription.direct_status()},
                skywalker_subs={SkywalkerSubscription.direct_sub(self.state.user_id),
                                SkywalkerSubscription.live_sub(self.state.user_id)},
                seq_id=seq_id, snapshot_at_ms=snapshot_at_ms)
        except Exception:
            self.log.exception("Fatal error in listener")
            await self.send_bridge_notice("Fatal error in listener (see logs for more info)",
                                          important=True)
            self.mqtt.disconnect()
            self._is_connected = False
            self._track_metric(METRIC_CONNECTED, False)
        else:
            if not self.shutdown:
                await self.send_bridge_notice("Instagram connection closed without error")
        finally:
            self._listen_task = None

    async def stop_listen(self) -> None:
        self.shutdown = True
        if self.mqtt:
            self.mqtt.disconnect()
            if self._listen_task:
                await self._listen_task
        self._track_metric(METRIC_CONNECTED, False)
        self._is_connected = False
        await self.update()

    async def logout(self) -> None:
        if self.client:
            try:
                await self.client.logout(one_tap_app_login=False)
            except Exception:
                self.log.debug("Exception logging out", exc_info=True)
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
        self.igpk = None
        self._is_logged_in = False
        await self.update()

    # endregion
    # region Event handlers

    @async_time(METRIC_MESSAGE)
    async def handle_message(self, evt: MessageSyncEvent) -> None:
        portal = await po.Portal.get_by_thread_id(evt.message.thread_id, receiver=self.igpk)
        if not portal or not portal.mxid:
            self.log.debug("Got message in thread with no portal, getting info...")
            resp = await self.client.get_thread(evt.message.thread_id)
            portal = await po.Portal.get_by_thread(resp.thread, self.igpk)
            self.log.debug("Got info for unknown portal, creating room")
            await portal.create_matrix_room(self, resp.thread)
            if not portal.mxid:
                self.log.warning("Room creation appears to have failed, "
                                 f"dropping message in {evt.message.thread_id}")
                return
        self.log.trace(f"Received message sync event {evt.message}")
        sender = await pu.Puppet.get_by_pk(evt.message.user_id) if evt.message.user_id else None
        if evt.message.op == Operation.ADD:
            if not sender:
                # I don't think we care about adds with no sender
                return
            await portal.handle_instagram_item(self, sender, evt.message)
        elif evt.message.op == Operation.REMOVE:
            # Removes don't have a sender, only the message sender can unsend messages anyway
            await portal.handle_instagram_remove(evt.message.item_id)
        elif evt.message.op == Operation.REPLACE:
            await portal.handle_instagram_update(evt.message)

    @async_time(METRIC_THREAD_SYNC)
    async def handle_thread_sync(self, evt: ThreadSyncEvent) -> None:
        self.log.trace("Received thread sync event %s", evt)
        portal = await po.Portal.get_by_thread(evt, receiver=self.igpk)
        await portal.create_matrix_room(self, evt)

    @async_time(METRIC_RTD)
    async def handle_rtd(self, evt: RealtimeDirectEvent) -> None:
        if not isinstance(evt.value, ActivityIndicatorData):
            return

        now = int(time.time() * 1000)
        date = int(evt.value.timestamp) // 1000
        expiry = date + evt.value.ttl
        if expiry < now:
            return

        if evt.activity_indicator_id in self._activity_indicator_ids:
            return
        # TODO clear expired items from this dict
        self._activity_indicator_ids[evt.activity_indicator_id] = expiry

        puppet = await pu.Puppet.get_by_pk(int(evt.value.sender_id))
        portal = await po.Portal.get_by_thread_id(evt.thread_id, receiver=self.igpk)
        if not puppet or not portal or not portal.mxid:
            return

        is_typing = evt.value.activity_status != TypingStatus.OFF
        if puppet.pk == self.igpk:
            self.remote_typing_status = TypingStatus.TEXT if is_typing else TypingStatus.OFF
        await puppet.intent_for(portal).set_typing(portal.mxid, is_typing=is_typing,
                                                   timeout=evt.value.ttl)

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
