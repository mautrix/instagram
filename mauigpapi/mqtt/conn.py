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
import urllib.request
import zlib

from paho.mqtt.client import MQTTMessage, WebsocketConnectionError
from yarl import URL
import paho.mqtt.client

from mautrix.util.logging import TraceLogger

from ..errors import IrisSubscribeError, MQTTNotConnected, MQTTNotLoggedIn
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
    PubsubEvent,
    PubsubPayload,
    ReactionStatus,
    RealtimeDirectEvent,
    RealtimeZeroProvisionPayload,
    ThreadAction,
    ThreadItemType,
    ThreadSyncEvent,
    TypingStatus,
)
from .events import Connect, Disconnect
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
    _message_response_waiters: dict[str, asyncio.Future]
    _disconnect_error: Exception | None
    _event_handlers: dict[Type[T], list[Callable[[T], Awaitable[None]]]]

    # region Initialization

    def __init__(
        self,
        state: AndroidState,
        loop: asyncio.AbstractEventLoop | None = None,
        log: TraceLogger | None = None,
    ) -> None:
        self._graphql_subs = set()
        self._skywalker_subs = set()
        self._iris_seq_id = None
        self._iris_snapshot_at_ms = None
        self._publish_waiters = {}
        self._response_waiters = {}
        self._message_response_waiters = {}
        self._disconnect_error = None
        self._response_waiter_locks = defaultdict(lambda: asyncio.Lock())
        self._event_handlers = defaultdict(lambda: [])
        self.log = log or logging.getLogger("mauigpapi.mqtt")
        self._loop = loop or asyncio.get_event_loop()
        self.state = state
        self._client = MQTToTClient(
            client_id=self._form_client_id(),
            clean_session=True,
            protocol=paho.mqtt.client.MQTTv31,
            transport="tcp",
        )
        try:
            http_proxy = urllib.request.getproxies()["http"]
        except KeyError:
            http_proxy = None
        if http_proxy and socks and URL:
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
        # self._client.on_disconnect = self._on_disconnect_handler
        self._client.on_socket_open = self._on_socket_open
        self._client.on_socket_close = self._on_socket_close
        self._client.on_socket_register_write = self._on_socket_register_write
        self._client.on_socket_unregister_write = self._on_socket_unregister_write

    def _form_client_id(self) -> bytes:
        subscribe_topics = [
            RealtimeTopic.PUBSUB,
            RealtimeTopic.SUB_IRIS_RESPONSE,
            RealtimeTopic.REALTIME_SUB,
            RealtimeTopic.REGION_HINT,
            RealtimeTopic.SEND_MESSAGE_RESPONSE,
            RealtimeTopic.MESSAGE_SYNC,
            RealtimeTopic.UNKNOWN_179,
            RealtimeTopic.UNKNOWN_PP,
        ]
        subscribe_topic_ids = [int(topic.encoded) for topic in subscribe_topics]
        password = f"sessionid={self.state.cookies['sessionid']}"
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
                network_subtype=0,
                client_mqtt_session_id=int(time.time() * 1000) & 0xFFFFFFFF,
                subscribe_topics=subscribe_topic_ids,
                client_type="cookie_auth",
                app_id=567067343352427,
                region_preference=self.state.session.region_hint or "LLA",
                device_secret="",
                client_stack=3,
            ),
            password=password,
            app_specific_info={
                "app_version": self.state.application.APP_VERSION,
                "X-IG-Capabilities": self.state.application.CAPABILITIES,
                "everclear_subscriptions": json.dumps(everclear_subscriptions),
                "User-Agent": self.state.user_agent,
                "Accept-Language": self.state.device.language.replace("_", "-"),
                "platform": "android",
                "ig_mqtt_route": "django",
                "pubsub_msg_type_blacklist": "direct, typing_type",
                "auth_cache_enabled": "0",
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
            err = paho.mqtt.client.connack_string(rc)
            self.log.error("MQTT Connection Error: %s (%d)", err, rc)
            return

        self._loop.create_task(self._post_connect())

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
                    if retry >= 5:
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
                # TODO wtf is this?
                #      it has something to do with reactions
                if len(rest) > 4:
                    additional[rest[2]] = {
                        rest[3]: rest[4],
                    }
            elif subitem_key in "admin_user_ids":
                additional["admin_user_id"] = int(rest[1])
            elif subitem_key == "activity_indicator_id":
                additional["activity_indicator_id"] = rest[1]
        self.log.trace("Parsed path %s -> %s", path, additional)
        return additional

    def _on_messager_sync_item(self, part: IrisPayloadData, parsed_item: IrisPayload) -> None:
        if part.path.startswith("/direct_v2/threads/"):
            raw_message = {
                "path": part.path,
                "op": part.op,
                **self._parse_direct_thread_path(part.path),
            }
            try:
                raw_message = {
                    **raw_message,
                    **json.loads(part.value),
                }
            except (json.JSONDecodeError, TypeError):
                raw_message["value"] = part.value
            message = MessageSyncMessage.deserialize(raw_message)
            evt = MessageSyncEvent(iris=parsed_item, message=message)
        elif part.path.startswith("/direct_v2/inbox/threads/"):
            raw_message = {
                "path": part.path,
                "op": part.op,
                **json.loads(part.value),
            }
            evt = ThreadSyncEvent.deserialize(raw_message)
        else:
            self.log.warning(f"Unsupported path {part.path}")
            return
        self._loop.create_task(self._dispatch(evt))

    def _on_message_sync(self, payload: bytes) -> None:
        parsed = json.loads(payload.decode("utf-8"))
        self.log.trace("Got message sync event: %s", parsed)
        for sync_item in parsed:
            parsed_item = IrisPayload.deserialize(sync_item)
            if self._iris_seq_id < parsed_item.seq_id:
                self.log.trace(f"Got new seq_id: {parsed_item.seq_id}")
                self._iris_seq_id = parsed_item.seq_id
                self._iris_snapshot_at_ms = int(time.time() * 1000)
            for part in parsed_item.data:
                self._on_messager_sync_item(part, parsed_item)

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

    def _on_message_handler(self, client: MQTToTClient, _: Any, message: MQTTMessage) -> None:
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
                try:
                    data = json.loads(message.payload.decode("utf-8"))
                    ccid = data["payload"]["client_context"]
                    waiter = self._message_response_waiters.pop(ccid)
                except KeyError as e:
                    self.log.debug(
                        "No handler (%s) for send message response: %s", e, message.payload
                    )
                else:
                    self.log.trace("Got response to %s: %s", ccid, message.payload)
                    waiter.set_result(message)
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
        except (SocketError, OSError, WebsocketConnectionError) as e:
            # TODO custom class
            raise MQTTNotLoggedIn("MQTT reconnection failed") from e

    def add_event_handler(
        self, evt_type: Type[T], handler: Callable[[T], Awaitable[None]]
    ) -> None:
        self._event_handlers[evt_type].append(handler)

    async def _dispatch(self, evt: T) -> None:
        for handler in self._event_handlers[type(evt)]:
            try:
                await handler(evt)
            except Exception:
                self.log.exception(f"Error in {type(evt)} handler")

    def disconnect(self) -> None:
        self._client.disconnect()

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
            if self._client._state == paho.mqtt.client.mqtt_cs_disconnecting:
                break  # Stop listening

            if rc != paho.mqtt.client.MQTT_ERR_SUCCESS:
                # If known/expected error
                if rc == paho.mqtt.client.MQTT_ERR_CONN_LOST:
                    await self._dispatch(Disconnect(reason="Connection lost, retrying"))
                elif rc == paho.mqtt.client.MQTT_ERR_NOMEM:
                    # This error is wrongly classified
                    # See https://github.com/eclipse/paho.mqtt.python/issues/340
                    await self._dispatch(Disconnect(reason="Connection lost, retrying"))
                elif rc == paho.mqtt.client.MQTT_ERR_CONN_REFUSED:
                    raise MQTTNotLoggedIn("MQTT connection refused")
                elif rc == paho.mqtt.client.MQTT_ERR_NO_CONN:
                    if connection_retries > retry_limit:
                        raise MQTTNotConnected(f"Connection failed {connection_retries} times")
                    sleep = connection_retries * 2
                    await self._dispatch(
                        Disconnect(
                            reason="MQTT Error: no connection, retrying "
                            f"in {connection_retries} seconds"
                        )
                    )
                    await asyncio.sleep(sleep)
                else:
                    err = paho.mqtt.client.error_string(rc)
                    self.log.error("MQTT Error: %s", err)
                    await self._dispatch(Disconnect(reason=f"MQTT Error: {err}, retrying"))

                await self._reconnect()
                connection_retries += 1
            else:
                connection_retries = 0
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
    ) -> MQTTMessage:
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
            {"seq_id": seq_id, "snapshot_at_ms": snapshot_at_ms},
            timeout=20 * 1000,
        )
        self.log.debug("Iris subscribe response: %s", resp.payload.decode("utf-8"))
        resp_dict = json.loads(resp.payload.decode("utf-8"))
        if resp_dict["error_type"] and resp_dict["error_message"]:
            raise IrisSubscribeError(resp_dict["error_type"], resp_dict["error_message"])

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
        client_context = client_context or self.state.gen_client_context()
        req = {
            "thread_id": thread_id,
            "client_context": client_context,
            "offline_threading_id": client_context,
            "action": action.value,
            # "device_id": self.state.cookies["ig_did"],
            **kwargs,
        }
        if action in (ThreadAction.MARK_SEEN,):
            # Some commands don't have client_context in the response, so we can't properly match
            # them to the requests. We probably don't need the data, so just ignore it.
            await self.publish(RealtimeTopic.SEND_MESSAGE, payload=req)
            return None
        else:
            fut = asyncio.Future()
            self._message_response_waiters[client_context] = fut
            await self.publish(RealtimeTopic.SEND_MESSAGE, req)
            self.log.trace(
                f"Request published to {RealtimeTopic.SEND_MESSAGE}, "
                f"waiting for response {RealtimeTopic.SEND_MESSAGE_RESPONSE}"
            )
            resp = await fut
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
