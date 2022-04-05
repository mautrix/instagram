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
import asyncio
import logging
import time

from mauigpapi import AndroidAPI, AndroidMQTT, AndroidState
from mauigpapi.errors import (
    IGCheckpointError,
    IGConsentRequiredError,
    IGNotLoggedInError,
    IGUserIDNotFoundError,
    IrisSubscribeError,
    MQTTNotConnected,
    MQTTNotLoggedIn,
)
from mauigpapi.mqtt import Connect, Disconnect, GraphQLSubscription, SkywalkerSubscription
from mauigpapi.types import (
    ActivityIndicatorData,
    CurrentUser,
    MessageSyncEvent,
    Operation,
    RealtimeDirectEvent,
    Thread,
    ThreadSyncEvent,
    TypingStatus,
)
from mautrix.appservice import AppService
from mautrix.bridge import BaseUser, async_getter_lock
from mautrix.types import EventID, MessageType, RoomID, TextMessageEventContent, UserID
from mautrix.util.bridge_state import BridgeState, BridgeStateEvent
from mautrix.util.logging import TraceLogger
from mautrix.util.opt_prometheus import Gauge, Summary, async_time

from . import portal as po, puppet as pu
from .config import Config
from .db import Portal as DBPortal, User as DBUser

if TYPE_CHECKING:
    from .__main__ import InstagramBridge

METRIC_MESSAGE = Summary("bridge_on_message", "calls to handle_message")
METRIC_THREAD_SYNC = Summary("bridge_on_thread_sync", "calls to handle_thread_sync")
METRIC_RTD = Summary("bridge_on_rtd", "calls to handle_rtd")
METRIC_LOGGED_IN = Gauge("bridge_logged_in", "Users logged into the bridge")
METRIC_CONNECTED = Gauge("bridge_connected", "Bridged users connected to Instagram")

BridgeState.human_readable_errors.update(
    {
        "ig-connection-error": "Instagram disconnected unexpectedly",
        "ig-auth-error": "Authentication error from Instagram: {message}",
        "ig-checkpoint": "Instagram checkpoint error. Please check the Instagram website.",
        "ig-consent-required": "Instagram requires a consent update. Please check the Instagram website.",
        "ig-checkpoint-locked": "Instagram checkpoint error. Please check the Instagram website.",
        "ig-disconnected": None,
        "ig-no-mqtt": "You're not connected to Instagram",
        "logged-out": "You're not logged into Instagram",
    }
)


class User(DBUser, BaseUser):
    ig_base_log: TraceLogger = logging.getLogger("mau.instagram")
    _activity_indicator_ids: dict[str, int] = {}
    by_mxid: dict[UserID, User] = {}
    by_igpk: dict[int, User] = {}
    config: Config
    az: AppService
    loop: asyncio.AbstractEventLoop

    client: AndroidAPI | None
    mqtt: AndroidMQTT | None
    _listen_task: asyncio.Task | None = None

    permission_level: str
    username: str | None

    _notice_room_lock: asyncio.Lock
    _notice_send_lock: asyncio.Lock
    _is_logged_in: bool
    _is_connected: bool
    shutdown: bool
    remote_typing_status: TypingStatus | None

    def __init__(
        self,
        mxid: UserID,
        igpk: int | None = None,
        state: AndroidState | None = None,
        notice_room: RoomID | None = None,
    ) -> None:
        super().__init__(mxid=mxid, igpk=igpk, state=state, notice_room=notice_room)
        BaseUser.__init__(self)
        self._notice_room_lock = asyncio.Lock()
        self._notice_send_lock = asyncio.Lock()
        perms = self.config.get_permissions(mxid)
        self.relay_whitelisted, self.is_whitelisted, self.is_admin, self.permission_level = perms
        self.client = None
        self.mqtt = None
        self.username = None
        self._is_logged_in = False
        self._is_connected = False
        self._is_refreshing = False
        self.shutdown = False
        self._listen_task = None
        self.remote_typing_status = None

    @classmethod
    def init_cls(cls, bridge: "InstagramBridge") -> AsyncIterable[Awaitable[None]]:
        cls.bridge = bridge
        cls.config = bridge.config
        cls.az = bridge.az
        cls.loop = bridge.loop
        return (user.try_connect() async for user in cls.all_logged_in())

    # region Connection management

    async def is_logged_in(self) -> bool:
        return bool(self.client) and self._is_logged_in

    async def get_puppet(self) -> pu.Puppet | None:
        if not self.igpk:
            return None
        return await pu.Puppet.get_by_pk(self.igpk)

    async def get_portal_with(self, puppet: pu.Puppet, create: bool = True) -> po.Portal | None:
        if not self.igpk:
            return None
        portal = await po.Portal.find_private_chat(self.igpk, puppet.pk)
        if portal:
            return portal
        if create:
            # TODO add error handling somewhere
            thread = await self.client.create_group_thread([puppet.pk])
            portal = await po.Portal.get_by_thread(thread, self.igpk)
            await portal.update_info(thread, self)
            return portal
        return None

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

    async def connect(self, user: CurrentUser | None = None) -> None:
        if not self.state:
            await self.push_bridge_state(BridgeStateEvent.BAD_CREDENTIALS, error="logged-out")
            return
        client = AndroidAPI(self.state, log=self.api_log)

        if not user:
            try:
                resp = await client.current_user()
                user = resp.user
            except IGNotLoggedInError as e:
                self.log.warning(f"Failed to connect to Instagram: {e}, logging out")
                await self.logout(error=e)
                return
            except (IGCheckpointError, IGConsentRequiredError) as e:
                await self._handle_checkpoint(e, on="connect", client=client)
                return
        self.client = client
        self._is_logged_in = True
        self.igpk = user.pk
        self.username = user.username
        await self.push_bridge_state(BridgeStateEvent.CONNECTING)
        self._track_metric(METRIC_LOGGED_IN, True)
        self.by_igpk[self.igpk] = self

        self.mqtt = AndroidMQTT(
            self.state, loop=self.loop, log=self.ig_base_log.getChild("mqtt").getChild(self.mxid)
        )
        self.mqtt.add_event_handler(Connect, self.on_connect)
        self.mqtt.add_event_handler(Disconnect, self.on_disconnect)
        self.mqtt.add_event_handler(MessageSyncEvent, self.handle_message)
        self.mqtt.add_event_handler(ThreadSyncEvent, self.handle_thread_sync)
        self.mqtt.add_event_handler(RealtimeDirectEvent, self.handle_rtd)

        await self.update()

        self.loop.create_task(self._try_sync_puppet(user))
        self.loop.create_task(self._try_sync())

    async def on_connect(self, evt: Connect) -> None:
        self.log.debug("Connected to Instagram")
        self._track_metric(METRIC_CONNECTED, True)
        self._is_connected = True
        await self.send_bridge_notice("Connected to Instagram")
        await self.push_bridge_state(BridgeStateEvent.CONNECTED)

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
                creation_content = {}
                if not self.config["bridge.federate_rooms"]:
                    creation_content["m.federate"] = False
                self.notice_room = await self.az.intent.create_room(
                    is_direct=True,
                    invitees=[self.mxid],
                    topic="Instagram bridge notices",
                    creation_content=creation_content,
                )
                await self.update()
        return self.notice_room

    async def fill_bridge_state(self, state: BridgeState) -> None:
        await super().fill_bridge_state(state)
        if not state.remote_id:
            if self.igpk:
                state.remote_id = str(self.igpk)
            else:
                try:
                    state.remote_id = self.state.user_id
                except IGUserIDNotFoundError:
                    state.remote_id = None
        if self.username:
            state.remote_name = f"@{self.username}"

    async def get_bridge_states(self) -> list[BridgeState]:
        if not self.state:
            return []
        state = BridgeState(state_event=BridgeStateEvent.UNKNOWN_ERROR)
        if self.is_connected:
            state.state_event = BridgeStateEvent.CONNECTED
        elif self._is_refreshing or self.mqtt:
            state.state_event = BridgeStateEvent.TRANSIENT_DISCONNECT
        return [state]

    async def send_bridge_notice(
        self,
        text: str,
        edit: EventID | None = None,
        state_event: BridgeStateEvent | None = None,
        important: bool = False,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> EventID | None:
        if state_event:
            await self.push_bridge_state(
                state_event, error=error_code, message=error_message if error_code else text
            )
        if self.config["bridge.disable_bridge_notices"]:
            return None
        if not important and not self.config["bridge.unimportant_bridge_notices"]:
            self.log.debug("Not sending unimportant bridge notice: %s", text)
            return None
        event_id = None
        try:
            self.log.debug("Sending bridge notice: %s", text)
            content = TextMessageEventContent(
                body=text, msgtype=(MessageType.TEXT if important else MessageType.NOTICE)
            )
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
            await self.push_bridge_state(BridgeStateEvent.UNKNOWN_ERROR)

    async def get_direct_chats(self) -> dict[UserID, list[RoomID]]:
        return {
            pu.Puppet.get_mxid_from_id(portal.other_user_pk): [portal.mxid]
            for portal in await DBPortal.find_private_chats_of(self.igpk)
            if portal.mxid
        }

    async def refresh(self, resync: bool = True) -> None:
        self._is_refreshing = True
        try:
            await self.stop_listen()
            if resync:
                retry_count = 0
                minutes = 1
                while True:
                    try:
                        await self.sync()
                        return
                    except IGNotLoggedInError as e:
                        self.log.exception("Got not logged in error while syncing for refresh")
                        await self.logout(error=e)
                    except IGCheckpointError as e:
                        await self._handle_checkpoint(e, on="refresh")
                        return
                    except Exception:
                        if retry_count >= 4 and minutes < 5:
                            minutes += 1
                        retry_count += 1
                        s = "s" if minutes != 1 else ""
                        self.log.exception(
                            f"Error while syncing for refresh, retrying in {minutes} minute{s}"
                        )
                        await self.push_bridge_state(BridgeStateEvent.UNKNOWN_ERROR)
                        await asyncio.sleep(minutes * 60)
            else:
                await self.start_listen()
        finally:
            self._is_refreshing = False

    async def _handle_checkpoint(
        self,
        e: IGCheckpointError | IGConsentRequiredError,
        on: str,
        client: AndroidAPI | None = None,
    ) -> None:
        self.log.warning(f"Got checkpoint error on {on}: {e.body.serialize()}")
        client = client or self.client
        self.client = None
        self.mqtt = None
        if isinstance(e, IGConsentRequiredError):
            await self.push_bridge_state(
                BridgeStateEvent.BAD_CREDENTIALS,
                error="ig-consent-required",
                info=e.body.serialize(),
            )
            return
        error_code = "ig-checkpoint"
        try:
            resp = await client.challenge_reset()
            info = {
                "challenge_context": (
                    resp.challenge_context.serialize() if resp.challenge_context_str else None
                ),
                "step_name": resp.step_name,
                "step_data": resp.step_data.serialize() if resp.step_data else None,
                "user_id": resp.user_id,
                "action": resp.action,
                "status": resp.status,
                "challenge": e.body.challenge.serialize() if e.body.challenge else None,
            }
            self.log.debug(f"Challenge state: {resp.serialize()}")
            if resp.challenge_context.challenge_type_enum == "HACKED_LOCK":
                error_code = "ig-checkpoint-locked"
        except Exception:
            self.log.exception("Error resetting challenge state")
            info = {"challenge": e.body.challenge.serialize() if e.body.challenge else None}
        await self.push_bridge_state(BridgeStateEvent.BAD_CREDENTIALS, error=error_code, info=info)
        # if on == "connect":
        #     await self.connect()
        # else:
        #     await self.sync()

    async def _sync_thread(self, thread: Thread, min_active_at: int) -> None:
        portal = await po.Portal.get_by_thread(thread, self.igpk)
        if portal.mxid:
            self.log.debug(f"{thread.thread_id} has a portal, syncing and backfilling...")
            await portal.update_matrix_room(self, thread, backfill=True)
        elif thread.last_activity_at > min_active_at:
            self.log.debug(f"{thread.thread_id} has been active recently, creating portal...")
            await portal.create_matrix_room(self, thread)
        else:
            self.log.debug(f"{thread.thread_id} is not active and doesn't have a portal")

    async def sync(self) -> None:
        resp = await self.client.get_inbox()

        if not self._listen_task:
            await self.start_listen(resp.seq_id, resp.snapshot_at_ms)

        max_age = self.config["bridge.portal_create_max_age"] * 1_000_000
        limit = self.config["bridge.chat_sync_limit"]
        min_active_at = (time.time() * 1_000_000) - max_age
        i = 0
        await self.push_bridge_state(BridgeStateEvent.BACKFILLING)
        async for thread in self.client.iter_inbox(start_at=resp):
            try:
                await self._sync_thread(thread, min_active_at)
            except Exception:
                self.log.exception(f"Error syncing thread {thread.thread_id}")
            i += 1
            if i >= limit:
                break
        try:
            await self.update_direct_chats()
        except Exception:
            self.log.exception("Error updating direct chat list")

    async def start_listen(
        self, seq_id: int | None = None, snapshot_at_ms: int | None = None
    ) -> None:
        self.shutdown = False
        if not seq_id:
            resp = await self.client.get_inbox(limit=1)
            seq_id, snapshot_at_ms = resp.seq_id, resp.snapshot_at_ms
        task = self.listen(seq_id=seq_id, snapshot_at_ms=snapshot_at_ms)
        self._listen_task = self.loop.create_task(task)

    async def listen(self, seq_id: int, snapshot_at_ms: int) -> None:
        try:
            await self.mqtt.listen(
                graphql_subs={
                    GraphQLSubscription.app_presence(),
                    GraphQLSubscription.direct_typing(self.state.user_id),
                    GraphQLSubscription.direct_status(),
                },
                skywalker_subs={
                    SkywalkerSubscription.direct_sub(self.state.user_id),
                    SkywalkerSubscription.live_sub(self.state.user_id),
                },
                seq_id=seq_id,
                snapshot_at_ms=snapshot_at_ms,
            )
        except IrisSubscribeError as e:
            self.log.warning(f"Got IrisSubscribeError {e}, refreshing...")
            await self.refresh()
        except (MQTTNotConnected, MQTTNotLoggedIn) as e:
            await self.send_bridge_notice(
                f"Error in listener: {e}",
                important=True,
                state_event=BridgeStateEvent.UNKNOWN_ERROR,
                error_code="ig-connection-error",
            )
            self.mqtt.disconnect()
        except Exception:
            self.log.exception("Fatal error in listener")
            await self.send_bridge_notice(
                "Fatal error in listener (see logs for more info)",
                state_event=BridgeStateEvent.UNKNOWN_ERROR,
                important=True,
                error_code="ig-connection-error",
            )
            self.mqtt.disconnect()
        else:
            if not self.shutdown:
                await self.send_bridge_notice(
                    "Instagram connection closed without error",
                    state_event=BridgeStateEvent.UNKNOWN_ERROR,
                    error_code="ig-disconnected",
                )
        finally:
            self._listen_task = None
            self._is_connected = False
            self._track_metric(METRIC_CONNECTED, False)

    async def stop_listen(self) -> None:
        if self.mqtt:
            self.shutdown = True
            self.mqtt.disconnect()
            if self._listen_task:
                await self._listen_task
            self.shutdown = False
        self._track_metric(METRIC_CONNECTED, False)
        self._is_connected = False
        await self.update()

    async def logout(self, error: IGNotLoggedInError | None = None) -> None:
        if self.client and error is None:
            try:
                await self.client.logout(one_tap_app_login=False)
            except Exception:
                self.log.debug("Exception logging out", exc_info=True)
        if self.mqtt:
            self.mqtt.disconnect()
        self._track_metric(METRIC_CONNECTED, False)
        self._track_metric(METRIC_LOGGED_IN, False)
        if error is None:
            await self.push_bridge_state(BridgeStateEvent.LOGGED_OUT)
            puppet = await pu.Puppet.get_by_pk(self.igpk, create=False)
            if puppet and puppet.is_real_user:
                await puppet.switch_mxid(None, None)
            try:
                del self.by_igpk[self.igpk]
            except KeyError:
                pass
            self.igpk = None
        else:
            self.log.debug("Auth error body: %s", error.body.serialize())
            await self.send_bridge_notice(
                f"You have been logged out of Instagram: {error.proper_message}",
                important=True,
                state_event=BridgeStateEvent.BAD_CREDENTIALS,
                error_code="ig-auth-error",
                error_message=error.proper_message,
            )
        self.client = None
        self.mqtt = None
        self.state = None
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
                self.log.warning(
                    "Room creation appears to have failed, "
                    f"dropping message in {evt.message.thread_id}"
                )
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
        date = evt.value.timestamp_ms
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
        await puppet.intent_for(portal).set_typing(
            portal.mxid, is_typing=is_typing, timeout=evt.value.ttl
        )

    # endregion
    # region Database getters

    def _add_to_cache(self) -> None:
        self.by_mxid[self.mxid] = self
        if self.igpk:
            self.by_igpk[self.igpk] = self

    @classmethod
    @async_getter_lock
    async def get_by_mxid(cls, mxid: UserID, *, create: bool = True) -> User | None:
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
    @async_getter_lock
    async def get_by_igpk(cls, igpk: int) -> User | None:
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
    async def all_logged_in(cls) -> AsyncGenerator[User, None]:
        users = await super().all_logged_in()
        user: cls
        for index, user in enumerate(users):
            try:
                yield cls.by_mxid[user.mxid]
            except KeyError:
                user._add_to_cache()
                yield user

    # endregion
