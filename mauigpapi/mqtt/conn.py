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

from typing import Any, Awaitable, Callable, Iterable, Type, TypeVar
from collections import defaultdict
from socket import error as SocketError, socket
import asyncio
import json
import logging
import re
import time
import zlib

from yarl import URL
import paho.mqtt.client as pmc

from mautrix.util.logging import TraceLogger

from ..errors import (
    IrisSubscribeError,
    MQTTConnectionUnauthorized,
    MQTTNotConnected,
    MQTTNotLoggedIn,
    MQTTReconnectionError,
)
from ..proxy import ProxyHandler
from ..state import AndroidState
from ..types import (
    AppPresenceEventPayload,
    ClientConfigUpdatePayload,
    CommandResponse,
    IrisPayload,
    IrisPayloadData,
    LiveVideoCommentPayload,
    MessageSyncEvent,
    MessageSyncMessage,
    Operation,
    PubsubEvent,
    PubsubPayload,
    ReactionStatus,
    ReactionType,
    RealtimeDirectEvent,
    RealtimeZeroProvisionPayload,
    ThreadAction,
    ThreadItemType,
    ThreadRemoveEvent,
    ThreadSyncEvent,
    TypingStatus,
)
from .events import Connect, Disconnect, NewSequenceID, ProxyUpdate
from .otclient import MQTToTClient
from .subscription import GraphQLQueryID, RealtimeTopic, everclear_subscriptions
from .thrift import ForegroundStateConfig, IncomingMessage, RealtimeClientInfo, RealtimeConfig

try:
    import socks
except ImportError:
    socks = None

T = TypeVar("T")

ACTIVITY_INDICATOR_REGEX = re.compile(
    r"/direct_v2/threads/([\w_]+)/activity_indicator_id/([\w_]+)"
)

INBOX_THREAD_REGEX = re.compile(r"/direct_v2/inbox/threads/([\w_]+)")


class AndroidMQTT:
    _loop: asyncio.AbstractEventLoop
    _client: MQTToTClient
    log: TraceLogger
    state: AndroidState
    _graphql_subs: set[str]
    _skywalker_subs: set[str]
    _iris_seq_id: int | None
    _iris_snapshot_at_ms: int | None
    _publish_waiters: dict[int, asyncio.Future]
    _response_waiters: dict[RealtimeTopic, asyncio.Future]
    _response_waiter_locks: dict[RealtimeTopic, asyncio.Lock]
    _message_response_waiter_lock: asyncio.Lock
    _message_response_waiter_id: str | None
    _message_response_waiter: asyncio.Future | None
    _disconnect_error: Exception | None
    _event_handlers: dict[Type[T], list[Callable[[T], Awaitable[None]]]]
    _outgoing_events: asyncio.Queue
    _event_dispatcher_task: asyncio.Task | None

    # region Initialization

    def __init__(
        self,
        state: AndroidState,
        log: TraceLogger | None = None,
        proxy_handler: ProxyHandler | None = None,
    ) -> None:
        self._graphql_subs = set()
        self._skywalker_subs = set()
        self._iris_seq_id = None
        self._iris_snapshot_at_ms = None
        self._publish_waiters = {}
        self._response_waiters = {}
        self._message_response_waiter_lock = asyncio.Lock()
        self._message_response_waiter_id = None
        self._message_response_waiter = None
        self._disconnect_error = None
        self._response_waiter_locks = defaultdict(lambda: asyncio.Lock())
        self._event_handlers = defaultdict(lambda: [])
        self._event_dispatcher_task = None
        self._outgoing_events = asyncio.Queue()
        self.log = log or logging.getLogger("mauigpapi.mqtt")
        self._loop = asyncio.get_running_loop()
        self.state = state
        self._client = MQTToTClient(
            client_id=self._form_client_id(),
            clean_session=True,
            protocol=pmc.MQTTv31,
            transport="tcp",
        )
        self.proxy_handler = proxy_handler
        self.setup_proxy()
        self._client.enable_logger()
        self._client.tls_set()
        # mqtt.max_inflight_messages_set(20)  # The rest will get queued
        # mqtt.max_queued_messages_set(0)  # Unlimited messages can be queued
        # mqtt.message_retry_set(20)  # Retry sending for at least 20 seconds
        # mqtt.reconnect_delay_set(min_delay=1, max_delay=120)
        self._client.connect_async("edge-mqtt.facebook.com", 443, keepalive=60)
        self._client.on_message = self._on_message_handler
        self._client.on_publish = self._on_publish_handler
        self._client.on_connect = self._on_connect_handler
        self._client.on_disconnect = self._on_disconnect_handler
        self._client.on_socket_open = self._on_socket_open
        self._client.on_socket_close = self._on_socket_close
        self._client.on_socket_register_write = self._on_socket_register_write
        self._client.on_socket_unregister_write = self._on_socket_unregister_write

    def setup_proxy(self):
        http_proxy = self.proxy_handler.get_proxy_url() if self.proxy_handler else None
        if http_proxy:
            if not socks:
                self.log.warning("http_proxy is set, but pysocks is not installed")
            else:
                proxy_url = URL(http_proxy)
                proxy_type = {
                    "http": socks.HTTP,
                    "https": socks.HTTP,
                    "socks": socks.SOCKS5,
                    "socks5": socks.SOCKS5,
                    "socks4": socks.SOCKS4,
                }[proxy_url.scheme]
                self._client.proxy_set(
                    proxy_type=proxy_type,
                    proxy_addr=proxy_url.host,
                    proxy_port=proxy_url.port,
                    proxy_username=proxy_url.user,
                    proxy_password=proxy_url.password,
                )

    def _clear_response_waiters(self) -> None:
        for waiter in self._response_waiters.values():
            if not waiter.done():
                waiter.set_exception(
                    MQTTNotConnected("MQTT disconnected before request returned response")
                )
        for waiter in self._publish_waiters.values():
            if not waiter.done():
                waiter.set_exception(
                    MQTTNotConnected("MQTT disconnected before request was published")
                )
        if self._message_response_waiter and not self._message_response_waiter.done():
            self._message_response_waiter.set_exception(
                MQTTNotConnected("MQTT disconnected before message send returned response")
            )
            self._message_response_waiter = None
            self._message_response_waiter_id = None
        self._response_waiters = {}
        self._publish_waiters = {}

    def _form_client_id(self) -> bytes:
        subscribe_topics = [
            RealtimeTopic.PUBSUB,  # 88
            RealtimeTopic.SUB_IRIS_RESPONSE,  # 135
            RealtimeTopic.RS_REQ,  # 244
            RealtimeTopic.REALTIME_SUB,  # 149
            RealtimeTopic.REGION_HINT,  # 150
            RealtimeTopic.RS_RESP,  # 245
            RealtimeTopic.T_RTC_LOG,  # 274
            RealtimeTopic.SEND_MESSAGE_RESPONSE,  # 133
            RealtimeTopic.MESSAGE_SYNC,  # 146
            RealtimeTopic.LIGHTSPEED_RESPONSE,  # 179
            RealtimeTopic.UNKNOWN_PP,  # 34
        ]
        subscribe_topic_ids = [int(topic.encoded) for topic in subscribe_topics]
        password = f"authorization={self.state.session.authorization}"
        cfg = RealtimeConfig(
            client_identifier=self.state.device.phone_id[:20],
            client_info=RealtimeClientInfo(
                user_id=int(self.state.user_id),
                user_agent=self.state.user_agent,
                client_capabilities=0b10110111,
                endpoint_capabilities=0,
                publish_format=1,
                no_automatic_foreground=True,
                make_user_available_in_foreground=False,
                device_id=self.state.device.phone_id,
                is_initially_foreground=False,
                network_type=1,
                network_subtype=-1,
                client_mqtt_session_id=int(time.time() * 1000) & 0xFFFFFFFF,
                subscribe_topics=subscribe_topic_ids,
                client_type="cookie_auth",
                app_id=567067343352427,
                # region_preference=self.state.session.region_hint or "LLA",
                device_secret="",
                client_stack=3,
            ),
            password=password,
            app_specific_info={
                "capabilities": self.state.application.CAPABILITIES,
                "app_version": self.state.application.APP_VERSION,
                "everclear_subscriptions": json.dumps(everclear_subscriptions),
                "User-Agent": self.state.user_agent,
                "Accept-Language": self.state.device.language.replace("_", "-"),
                "platform": "android",
                "ig_mqtt_route": "django",
                "pubsub_msg_type_blacklist": "direct, typing_type",
                "auth_cache_enabled": "1",
            },
        )
        return zlib.compress(cfg.to_thrift(), level=9)

    # endregion

    def _on_socket_open(self, client: MQTToTClient, _: Any, sock: socket) -> None:
        self._loop.add_reader(sock, client.loop_read)

    def _on_socket_close(self, client: MQTToTClient, _: Any, sock: socket) -> None:
        self._loop.remove_reader(sock)

    def _on_socket_register_write(self, client: MQTToTClient, _: Any, sock: socket) -> None:
        self._loop.add_writer(sock, client.loop_write)

    def _on_socket_unregister_write(self, client: MQTToTClient, _: Any, sock: socket) -> None:
        self._loop.remove_writer(sock)

    def _on_connect_handler(
        self, client: MQTToTClient, _: Any, flags: dict[str, Any], rc: int
    ) -> None:
        if rc != 0:
            err = pmc.connack_string(rc)
            self.log.error("MQTT Connection Error: %s (%d)", err, rc)
            if rc == pmc.CONNACK_REFUSED_NOT_AUTHORIZED:
                self._disconnect_error = MQTTConnectionUnauthorized()
                self.disconnect()
            return

        self._loop.create_task(self._post_connect())

    def _on_disconnect_handler(self, client: MQTToTClient, _: Any, rc: int) -> None:
        err_str = "Generic error." if rc == pmc.MQTT_ERR_NOMEM else pmc.error_string(rc)
        self.log.debug(f"MQTT disconnection code %d: %s", rc, err_str)
        self._clear_response_waiters()

    async def _post_connect(self) -> None:
        await self._dispatch(Connect())
        self.log.debug("Re-subscribing to things after connect")
        if self._graphql_subs:
            res = await self.graphql_subscribe(self._graphql_subs)
            self.log.trace("GraphQL subscribe response: %s", res)
        if self._skywalker_subs:
            res = await self.skywalker_subscribe(self._skywalker_subs)
            self.log.trace("Skywalker subscribe response: %s", res)
        if self._iris_seq_id:
            retry = 0
            while True:
                try:
                    await self.iris_subscribe(self._iris_seq_id, self._iris_snapshot_at_ms)
                    break
                except (asyncio.TimeoutError, IrisSubscribeError) as e:
                    self.log.exception("Error requesting iris subscribe")
                    retry += 1
                    if retry >= 5 or isinstance(e, IrisSubscribeError):
                        self._disconnect_error = e
                        self.disconnect()
                        break
                    await asyncio.sleep(5)
                    self.log.debug("Retrying iris subscribe")

    def _on_publish_handler(self, client: MQTToTClient, _: Any, mid: int) -> None:
        try:
            waiter = self._publish_waiters[mid]
        except KeyError:
            self.log.trace(f"Got publish confirmation for {mid}, but no waiters")
            return
        self.log.trace(f"Got publish confirmation for {mid}")
        waiter.set_result(None)

    # region Incoming event parsing

    def _parse_direct_thread_path(self, path: str) -> dict:
        try:
            blank, direct_v2, threads, thread_id, *rest = path.split("/")
        except (ValueError, IndexError) as e:
            self.log.debug(f"Got {e!r} while parsing path {path}")
            raise
        if (blank, direct_v2, threads) != ("", "direct_v2", "threads"):
            self.log.debug(f"Got unexpected first parts in direct thread path {path}")
            raise ValueError("unexpected first three parts in _parse_direct_thread_path")
        additional = {"thread_id": thread_id}
        if rest:
            subitem_key = rest[0]
            if subitem_key == "approval_required_for_new_members":
                additional["approval_required_for_new_members"] = True
            elif subitem_key == "participants" and len(rest) > 2 and rest[2] == "has_seen":
                additional["has_seen"] = int(rest[1])
            elif subitem_key == "items":
                additional["item_id"] = rest[1]
                if len(rest) > 4 and rest[2] == "reactions":
                    additional["reaction_type"] = ReactionType(rest[3])
                    additional["reaction_user_id"] = int(rest[4])
            elif subitem_key in "admin_user_ids":
                additional["admin_user_id"] = int(rest[1])
            elif subitem_key == "activity_indicator_id":
                additional["activity_indicator_id"] = rest[1]
        self.log.trace("Parsed path %s -> %s", path, additional)
        return additional

    def _on_messager_sync_item(self, part: IrisPayloadData, parsed_item: IrisPayload) -> bool:
        if part.path.startswith("/direct_v2/threads/"):
            raw_message = {
                "path": part.path,
                "op": part.op,
                **self._parse_direct_thread_path(part.path),
            }
            try:
                json_value = json.loads(part.value)
                if "reaction_type" in raw_message:
                    self.log.trace("Treating %s as new reaction data", json_value)
                    raw_message["new_reaction"] = json_value
                    json_value["sender_id"] = raw_message.pop("reaction_user_id")
                    json_value["type"] = raw_message.pop("reaction_type")
                    json_value["client_context"] = parsed_item.mutation_token
                    if part.op == Operation.REMOVE:
                        json_value["emoji"] = None
                        json_value["timestamp"] = None
                else:
                    raw_message = {
                        **raw_message,
                        **json_value,
                    }
            except (json.JSONDecodeError, TypeError):
                raw_message["value"] = part.value
            message = MessageSyncMessage.deserialize(raw_message)
            evt = MessageSyncEvent(iris=parsed_item, message=message)
        elif part.path.startswith("/direct_v2/inbox/threads/"):
            if part.op == Operation.REMOVE:
                blank, direct_v2, inbox, threads, thread_id, *_ = part.path.split("/")
                evt = ThreadRemoveEvent.deserialize(
                    {
                        "thread_id": thread_id,
                        "path": part.path,
                        "op": part.op,
                        **json.loads(part.value),
                    }
                )
            else:
                evt = ThreadSyncEvent.deserialize(
                    {
                        "path": part.path,
                        "op": part.op,
                        **json.loads(part.value),
                    }
                )
        else:
            self.log.warning(f"Unsupported path {part.path}")
            return False
        self._outgoing_events.put_nowait(evt)
        return True

    def _on_message_sync(self, payload: bytes) -> None:
        parsed = json.loads(payload.decode("utf-8"))
        self.log.trace("Got message sync event: %s", parsed)
        has_items = False
        for sync_item in parsed:
            parsed_item = IrisPayload.deserialize(sync_item)
            if self._iris_seq_id < parsed_item.seq_id:
                self.log.trace(f"Got new seq_id: {parsed_item.seq_id}")
                self._iris_seq_id = parsed_item.seq_id
                self._iris_snapshot_at_ms = int(time.time() * 1000)
                asyncio.create_task(
                    self._dispatch(NewSequenceID(self._iris_seq_id, self._iris_snapshot_at_ms))
                )
            for part in parsed_item.data:
                has_items = self._on_messager_sync_item(part, parsed_item) or has_items
        if has_items and not self._event_dispatcher_task:
            self._event_dispatcher_task = asyncio.create_task(self._dispatcher_loop())

    def _on_pubsub(self, payload: bytes) -> None:
        parsed_thrift = IncomingMessage.from_thrift(payload)
        self.log.trace(f"Got pubsub event {parsed_thrift.topic} / {parsed_thrift.payload}")
        message = PubsubPayload.parse_json(parsed_thrift.payload)
        for data in message.data:
            match = ACTIVITY_INDICATOR_REGEX.match(data.path)
            if match:
                evt = PubsubEvent(
                    data=data,
                    base=message,
                    thread_id=match.group(1),
                    activity_indicator_id=match.group(2),
                )
                self._loop.create_task(self._dispatch(evt))
            elif not data.double_publish:
                self.log.debug("Pubsub: no activity indicator on data: %s", data)
            else:
                self.log.debug("Pubsub: double publish: %s", data.path)

    def _parse_realtime_sub_item(self, topic: str | GraphQLQueryID, raw: dict) -> Iterable[Any]:
        if topic == GraphQLQueryID.APP_PRESENCE:
            yield AppPresenceEventPayload.deserialize(raw).presence_event
        elif topic == GraphQLQueryID.ZERO_PROVISION:
            yield RealtimeZeroProvisionPayload.deserialize(raw).zero_product_provisioning_event
        elif topic == GraphQLQueryID.CLIENT_CONFIG_UPDATE:
            yield ClientConfigUpdatePayload.deserialize(raw).client_config_update_event
        elif topic == GraphQLQueryID.LIVE_REALTIME_COMMENTS:
            yield LiveVideoCommentPayload.deserialize(raw).live_video_comment_event
        elif topic == "direct":
            event = raw["event"]
            for item in raw["data"]:
                yield RealtimeDirectEvent.deserialize(
                    {
                        "event": event,
                        **self._parse_direct_thread_path(item["path"]),
                        **item,
                    }
                )

    def _on_realtime_sub(self, payload: bytes) -> None:
        parsed_thrift = IncomingMessage.from_thrift(payload)
        try:
            topic = GraphQLQueryID(parsed_thrift.topic)
        except ValueError:
            topic = parsed_thrift.topic
        self.log.trace(f"Got realtime sub event {topic} / {parsed_thrift.payload}")
        allowed = (
            "direct",
            GraphQLQueryID.APP_PRESENCE,
            GraphQLQueryID.ZERO_PROVISION,
            GraphQLQueryID.CLIENT_CONFIG_UPDATE,
            GraphQLQueryID.LIVE_REALTIME_COMMENTS,
        )
        if topic not in allowed:
            return
        parsed_json = json.loads(parsed_thrift.payload)
        for evt in self._parse_realtime_sub_item(topic, parsed_json):
            self._loop.create_task(self._dispatch(evt))

    def _handle_send_response(self, message: pmc.MQTTMessage) -> None:
        data = json.loads(message.payload.decode("utf-8"))
        try:
            ccid = data["payload"]["client_context"]
        except KeyError:
            self.log.warning(
                "Didn't find client_context in send message response: %s", message.payload
            )
            ccid = self._message_response_waiter_id
        else:
            if ccid != self._message_response_waiter_id:
                self.log.error(
                    "Mismatching client_context in send message response (%s != %s)",
                    ccid,
                    self._message_response_waiter_id,
                )
                return
        if self._message_response_waiter and not self._message_response_waiter.done():
            self.log.debug("Got response to %s: %s", ccid, message.payload)
            self._message_response_waiter.set_result(message)
            self._message_response_waiter = None
            self._message_response_waiter_id = None
        else:
            self.log.warning("Didn't find task waiting for response %s", message.payload)

    def _on_message_handler(self, client: MQTToTClient, _: Any, message: pmc.MQTTMessage) -> None:
        try:
            topic = RealtimeTopic.decode(message.topic)
            # Instagram Android MQTT messages are always compressed
            message.payload = zlib.decompress(message.payload)
            if topic == RealtimeTopic.MESSAGE_SYNC:
                self._on_message_sync(message.payload)
            elif topic == RealtimeTopic.PUBSUB:
                self._on_pubsub(message.payload)
            elif topic == RealtimeTopic.REALTIME_SUB:
                self._on_realtime_sub(message.payload)
            elif topic == RealtimeTopic.SEND_MESSAGE_RESPONSE:
                self._handle_send_response(message)
            else:
                try:
                    waiter = self._response_waiters.pop(topic)
                except KeyError:
                    self.log.debug(
                        "No handler for MQTT message in %s: %s", topic.value, message.payload
                    )
                else:
                    self.log.trace("Got response %s: %s", topic.value, message.payload)
                    waiter.set_result(message)
        except Exception:
            self.log.exception("Error in incoming MQTT message handler")
            self.log.trace("Errored MQTT payload: %s", message.payload)

    # endregion

    async def _reconnect(self) -> None:
        try:
            self.log.trace("Trying to reconnect to MQTT")
            self._client.reconnect()
        except (SocketError, OSError, pmc.WebsocketConnectionError) as e:
            raise MQTTReconnectionError("MQTT reconnection failed") from e

    def add_event_handler(
        self, evt_type: Type[T], handler: Callable[[T], Awaitable[None]]
    ) -> None:
        self._event_handlers[evt_type].append(handler)

    async def _dispatch(self, evt: T) -> None:
        for handler in self._event_handlers[type(evt)]:
            try:
                await handler(evt)
            except Exception:
                self.log.exception(f"Error in {type(evt).__name__} handler")

    def disconnect(self) -> None:
        self._client.disconnect()

    async def _dispatcher_loop(self) -> None:
        loop_id = f"{hex(id(self))}#{time.monotonic()}"
        self.log.debug(f"Dispatcher loop {loop_id} starting")
        try:
            while True:
                evt = await self._outgoing_events.get()
                await asyncio.shield(self._dispatch(evt))
        except asyncio.CancelledError:
            tasks = self._outgoing_events
            self._outgoing_events = asyncio.Queue()
            if not tasks.empty():
                self.log.debug(
                    f"Dispatcher loop {loop_id} stopping after dispatching {tasks.qsize()} events"
                )
            while not tasks.empty():
                await self._dispatch(tasks.get_nowait())
            raise
        finally:
            self.log.debug(f"Dispatcher loop {loop_id} stopped")

    async def listen(
        self,
        graphql_subs: set[str] | None = None,
        skywalker_subs: set[str] | None = None,
        seq_id: int = None,
        snapshot_at_ms: int = None,
        retry_limit: int = 5,
    ) -> None:
        self._graphql_subs = graphql_subs or set()
        self._skywalker_subs = skywalker_subs or set()
        self._iris_seq_id = seq_id
        self._iris_snapshot_at_ms = snapshot_at_ms

        self.log.debug("Connecting to Instagram MQTT")
        await self._reconnect()
        connection_retries = 0

        while True:
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                self.disconnect()
                # this might not be necessary
                self._client.loop_misc()
                break
            rc = self._client.loop_misc()

            # If disconnect() has been called
            # Beware, internal API, may have to change this to something more stable!
            if self._client._state == pmc.mqtt_cs_disconnecting:
                break  # Stop listening

            if rc != pmc.MQTT_ERR_SUCCESS:
                # If known/expected error
                if rc == pmc.MQTT_ERR_CONN_LOST:
                    await self._dispatch(Disconnect(reason="Connection lost, retrying"))
                elif rc == pmc.MQTT_ERR_NOMEM:
                    # This error is wrongly classified
                    # See https://github.com/eclipse/paho.mqtt.python/issues/340
                    await self._dispatch(Disconnect(reason="Connection lost, retrying"))
                elif rc == pmc.MQTT_ERR_CONN_REFUSED:
                    raise MQTTNotLoggedIn("MQTT connection refused")
                elif rc == pmc.MQTT_ERR_NO_CONN:
                    if connection_retries > retry_limit:
                        raise MQTTNotConnected(f"Connection failed {connection_retries} times")
                    if self.proxy_handler and self.proxy_handler.update_proxy_url():
                        self.setup_proxy()
                        await self._dispatch(ProxyUpdate())
                    sleep = connection_retries * 2
                    await self._dispatch(
                        Disconnect(
                            reason="MQTT Error: no connection, retrying "
                            f"in {connection_retries} seconds"
                        )
                    )
                    await asyncio.sleep(sleep)
                else:
                    err = pmc.error_string(rc)
                    self.log.error("MQTT Error: %s", err)
                    await self._dispatch(Disconnect(reason=f"MQTT Error: {err}, retrying"))

                await self._reconnect()
                connection_retries += 1
            else:
                connection_retries = 0
        if self._event_dispatcher_task:
            self._event_dispatcher_task.cancel()
            self._event_dispatcher_task = None
        if self._disconnect_error:
            self.log.info("disconnect_error is set, raising and clearing variable")
            err = self._disconnect_error
            self._disconnect_error = None
            raise err

    # region Basic outgoing MQTT

    def publish(self, topic: RealtimeTopic, payload: str | bytes | dict) -> asyncio.Future:
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        self.log.trace(f"Publishing message in {topic.value} ({topic.encoded}): {payload}")
        payload = zlib.compress(payload, level=9)
        info = self._client.publish(topic.encoded, payload, qos=1)
        self.log.trace(f"Published message ID: {info.mid}")
        fut = asyncio.Future()
        self._publish_waiters[info.mid] = fut
        return fut

    async def request(
        self,
        topic: RealtimeTopic,
        response: RealtimeTopic,
        payload: str | bytes | dict,
        timeout: int | None = None,
    ) -> pmc.MQTTMessage:
        async with self._response_waiter_locks[response]:
            fut = asyncio.Future()
            self._response_waiters[response] = fut
            await self.publish(topic, payload)
            self.log.trace(
                f"Request published to {topic.value}, waiting for response {response.name}"
            )
            return await asyncio.wait_for(fut, timeout)

    async def iris_subscribe(self, seq_id: int, snapshot_at_ms: int) -> None:
        self.log.debug(f"Requesting iris subscribe {seq_id}/{snapshot_at_ms}")
        resp = await self.request(
            RealtimeTopic.SUB_IRIS,
            RealtimeTopic.SUB_IRIS_RESPONSE,
            {
                "seq_id": seq_id,
                "snapshot_at_ms": snapshot_at_ms,
                "snapshot_app_version": self.state.application.APP_VERSION,
                "timezone_offset": int(self.state.device.timezone_offset),
                "subscription_type": "message",
            },
            timeout=20,
        )
        self.log.debug("Iris subscribe response: %s", resp.payload.decode("utf-8"))
        resp_dict = json.loads(resp.payload.decode("utf-8"))
        if resp_dict["error_type"] and resp_dict["error_message"]:
            raise IrisSubscribeError(resp_dict["error_type"], resp_dict["error_message"])
        latest_seq_id = resp_dict.get("latest_seq_id")
        if latest_seq_id > self._iris_seq_id:
            self.log.info(f"Latest sequence ID is {latest_seq_id}, catching up from {seq_id}")
            self._iris_seq_id = latest_seq_id
            self._iris_snapshot_at_ms = resp_dict.get("subscribed_at_ms", int(time.time() * 1000))
            asyncio.create_task(
                self._dispatch(NewSequenceID(self._iris_seq_id, self._iris_snapshot_at_ms))
            )

    def graphql_subscribe(self, subs: set[str]) -> asyncio.Future:
        self._graphql_subs |= subs
        return self.publish(RealtimeTopic.REALTIME_SUB, {"sub": list(subs)})

    def graphql_unsubscribe(self, subs: set[str]) -> asyncio.Future:
        self._graphql_subs -= subs
        return self.publish(RealtimeTopic.REALTIME_SUB, {"unsub": list(subs)})

    def skywalker_subscribe(self, subs: set[str]) -> asyncio.Future:
        self._skywalker_subs |= subs
        return self.publish(RealtimeTopic.PUBSUB, {"sub": list(subs)})

    def skywalker_unsubscribe(self, subs: set[str]) -> asyncio.Future:
        self._skywalker_subs -= subs
        return self.publish(RealtimeTopic.PUBSUB, {"unsub": list(subs)})

    # endregion
    # region Actually sending messages and stuff

    async def send_foreground_state(self, state: ForegroundStateConfig) -> None:
        self.log.debug("Updating foreground state: %s", state)
        await self.publish(
            RealtimeTopic.FOREGROUND_STATE, zlib.compress(state.to_thrift(), level=9)
        )
        if state.keep_alive_timeout:
            self._client._keepalive = state.keep_alive_timeout

    async def send_command(
        self,
        thread_id: str,
        action: ThreadAction,
        client_context: str | None = None,
        **kwargs: Any,
    ) -> CommandResponse | None:
        self.log.debug(f"Preparing to send {action} to {thread_id} with {client_context}")
        client_context = client_context or self.state.gen_client_context()
        req = {
            "thread_id": thread_id,
            "client_context": client_context,
            "offline_threading_id": client_context,
            "action": action.value,
            # "device_id": self.state.cookies["ig_did"],
            **kwargs,
        }
        lock_start = time.monotonic()
        async with self._message_response_waiter_lock:
            lock_wait_dur = time.monotonic() - lock_start
            if lock_wait_dur > 1:
                self.log.warning(f"Waited {lock_wait_dur:.3f} seconds to send {client_context}")
            fut = self._message_response_waiter = asyncio.Future()
            self._message_response_waiter_id = client_context
            self.log.debug(f"Publishing {action} to {thread_id} with {client_context}")
            await self.publish(RealtimeTopic.SEND_MESSAGE, req)
            self.log.trace(
                f"Request published to {RealtimeTopic.SEND_MESSAGE}, "
                f"waiting for response {RealtimeTopic.SEND_MESSAGE_RESPONSE}"
            )
            try:
                resp = await asyncio.wait_for(fut, timeout=30000)
            except asyncio.TimeoutError:
                self.log.error(f"Request with ID {client_context} timed out!")
                raise
            return CommandResponse.parse_json(resp.payload.decode("utf-8"))

    def send_item(
        self,
        thread_id: str,
        item_type: ThreadItemType,
        shh_mode: bool = False,
        client_context: str | None = None,
        **kwargs: Any,
    ) -> Awaitable[CommandResponse]:
        return self.send_command(
            thread_id,
            item_type=item_type.value,
            is_shh_mode=str(int(shh_mode)),
            action=ThreadAction.SEND_ITEM,
            client_context=client_context,
            **kwargs,
        )

    def send_hashtag(
        self,
        thread_id: str,
        hashtag: str,
        text: str = "",
        shh_mode: bool = False,
        client_context: str | None = None,
    ) -> Awaitable[CommandResponse]:
        return self.send_item(
            thread_id,
            text=text,
            item_id=hashtag,
            shh_mode=shh_mode,
            item_type=ThreadItemType.HASHTAG,
            client_context=client_context,
        )

    def send_like(
        self, thread_id: str, shh_mode: bool = False, client_context: str | None = None
    ) -> Awaitable[CommandResponse]:
        return self.send_item(
            thread_id,
            shh_mode=shh_mode,
            item_type=ThreadItemType.LIKE,
            client_context=client_context,
        )

    def send_location(
        self,
        thread_id: str,
        venue_id: str,
        text: str = "",
        shh_mode: bool = False,
        client_context: str | None = None,
    ) -> Awaitable[CommandResponse]:
        return self.send_item(
            thread_id,
            text=text,
            item_id=venue_id,
            shh_mode=shh_mode,
            item_type=ThreadItemType.LOCATION,
            client_context=client_context,
        )

    def send_media(
        self,
        thread_id: str,
        media_id: str,
        text: str = "",
        shh_mode: bool = False,
        client_context: str | None = None,
    ) -> Awaitable[CommandResponse]:
        return self.send_item(
            thread_id,
            text=text,
            media_id=media_id,
            shh_mode=shh_mode,
            item_type=ThreadItemType.MEDIA_SHARE,
            client_context=client_context,
        )

    def send_profile(
        self,
        thread_id: str,
        user_id: str,
        text: str = "",
        shh_mode: bool = False,
        client_context: str | None = None,
    ) -> Awaitable[CommandResponse]:
        return self.send_item(
            thread_id,
            text=text,
            item_id=user_id,
            shh_mode=shh_mode,
            item_type=ThreadItemType.PROFILE,
            client_context=client_context,
        )

    def send_reaction(
        self,
        thread_id: str,
        emoji: str,
        item_id: str,
        reaction_status: ReactionStatus = ReactionStatus.CREATED,
        target_item_type: ThreadItemType = ThreadItemType.TEXT,
        shh_mode: bool = False,
        client_context: str | None = None,
    ) -> Awaitable[CommandResponse]:
        return self.send_item(
            thread_id,
            reaction_status=reaction_status.value,
            node_type="item",
            reaction_type="like",
            target_item_type=target_item_type.value,
            emoji=emoji,
            item_id=item_id,
            reaction_action_source="double_tap",
            shh_mode=shh_mode,
            item_type=ThreadItemType.REACTION,
            client_context=client_context,
        )

    def send_user_story(
        self,
        thread_id: str,
        media_id: str,
        text: str = "",
        shh_mode: bool = False,
        client_context: str | None = None,
    ) -> Awaitable[CommandResponse]:
        return self.send_item(
            thread_id,
            text=text,
            item_id=media_id,
            shh_mode=shh_mode,
            item_type=ThreadItemType.REEL_SHARE,
            client_context=client_context,
        )

    def send_text(
        self,
        thread_id: str,
        text: str = "",
        urls: list[str] | None = None,
        shh_mode: bool = False,
        client_context: str | None = None,
        replied_to_item_id: str | None = None,
        replied_to_client_context: str | None = None,
    ) -> Awaitable[CommandResponse]:
        args = {
            "text": text,
        }
        item_type = ThreadItemType.TEXT
        if urls is not None:
            args = {
                "link_text": text,
                "link_urls": json.dumps(urls or []),
            }
            item_type = ThreadItemType.LINK
        return self.send_item(
            thread_id,
            **args,
            shh_mode=shh_mode,
            item_type=item_type,
            client_context=client_context,
            replied_to_item_id=replied_to_item_id,
            replied_to_client_context=replied_to_client_context,
        )

    def mark_seen(
        self, thread_id: str, item_id: str, client_context: str | None = None
    ) -> Awaitable[None]:
        return self.send_command(
            thread_id,
            item_id=item_id,
            action=ThreadAction.MARK_SEEN,
            client_context=client_context,
        )

    def mark_visual_item_seen(
        self, thread_id: str, item_id: str, client_context: str | None = None
    ) -> Awaitable[CommandResponse]:
        return self.send_command(
            thread_id,
            item_id=item_id,
            action=ThreadAction.MARK_VISUAL_ITEM_SEEN,
            client_context=client_context,
        )

    def indicate_activity(
        self,
        thread_id: str,
        activity_status: TypingStatus = TypingStatus.TEXT,
        client_context: str | None = None,
    ) -> Awaitable[CommandResponse]:
        return self.send_command(
            thread_id,
            activity_status=activity_status.value,
            action=ThreadAction.INDICATE_ACTIVITY,
            client_context=client_context,
        )

    # endregion
