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

from typing import TYPE_CHECKING, AsyncGenerator, AsyncIterable, Awaitable, Callable, cast
from datetime import datetime, timedelta
from functools import partial
import asyncio
import logging
import time

from mauigpapi import AndroidAPI, AndroidMQTT, AndroidState
from mauigpapi.errors import (
    IGChallengeError,
    IGCheckpointError,
    IGConsentRequiredError,
    IGNotLoggedInError,
    IGRateLimitError,
    IGUnknownError,
    IGUserIDNotFoundError,
    IrisSubscribeError,
    MQTTConnectionUnauthorized,
    MQTTNotConnected,
    MQTTNotLoggedIn,
    MQTTReconnectionError,
)
from mauigpapi.mqtt import (
    Connect,
    Disconnect,
    GraphQLSubscription,
    NewSequenceID,
    ProxyUpdate,
    SkywalkerSubscription,
)
from mauigpapi.types import (
    ActivityIndicatorData,
    CurrentUser,
    MessageSyncEvent,
    Operation,
    RealtimeDirectEvent,
    Thread,
    ThreadRemoveEvent,
    ThreadSyncEvent,
    TypingStatus,
)
from mauigpapi.types.direct_inbox import DMInbox, DMInboxResponse
from mautrix.appservice import AppService
from mautrix.bridge import BaseUser, async_getter_lock
from mautrix.types import EventID, MessageType, RoomID, TextMessageEventContent, UserID
from mautrix.util import background_task
from mautrix.util.bridge_state import BridgeState, BridgeStateEvent
from mautrix.util.logging import TraceLogger
from mautrix.util.opt_prometheus import Gauge, Summary, async_time
from mautrix.util.proxy import RETRYABLE_PROXY_EXCEPTIONS, ProxyHandler
from mautrix.util.simple_lock import SimpleLock

from . import portal as po, puppet as pu
from .config import Config
from .db import Backfill, Message as DBMessage, Portal as DBPortal, User as DBUser

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
        "ig-refresh-connection-error": "Reconnecting failed again after refresh: {message}",
        "ig-connection-fatal-error": "Instagram disconnected unexpectedly",
        "ig-auth-error": "Authentication error from Instagram: {message}, please login again to continue",
        "ig-checkpoint": "Instagram checkpoint error. Please check the Instagram website.",
        "ig-consent-required": "Instagram requires a consent update. Please check the Instagram website.",
        "ig-checkpoint-locked": "Instagram checkpoint error. Please check the Instagram website.",
        "ig-rate-limit": "Got Instagram ratelimit error, waiting a few minutes before retrying...",
        "ig-disconnected": None,
        "logged-out": "You've been logged out of instagram, please login again to continue",
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
    _sync_lock: SimpleLock
    _backfill_loop_task: asyncio.Task | None
    _thread_sync_task: asyncio.Task | None
    _seq_id_save_task: asyncio.Task | None

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
        seq_id: int | None = None,
        snapshot_at_ms: int | None = None,
        oldest_cursor: str | None = None,
        total_backfilled_portals: int | None = None,
        thread_sync_completed: bool = False,
    ) -> None:
        super().__init__(
            mxid=mxid,
            igpk=igpk,
            state=state,
            notice_room=notice_room,
            seq_id=seq_id,
            snapshot_at_ms=snapshot_at_ms,
            oldest_cursor=oldest_cursor,
            total_backfilled_portals=total_backfilled_portals,
            thread_sync_completed=thread_sync_completed,
        )
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
        self._sync_lock = SimpleLock(
            "Waiting for thread sync to finish before handling %s", log=self.log
        )
        self._listen_task = None
        self._thread_sync_task = None
        self._backfill_loop_task = None
        self.remote_typing_status = None
        self._seq_id_save_task = None

        self.proxy_handler = ProxyHandler(
            api_url=self.config["bridge.get_proxy_api_url"],
        )

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
        while True:
            try:
                await self.connect()
            except RETRYABLE_PROXY_EXCEPTIONS as e:
                # These are retried by the client up to 10 times, but we actually want to retry
                # these indefinitely so we capture them here again and retry.
                self.log.warning(
                    f"Proxy error connecting to Instagram: {e}, retrying in 1 minute",
                )
                await asyncio.sleep(60)
                continue
            except Exception as e:
                self.log.exception("Error while connecting to Instagram")
                await self.push_bridge_state(
                    BridgeStateEvent.UNKNOWN_ERROR, info={"python_error": str(e)}
                )
            return

    @property
    def api_log(self) -> TraceLogger:
        return self.ig_base_log.getChild("http").getChild(self.mxid)

    @property
    def is_connected(self) -> bool:
        return bool(self.client) and bool(self.mqtt) and self._is_connected

    async def ensure_connected(self, max_wait_seconds: int = 5) -> None:
        sleep_interval = 0.1
        max_attempts = max_wait_seconds / sleep_interval
        attempts = 0
        while True:
            if self.is_connected:
                return
            attempts += 1
            if attempts > max_attempts:
                raise Exception("You're not connected to instagram")
            await asyncio.sleep(sleep_interval)

    async def connect(self, user: CurrentUser | None = None) -> None:
        if not self.state:
            await self.push_bridge_state(
                BridgeStateEvent.BAD_CREDENTIALS,
                error="logged-out",
                info={"cnd_action": "reauth"},
            )
            return
        client = AndroidAPI(
            self.state,
            log=self.api_log,
            proxy_handler=self.proxy_handler,
            on_proxy_update=self.on_proxy_update,
        )

        if not user:
            try:
                resp = await client.current_user()
                user = resp.user
            except IGNotLoggedInError as e:
                self.log.warning(f"Failed to connect to Instagram: {e}, logging out")
                await self.logout(error=e)
                return
            except IGCheckpointError as e:
                self.log.debug("Checkpoint error content: %s", e.body)
                raise
            except (IGChallengeError, IGConsentRequiredError) as e:
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
            self.state,
            log=self.ig_base_log.getChild("mqtt").getChild(self.mxid),
            proxy_handler=self.proxy_handler,
        )
        self.mqtt.add_event_handler(Connect, self.on_connect)
        self.mqtt.add_event_handler(Disconnect, self.on_disconnect)
        self.mqtt.add_event_handler(NewSequenceID, self.update_seq_id)
        self.mqtt.add_event_handler(MessageSyncEvent, self.handle_message)
        self.mqtt.add_event_handler(ThreadSyncEvent, self.handle_thread_sync)
        self.mqtt.add_event_handler(ThreadRemoveEvent, self.handle_thread_remove)
        self.mqtt.add_event_handler(RealtimeDirectEvent, self.handle_rtd)
        self.mqtt.add_event_handler(ProxyUpdate, self.on_proxy_update)

        await self.update()

        self.loop.create_task(self._try_sync_puppet(user))
        self.loop.create_task(self._post_connect())

    async def _post_connect(self):
        # Backfill requests are handled synchronously so as not to overload the homeserver.
        # Users can configure their backfill stages to be more or less aggressive with backfilling
        # to try and avoid getting banned.
        if not self._backfill_loop_task or self._backfill_loop_task.done():
            self._backfill_loop_task = asyncio.create_task(self._handle_backfill_requests_loop())

        if not self.seq_id:
            await self._try_sync()
        else:
            self.log.debug("Connecting to MQTT directly as resync_on_startup is false")
            self.start_listen()

        if self.config["bridge.backfill.enable"]:
            if self._thread_sync_task and not self._thread_sync_task.done():
                self.log.warning("Cancelling existing background thread sync task")
                self._thread_sync_task.cancel()
            self._thread_sync_task = asyncio.create_task(self.backfill_threads())

        if self.bridge.homeserver_software.is_hungry:
            self.log.info("Updating contact info for all users")
            asyncio.gather(*[puppet.update_contact_info() async for puppet in pu.Puppet.get_all()])

    async def _handle_backfill_requests_loop(self) -> None:
        if not self.config["bridge.backfill.enable"] or not self.config["bridge.backfill.msc2716"]:
            return

        while True:
            await self._sync_lock.wait("backfill request")
            req = await Backfill.get_next(self.mxid)
            if not req:
                await asyncio.sleep(30)
                continue
            self.log.info("Backfill request %s", req)
            try:
                portal = await po.Portal.get_by_thread_id(
                    req.portal_thread_id, receiver=req.portal_receiver
                )
                await req.mark_dispatched()
                await portal.backfill(self, req)
                await req.mark_done()
            except IGNotLoggedInError as e:
                self.log.exception("User got logged out during backfill loop")
                await self.logout(error=e)
                break
            except (IGChallengeError, IGConsentRequiredError) as e:
                self.log.exception("User got a challenge during backfill loop")
                await self._handle_checkpoint(e, on="backfill")
                break
            except Exception as e:
                self.log.exception("Failed to backfill portal %s: %s", req.portal_thread_id, e)

                # Don't try again to backfill this portal for a minute.
                await req.set_cooldown_timeout(60)
        self._backfill_loop_task = None

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

    async def on_proxy_update(self, evt: ProxyUpdate | None = None) -> None:
        if self.client:
            self.client.setup_http(self.state.cookies.jar)
        if self.mqtt:
            self.mqtt.setup_proxy()

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
        info: dict | None = None,
    ) -> EventID | None:
        if state_event:
            await self.push_bridge_state(
                state_event,
                error=error_code,
                message=error_message if error_code else text,
                info=info,
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
            if puppet.custom_mxid != self.mxid and puppet.can_auto_login(self.mxid):
                self.log.info("Automatically enabling custom puppet")
                await puppet.switch_mxid(access_token="auto", mxid=self.mxid)
        except Exception:
            self.log.exception("Failed to automatically enable custom puppet")
        try:
            await puppet.update_info(user_info, self)
        except Exception:
            self.log.exception("Failed to update own puppet info")

    async def _try_sync(self) -> None:
        try:
            await self.sync()
        except Exception as e:
            self.log.exception("Exception while syncing")
            if isinstance(e, IGCheckpointError):
                self.log.debug("Checkpoint error content: %s", e.body)
            await self.push_bridge_state(
                BridgeStateEvent.UNKNOWN_ERROR, info={"python_error": str(e)}
            )

    async def get_direct_chats(self) -> dict[UserID, list[RoomID]]:
        return {
            pu.Puppet.get_mxid_from_id(portal.other_user_pk): [portal.mxid]
            for portal in await DBPortal.find_private_chats_of(self.igpk)
            if portal.mxid
        }

    async def refresh(self, resync: bool = True, update_proxy: bool = False) -> None:
        self._is_refreshing = True
        try:
            await self.stop_listen()
            self.state.reset_pigeon_session_id()
            if update_proxy and self.proxy_handler.update_proxy_url(reason="reconnect"):
                await self.on_proxy_update()
            if resync:
                retry_count = 0
                minutes = 1
                while True:
                    try:
                        await self.sync()
                        return
                    except Exception as e:
                        if retry_count >= 4 and minutes < 10:
                            minutes += 1
                        retry_count += 1
                        s = "s" if minutes != 1 else ""
                        self.log.exception(
                            f"Error while syncing for refresh, retrying in {minutes} minute{s}"
                        )
                        if isinstance(e, IGCheckpointError):
                            self.log.debug("Checkpoint error content: %s", e.body)
                        await self.push_bridge_state(
                            BridgeStateEvent.UNKNOWN_ERROR,
                            error="unknown-error",
                            message="An unknown error occurred while connecting to Instagram",
                            info={"python_error": str(e)},
                        )
                        await asyncio.sleep(minutes * 60)
            else:
                self.start_listen()
        finally:
            self._is_refreshing = False

    async def _handle_checkpoint(
        self,
        e: IGChallengeError | IGConsentRequiredError,
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

    async def _sync_thread(
        self, thread: Thread, enqueue_backfill: bool = True, portal: po.Portal | None = None
    ) -> bool:
        """
        Sync a specific thread. Returns whether the thread had messages after the last message in
        the database before the sync.
        """
        self.log.debug(f"Syncing thread {thread.thread_id}")

        forward_messages = thread.items

        assert self.client
        if not portal:
            portal = await po.Portal.get_by_thread(thread, self.igpk)
            assert portal
        else:
            assert portal.thread_id == thread.thread_id

        # Create or update the Matrix room
        if not portal.mxid:
            await portal.create_matrix_room(self, thread)
        else:
            await portal.update_matrix_room(self, thread)

        if not self.config["bridge.backfill.enable_initial"]:
            return True

        last_message = await DBMessage.get_last(portal.mxid)
        cursor = thread.oldest_cursor
        if last_message:
            original_number_of_messages = len(thread.items)
            new_messages = [
                m for m in thread.items if last_message.ig_timestamp_ms < m.timestamp_ms
            ]
            forward_messages = new_messages

            portal.log.debug(
                f"{len(new_messages)}/{original_number_of_messages} messages are after most recent"
                " message."
            )

            # Fetch more messages until we get back to messages that have been bridged already.
            while len(new_messages) > 0 and len(new_messages) == original_number_of_messages:
                await asyncio.sleep(self.config["bridge.backfill.incremental.page_delay"])

                portal.log.debug("Fetching more messages for forward backfill")
                resp = await self.client.get_thread(portal.thread_id, cursor=cursor)
                if len(resp.thread.items) == 0:
                    break
                original_number_of_messages = len(resp.thread.items)
                new_messages = [
                    m for m in resp.thread.items if last_message.ig_timestamp_ms < m.timestamp_ms
                ]
                forward_messages = new_messages + forward_messages
                cursor = resp.thread.oldest_cursor
                portal.log.debug(
                    f"{len(new_messages)}/{original_number_of_messages} messages are after most "
                    "recent message."
                )
        elif not portal.first_event_id:
            self.log.debug(
                f"Skipping backfilling {portal.thread_id} as the first event ID is not known"
            )
            return False

        if forward_messages:
            portal.cursor = cursor
            await portal.update()

            mark_read = thread.read_state == 0 or (
                (hours := self.config["bridge.backfill.unread_hours_threshold"]) > 0
                and (
                    datetime.fromtimestamp(forward_messages[0].timestamp_ms / 1000)
                    < datetime.now() - timedelta(hours=hours)
                )
            )
            base_insertion_event_id = await portal.backfill_message_page(
                self,
                list(reversed(forward_messages)),
                forward=True,
                last_message=last_message,
                mark_read=mark_read,
            )
            if (
                not self.bridge.homeserver_software.is_hungry
                and self.config["bridge.backfill.msc2716"]
            ):
                await portal.send_post_backfill_dummy(
                    forward_messages[0].timestamp, base_insertion_event_id=base_insertion_event_id
                )
            if (
                mark_read
                and not self.bridge.homeserver_software.is_hungry
                and (puppet := await self.get_puppet())
            ):
                last_message = await DBMessage.get_last(portal.mxid)
                if last_message:
                    await puppet.intent_for(portal).mark_read(portal.mxid, last_message.mxid)

            await portal._update_read_receipts(thread.last_seen_at)

        if self.config["bridge.backfill.msc2716"] and enqueue_backfill:
            await portal.enqueue_immediate_backfill(self, 1)
        return len(forward_messages) > 0

    async def sync(self, increment_total_backfilled_portals: bool = False) -> None:
        await self.run_with_sync_lock(partial(self._sync, increment_total_backfilled_portals))

    async def _sync(self, increment_total_backfilled_portals: bool = False) -> None:
        if not self._listen_task:
            self.state.reset_pigeon_session_id()
        sleep_minutes = 2
        while True:
            try:
                resp = await self.client.get_inbox()
                break
            except IGNotLoggedInError as e:
                self.log.exception("Got not logged in error while syncing")
                await self.logout(error=e)
                return
            except IGRateLimitError as e:
                self.log.error(
                    "Got ratelimit error while trying to get inbox (%s), retrying in %d minutes",
                    e.body,
                    sleep_minutes,
                )
                await self.push_bridge_state(
                    BridgeStateEvent.TRANSIENT_DISCONNECT, error="ig-rate-limit"
                )
                await asyncio.sleep(sleep_minutes * 60)
                sleep_minutes += 2
            except IGCheckpointError as e:
                self.log.debug("Checkpoint error content: %s", e.body)
                raise
            except (IGChallengeError, IGConsentRequiredError) as e:
                await self._handle_checkpoint(e, on="sync")
                return

        self.seq_id = resp.seq_id
        self.snapshot_at_ms = resp.snapshot_at_ms
        await self.save_seq_id()

        if not self._listen_task:
            self.start_listen(is_after_sync=True)

        sync_count = min(
            self.config["bridge.backfill.max_conversations"],
            self.config["bridge.max_startup_thread_sync_count"],
        )
        self.log.debug(f"Fetching {sync_count} threads, 20 at a time...")

        local_limit: int | None = sync_count
        if sync_count == 0:
            return
        elif sync_count < 0:
            local_limit = None

        await self._sync_threads_with_delay(
            self.client.iter_inbox(
                self._update_seq_id_and_cursor, start_at=resp, local_limit=local_limit
            ),
            stop_when_threads_have_no_messages_to_backfill=True,
            increment_total_backfilled_portals=increment_total_backfilled_portals,
            local_limit=local_limit,
        )

        try:
            await self.update_direct_chats()
        except Exception:
            self.log.exception("Error updating direct chat list")

    async def backfill_threads(self):
        try:
            await self.run_with_sync_lock(self._backfill_threads)
        except Exception:
            self.log.exception("Error in thread backfill loop")

    async def _backfill_threads(self):
        assert self.client
        if not self.config["bridge.backfill.enable"]:
            return

        max_conversations = self.config["bridge.backfill.max_conversations"] or 0
        if 0 <= max_conversations <= (self.total_backfilled_portals or 0):
            self.log.info("Backfill max_conversations count reached, not syncing any more portals")
            return
        elif self.thread_sync_completed:
            self.log.debug("Thread backfill is marked as completed, not syncing more portals")
            return
        local_limit = (
            max_conversations - (self.total_backfilled_portals or 0)
            if max_conversations >= 0
            else None
        )

        start_at = None
        if self.oldest_cursor:
            start_at = DMInboxResponse(
                status="",
                seq_id=self.seq_id,
                snapshot_at_ms=0,
                pending_requests_total=0,
                has_pending_top_requests=False,
                viewer=None,
                inbox=DMInbox(
                    threads=[],
                    has_older=True,
                    unseen_count=0,
                    unseen_count_ts=0,
                    blended_inbox_enabled=False,
                    oldest_cursor=self.oldest_cursor,
                ),
            )
        backoff = self.config.get("bridge.backfill.backoff.thread_list", 300)
        await self._sync_threads_with_delay(
            self.client.iter_inbox(
                self._update_seq_id_and_cursor,
                start_at=start_at,
                local_limit=local_limit,
                rate_limit_exceeded_backoff=backoff,
            ),
            increment_total_backfilled_portals=True,
            local_limit=local_limit,
        )
        await self.update_direct_chats()

    def _update_seq_id_and_cursor(self, seq_id: int, cursor: str | None):
        self.seq_id = seq_id
        if cursor:
            self.oldest_cursor = cursor

    async def _sync_threads_with_delay(
        self,
        threads: AsyncIterable[Thread],
        increment_total_backfilled_portals: bool = False,
        stop_when_threads_have_no_messages_to_backfill: bool = False,
        local_limit: int | None = None,
    ):
        sync_delay = self.config["bridge.backfill.min_sync_thread_delay"]
        last_thread_sync_ts = 0.0
        found_thread_count = 0
        async for thread in threads:
            found_thread_count += 1
            now = time.monotonic()
            if now < last_thread_sync_ts + sync_delay:
                delay = last_thread_sync_ts + sync_delay - now
                self.log.debug("Thread sync is happening too quickly. Waiting for %ds", delay)
                await asyncio.sleep(delay)

            last_thread_sync_ts = time.monotonic()
            had_new_messages = await self._sync_thread(thread)
            if not had_new_messages and stop_when_threads_have_no_messages_to_backfill:
                self.log.debug("Got to threads with no new messages. Stopping sync.")
                return

            if increment_total_backfilled_portals:
                self.total_backfilled_portals = (self.total_backfilled_portals or 0) + 1
            await self.update()
        if local_limit is None or found_thread_count < local_limit:
            if local_limit is None:
                self.log.info(
                    "Reached end of thread list with no limit, marking thread sync as completed"
                )
            else:
                self.log.info(
                    f"Reached end of thread list (got {found_thread_count} with "
                    f"limit {local_limit}), marking thread sync as completed"
                )
            self.thread_sync_completed = True
        await self.update()

    async def run_with_sync_lock(self, func: Callable[[], Awaitable]):
        with self._sync_lock:
            retry_count = 0
            while retry_count < 5:
                try:
                    retry_count += 1
                    await func()

                    # The sync was successful. Exit the loop.
                    return
                except IGNotLoggedInError as e:
                    await self.logout(error=e)
                    return
                except Exception:
                    self.log.exception(
                        "Failed to sync threads. Waiting 30 seconds before retrying sync."
                    )
                    await asyncio.sleep(30)

            # If we get here, it means that the sync has failed five times. If this happens, most
            # likely something very bad has happened.
            self.log.error("Failed to sync threads five times. Will not retry.")

    def start_listen(self, is_after_sync: bool = False) -> None:
        self.shutdown = False
        task = self._listen(
            seq_id=self.seq_id, snapshot_at_ms=self.snapshot_at_ms, is_after_sync=is_after_sync
        )
        self._listen_task = self.loop.create_task(task)

    async def delayed_start_listen(self, sleep: int) -> None:
        await asyncio.sleep(sleep)
        if self.is_connected:
            self.log.debug(
                "Already reconnected before delay after MQTT reconnection error finished"
            )
        else:
            self.log.debug("Reconnecting after MQTT connection error")
            self.start_listen()

    async def fetch_user_and_reconnect(self, sleep_first: int | None = None) -> None:
        if sleep_first:
            await asyncio.sleep(sleep_first)
            if self.is_connected:
                self.log.debug("Canceling user fetch, already reconnected")
                return
        self.log.debug("Refetching current user after disconnection")
        errors = 0
        while True:
            try:
                resp = await self.client.current_user()
            except RETRYABLE_PROXY_EXCEPTIONS as e:
                # These are retried by the client up to 10 times, but we actually want to retry
                # these indefinitely so we capture them here again and retry.
                self.log.warning(
                    f"Proxy error fetching user from Instagram: {e}, retrying in 1 minute",
                )
                await asyncio.sleep(60)
            except IGNotLoggedInError as e:
                self.log.warning(f"Failed to reconnect to Instagram: {e}, logging out")
                await self.logout(error=e)
                return
            except (IGChallengeError, IGConsentRequiredError) as e:
                await self._handle_checkpoint(e, on="reconnect")
                return
            except IGUnknownError as e:
                if "non-JSON body" not in e:
                    raise
                errors += 1
                if errors > 10:
                    raise
                self.log.warning(
                    "Non-JSON body while trying to check user for reconnection, retrying in 10s"
                )
                await asyncio.sleep(10)
            except Exception as e:
                self.log.exception("Error while reconnecting to Instagram")
                if isinstance(e, IGCheckpointError):
                    self.log.debug("Checkpoint error content: %s", e.body)
                await self.push_bridge_state(
                    BridgeStateEvent.UNKNOWN_ERROR, info={"python_error": str(e)}
                )
                return
            else:
                self.log.debug(f"Confirmed current user {resp.user.pk}")
                self.start_listen()
                return

    async def _listen(self, seq_id: int, snapshot_at_ms: int, is_after_sync: bool) -> None:
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
            if is_after_sync:
                self.log.exception("Got IrisSubscribeError right after refresh")
                await self.send_bridge_notice(
                    f"Reconnecting failed again after refresh: {e}",
                    important=True,
                    state_event=BridgeStateEvent.UNKNOWN_ERROR,
                    error_code="ig-refresh-connection-error",
                    error_message=str(e),
                    info={"python_error": str(e)},
                )
            else:
                self.log.warning(f"Got IrisSubscribeError {e}, refreshing...")
                background_task.create(self.refresh())
        except MQTTReconnectionError as e:
            self.log.warning(
                f"Unexpected connection error: {e}, reconnecting in 1 minute", exc_info=True
            )
            await self.send_bridge_notice(
                f"Error in listener: {e}",
                important=True,
                state_event=BridgeStateEvent.TRANSIENT_DISCONNECT,
                error_code="ig-connection-error-socket",
            )
            self.mqtt.disconnect()
            background_task.create(self.delayed_start_listen(sleep=60))
        except (MQTTNotConnected, MQTTNotLoggedIn, MQTTConnectionUnauthorized) as e:
            self.log.warning(f"Unexpected connection error: {e}, checking auth and reconnecting")
            await self.send_bridge_notice(
                f"Error in listener: {e}",
                important=True,
                state_event=BridgeStateEvent.TRANSIENT_DISCONNECT,
                error_code="ig-connection-error-maybe-auth",
            )
            self.mqtt.disconnect()
            background_task.create(self.fetch_user_and_reconnect())
        except Exception as e:
            self.log.exception("Fatal error in listener, reconnecting in 5 minutes")
            await self.send_bridge_notice(
                "Fatal error in listener (see logs for more info)",
                state_event=BridgeStateEvent.UNKNOWN_ERROR,
                important=True,
                error_code="ig-unknown-connection-error",
                info={"python_error": str(e)},
            )
            self.mqtt.disconnect()
            background_task.create(self.fetch_user_and_reconnect(sleep_first=300))
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

    def stop_backfill_tasks(self) -> None:
        if self._backfill_loop_task:
            self._backfill_loop_task.cancel()
            self._backfill_loop_task = None
        if self._thread_sync_task:
            self._thread_sync_task.cancel()
            self._thread_sync_task = None

    async def logout(self, error: IGNotLoggedInError | None = None) -> None:
        await self.stop_listen()
        self.stop_backfill_tasks()
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
                info={"cnd_action": "reauth"},
            )
        self.client = None
        self.mqtt = None
        self.state = None
        self.seq_id = None
        if self._seq_id_save_task and not self._seq_id_save_task.done():
            self._seq_id_save_task.cancel()
            self._seq_id_save_task = None
        self.snapshot_at_ms = None
        self.thread_sync_completed = False
        self._is_logged_in = False
        await self.update()

    # endregion
    # region Event handlers

    async def _save_seq_id_after_sleep(self) -> None:
        await asyncio.sleep(120)
        if self.seq_id is None:
            return
        self._seq_id_save_task = None
        self.log.trace("Saving sequence ID %d/%d", self.seq_id, self.snapshot_at_ms)
        try:
            await self.save_seq_id()
        except Exception:
            self.log.exception("Error saving sequence ID")

    async def update_seq_id(self, evt: NewSequenceID) -> None:
        self.seq_id = evt.seq_id
        self.snapshot_at_ms = evt.snapshot_at_ms
        if not self._seq_id_save_task or self._seq_id_save_task.done():
            self.log.trace("Starting seq id save task (%d/%d)", evt.seq_id, evt.snapshot_at_ms)
            self._seq_id_save_task = asyncio.create_task(self._save_seq_id_after_sleep())
        else:
            self.log.trace("Not starting seq id save task (%d/%d)", evt.seq_id, evt.snapshot_at_ms)

    @async_time(METRIC_MESSAGE)
    async def handle_message(self, evt: MessageSyncEvent) -> None:
        portal = await po.Portal.get_by_thread_id(evt.message.thread_id, receiver=self.igpk)
        if not portal or not portal.mxid:
            self.log.debug(
                "Got message in thread with no portal, getting info and syncing thread..."
            )
            resp = await self.client.get_thread(evt.message.thread_id)
            portal = await po.Portal.get_by_thread(resp.thread, self.igpk)
            await self._sync_thread(resp.thread, enqueue_backfill=False, portal=portal)
            if not portal.mxid:
                self.log.warning(
                    "Room creation appears to have failed, "
                    f"dropping message in {evt.message.thread_id}"
                )
                return
        self.log.trace(f"Received message sync event {evt.message}")
        if evt.message.new_reaction:
            await portal.handle_instagram_reaction(
                evt.message, remove=evt.message.op == Operation.REMOVE
            )
            return
        sender = await pu.Puppet.get_by_pk(evt.message.user_id) if evt.message.user_id else None
        if evt.message.is_thread_image:
            await portal.update_thread_image(self, evt.message.thread_image, sender=sender)
        elif evt.message.op == Operation.ADD:
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
        self.log.trace("Thread sync event content: %s", evt)
        portal = await po.Portal.get_by_thread(evt, receiver=self.igpk)
        if portal.mxid:
            self.log.debug("Got thread sync event for %s with existing portal", portal.thread_id)
        elif evt.is_group:
            self.log.debug(
                "Got thread sync event for group %s without existing portal, creating room",
                portal.thread_id,
            )
        else:
            self.log.debug(
                "Got thread sync event for DM %s without existing portal, ignoring",
                portal.thread_id,
            )
            return
        await self._sync_thread(evt, enqueue_backfill=False, portal=portal)

    async def handle_thread_remove(self, evt: ThreadRemoveEvent) -> None:
        self.log.debug("Got thread remove event: %s", evt.serialize())

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
        await puppet.intent_for(portal).set_typing(portal.mxid, timeout=evt.value.ttl)

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
