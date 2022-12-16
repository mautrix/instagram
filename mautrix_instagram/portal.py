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

from typing import TYPE_CHECKING, Any, AsyncGenerator, Awaitable, Callable, Optional, Union, cast
from collections import deque
from io import BytesIO
import asyncio
import base64
import hashlib
import html
import json
import mimetypes
import re
import sqlite3
import time

from yarl import URL
import asyncpg
import magic

from mauigpapi.errors import IGRateLimitError
from mauigpapi.types import (
    AnimatedMediaItem,
    CommandResponse,
    ExpiredMediaItem,
    MediaShareItem,
    MediaType,
    MessageSyncMessage,
    Reaction,
    ReactionStatus,
    ReelMediaShareItem,
    ReelShareType,
    RegularMediaItem,
    Thread,
    ThreadImageCandidate,
    ThreadItem,
    ThreadItemType,
    ThreadUser,
    ThreadUserLastSeenAt,
    TypingStatus,
    VoiceMediaItem,
    XMAMediaShareItem,
)
from mautrix.appservice import DOUBLE_PUPPET_SOURCE_KEY, IntentAPI
from mautrix.bridge import BasePortal, async_getter_lock
from mautrix.errors import MatrixError, MForbidden, MNotFound, SessionNotFound
from mautrix.types import (
    AudioInfo,
    BatchID,
    BatchSendEvent,
    BatchSendStateEvent,
    BeeperMessageStatusEventContent,
    ContentURI,
    EventID,
    EventType,
    Format,
    ImageInfo,
    LocationMessageEventContent,
    MediaMessageEventContent,
    Membership,
    MemberStateEventContent,
    MessageEventContent,
    MessageStatus,
    MessageStatusReason,
    MessageType,
    ReactionEventContent,
    RelatesTo,
    RelationType,
    RoomID,
    TextMessageEventContent,
    UserID,
    VideoInfo,
)
from mautrix.util import ffmpeg
from mautrix.util.message_send_checkpoint import MessageSendCheckpointStatus

from . import matrix as m, puppet as p, user as u
from .config import Config
from .db import Backfill, Message as DBMessage, Portal as DBPortal, Reaction as DBReaction

if TYPE_CHECKING:
    from .__main__ import InstagramBridge

try:
    from mautrix.crypto.attachments import decrypt_attachment, encrypt_attachment
except ImportError:
    encrypt_attachment = decrypt_attachment = None

try:
    from PIL import Image
except ImportError:
    Image = None


StateBridge = EventType.find("m.bridge", EventType.Class.STATE)
StateHalfShotBridge = EventType.find("uk.half-shot.bridge", EventType.Class.STATE)
MediaData = Union[
    AnimatedMediaItem,
    ExpiredMediaItem,
    MediaShareItem,
    ReelMediaShareItem,
    RegularMediaItem,
    VoiceMediaItem,
    XMAMediaShareItem,
]
MediaUploadFunc = Callable[["u.User", MediaData, IntentAPI], Awaitable[MediaMessageEventContent]]

PortalCreateDummy = EventType.find("fi.mau.dummy.portal_created", EventType.Class.MESSAGE)
HistorySyncMarkerMessage = EventType.find("org.matrix.msc2716.marker", EventType.Class.MESSAGE)
ConvertedMessage = tuple[EventType, MessageEventContent]

# This doesn't need to capture all valid URLs, it's enough to catch most of them.
# False negatives simply mean the link won't be linkified on Instagram,
# but false positives will cause the message to fail to send.
SIMPLE_URL_REGEX = re.compile(
    r"(?P<url>https?://[\da-z.-]+\.[a-z]{2,}(?:/[^\s]*)?)", flags=re.IGNORECASE
)


class UnsupportedAttachmentError(NotImplementedError):
    pass


class Portal(DBPortal, BasePortal):
    by_mxid: dict[RoomID, Portal] = {}
    by_thread_id: dict[tuple[str, int], Portal] = {}
    config: Config
    matrix: m.MatrixHandler
    private_chat_portal_meta: bool

    _main_intent: IntentAPI | None
    _create_room_lock: asyncio.Lock
    _msgid_dedup: deque[str]
    _reqid_dedup: set[str]

    _last_participant_update: set[int]
    _reaction_lock: asyncio.Lock
    _typing: set[UserID]

    def __init__(
        self,
        thread_id: str,
        receiver: int,
        other_user_pk: int | None,
        mxid: RoomID | None = None,
        name: str | None = None,
        avatar_url: ContentURI | None = None,
        encrypted: bool = False,
        name_set: bool = False,
        avatar_set: bool = False,
        relay_user_id: UserID | None = None,
        first_event_id: EventID | None = None,
        next_batch_id: BatchID | None = None,
        historical_base_insertion_event_id: EventID | None = None,
        cursor: str | None = None,
        thread_image_id: int | None = None,
    ) -> None:
        super().__init__(
            thread_id,
            receiver,
            other_user_pk,
            mxid,
            name,
            avatar_url,
            encrypted,
            name_set,
            avatar_set,
            relay_user_id,
            first_event_id,
            next_batch_id,
            historical_base_insertion_event_id,
            cursor,
            thread_image_id,
        )
        self._create_room_lock = asyncio.Lock()
        self.log = self.log.getChild(thread_id)
        self._msgid_dedup = deque(maxlen=100)
        self._reqid_dedup = set()
        self._last_participant_update = set()

        self._main_intent = None
        self._reaction_lock = asyncio.Lock()
        self._typing = set()
        self._relay_user = None

    @property
    def is_direct(self) -> bool:
        return self.other_user_pk is not None

    @property
    def main_intent(self) -> IntentAPI:
        if not self._main_intent:
            raise ValueError("Portal must be postinit()ed before main_intent can be used")
        return self._main_intent

    @classmethod
    def init_cls(cls, bridge: "InstagramBridge") -> None:
        BasePortal.bridge = bridge
        cls.config = bridge.config
        cls.matrix = bridge.matrix
        cls.az = bridge.az
        cls.loop = bridge.loop
        cls.bridge = bridge
        cls.private_chat_portal_meta = cls.config["bridge.private_chat_portal_meta"]

    # region Misc

    async def _send_delivery_receipt(self, event_id: EventID) -> None:
        if event_id and self.config["bridge.delivery_receipts"]:
            try:
                await self.az.intent.mark_read(self.mxid, event_id)
            except Exception:
                self.log.exception("Failed to send delivery receipt for %s", event_id)

    async def _send_bridge_success(
        self,
        sender: u.User,
        event_id: EventID,
        event_type: EventType,
        msgtype: MessageType | None = None,
    ) -> None:
        sender.send_remote_checkpoint(
            status=MessageSendCheckpointStatus.SUCCESS,
            event_id=event_id,
            room_id=self.mxid,
            event_type=event_type,
            message_type=msgtype,
        )
        asyncio.create_task(self._send_message_status(event_id, err=None))
        await self._send_delivery_receipt(event_id)

    async def _send_bridge_error(
        self,
        sender: u.User,
        err: Exception,
        event_id: EventID,
        event_type: EventType,
        message_type: MessageType | None = None,
        confirmed: bool = False,
    ) -> None:
        sender.send_remote_checkpoint(
            self._status_from_exception(err),
            event_id,
            self.mxid,
            event_type,
            message_type=message_type,
            error=err,
        )

        if self.config["bridge.delivery_error_reports"]:
            event_type_str = {
                EventType.REACTION: "reaction",
                EventType.ROOM_REDACTION: "redaction",
            }.get(event_type, "message")
            error_type = "was not" if confirmed else "may not have been"
            await self._send_message(
                self.main_intent,
                TextMessageEventContent(
                    msgtype=MessageType.NOTICE,
                    body=f"\u26a0 Your {event_type_str} {error_type} bridged: {str(err)}",
                ),
            )
        asyncio.create_task(self._send_message_status(event_id, err))

    async def _send_message_status(self, event_id: EventID, err: Exception | None) -> None:
        if not self.config["bridge.message_status_events"]:
            return
        intent = self.az.intent if self.encrypted else self.main_intent
        status = BeeperMessageStatusEventContent(
            network=self.bridge_info_state_key,
            relates_to=RelatesTo(
                rel_type=RelationType.REFERENCE,
                event_id=event_id,
            ),
        )
        if err:
            status.error = str(err)
            if isinstance(err, NotImplementedError):
                if isinstance(err, UnsupportedAttachmentError):
                    status.message = str(err)
                status.reason = MessageStatusReason.UNSUPPORTED
                status.status = MessageStatus.FAIL
            else:
                status.reason = MessageStatusReason.GENERIC_ERROR
                status.status = MessageStatus.RETRIABLE
        else:
            status.status = MessageStatus.SUCCESS
        status.fill_legacy_booleans()

        await intent.send_message_event(
            room_id=self.mxid,
            event_type=EventType.BEEPER_MESSAGE_STATUS,
            content=status,
        )

    async def _upsert_reaction(
        self,
        existing: DBReaction | None,
        intent: IntentAPI,
        mxid: EventID,
        message: DBMessage,
        sender: u.User | p.Puppet,
        reaction: str,
        mx_timestamp: int,
    ) -> None:
        if existing:
            self.log.debug(
                f"_upsert_reaction redacting {existing.mxid} and inserting {mxid}"
                f" (message: {message.mxid})"
            )
            await intent.redact(existing.mx_room, existing.mxid)
            await existing.edit(
                reaction=reaction, mxid=mxid, mx_room=message.mx_room, mx_timestamp=mx_timestamp
            )
        else:
            self.log.debug(f"_upsert_reaction inserting {mxid} (message: {message.mxid})")
            await DBReaction(
                mxid=mxid,
                mx_room=message.mx_room,
                ig_item_id=message.item_id,
                ig_receiver=self.receiver,
                ig_sender=sender.igpk,
                reaction=reaction,
                mx_timestamp=mx_timestamp,
            ).insert()

    # endregion
    # region Matrix event handling

    @staticmethod
    def _status_from_exception(e: Exception) -> MessageSendCheckpointStatus:
        if isinstance(e, NotImplementedError):
            return MessageSendCheckpointStatus.UNSUPPORTED
        elif isinstance(e, asyncio.TimeoutError):
            return MessageSendCheckpointStatus.TIMEOUT
        return MessageSendCheckpointStatus.PERM_FAILURE

    async def handle_matrix_message(
        self, sender: u.User, message: MessageEventContent, event_id: EventID
    ) -> None:
        try:
            await self._handle_matrix_message(sender, message, event_id)
        except Exception as e:
            self.log.exception(f"Error handling Matrix event {event_id}")
            await self._send_bridge_error(
                sender,
                e,
                event_id,
                EventType.ROOM_MESSAGE,
                message_type=message.msgtype,
                confirmed=True,
            )
        else:
            await self._send_bridge_success(
                sender, event_id, EventType.ROOM_MESSAGE, message.msgtype
            )

    async def _handle_matrix_giphy(
        self,
        sender: u.User,
        event_id: EventID,
        request_id: str,
        giphy_id: str,
    ) -> CommandResponse:
        self.log.trace(f"Broadcasting giphy from {event_id} with request ID {request_id}")
        return await sender.client.broadcast(
            self.thread_id,
            ThreadItemType.ANIMATED_MEDIA,
            client_context=request_id,
            id=giphy_id,
        )

    async def _handle_matrix_image(
        self,
        sender: u.User,
        event_id: EventID,
        request_id: str,
        data: bytes,
        mime_type: str,
        width: int | None = None,
        height: int | None = None,
    ) -> CommandResponse:
        if mime_type != "image/jpeg":
            if Image is None:
                raise UnsupportedAttachmentError(
                    "Instagram does not allow non-JPEG images, and Pillow is not installed, "
                    "so the bridge couldn't convert the image automatically"
                )
            with BytesIO(data) as inp, BytesIO() as out:
                img = Image.open(inp)
                img.convert("RGB").save(out, format="JPEG", quality=80)
                data = out.getvalue()
                mime_type = "image/jpeg"

        self.log.trace(f"Uploading photo from {event_id} (mime: {mime_type})")
        upload_resp = await sender.client.upload_photo(
            data, mime=mime_type, width=width, height=height
        )
        self.log.trace(f"Broadcasting uploaded photo with request ID {request_id}")
        return await sender.client.broadcast(
            self.thread_id,
            ThreadItemType.CONFIGURE_PHOTO,
            client_context=request_id,
            upload_id=upload_resp.upload_id,
            allow_full_aspect_ratio="true",
        )

    async def _handle_matrix_video(
        self,
        sender: u.User,
        event_id: EventID,
        request_id: str,
        data: bytes,
        mime_type: str,
        duration: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> CommandResponse:
        if mime_type != "video/mp4":
            data = await ffmpeg.convert_bytes(
                data,
                output_extension=".mp4",
                output_args=("-c:v", "libx264", "-c:a", "aac"),
                input_mime=mime_type,
            )

        self.log.trace(f"Uploading video from {event_id}")
        _, upload_id = await sender.client.upload_mp4(
            data, duration_ms=duration, width=width, height=height
        )
        self.log.trace(f"Broadcasting uploaded video with request ID {request_id}")
        return await sender.client.broadcast(
            self.thread_id,
            ThreadItemType.CONFIGURE_VIDEO,
            client_context=request_id,
            upload_id=upload_id,
            video_result="",
        )

    async def _handle_matrix_audio(
        self,
        sender: u.User,
        event_id: EventID,
        request_id: str,
        data: bytes,
        mime_type: str,
        waveform: list[int],
        duration: int | None = None,
    ) -> CommandResponse:
        if mime_type != "audio/mp4":
            data = await ffmpeg.convert_bytes(
                data, output_extension=".m4a", output_args=("-c:a", "aac"), input_mime=mime_type
            )

        self.log.trace(f"Uploading audio from {event_id}")
        _, upload_id = await sender.client.upload_mp4(data, audio=True, duration_ms=duration)
        self.log.trace(f"Broadcasting uploaded audio with request ID {request_id}")
        return await sender.client.broadcast(
            self.thread_id,
            ThreadItemType.SHARE_VOICE,
            client_context=request_id,
            upload_id=upload_id,
            waveform=json.dumps([(part or 0) / 1024 for part in waveform], separators=(",", ":")),
            waveform_sampling_frequency_hz="10",
        )

    async def _handle_matrix_message(
        self, orig_sender: u.User, message: MessageEventContent, event_id: EventID
    ) -> None:
        sender, is_relay = await self.get_relay_sender(orig_sender, f"message {event_id}")
        assert sender, "user is not logged in"
        assert sender.is_connected, "You're not connected to Instagram"

        if is_relay:
            await self.apply_relay_message_format(orig_sender, message)

        reply_to = {}
        if message.get_reply_to():
            msg = await DBMessage.get_by_mxid(message.get_reply_to(), self.mxid)
            if msg and msg.client_context:
                reply_to = {
                    "replied_to_item_id": msg.item_id,
                    "replied_to_client_context": msg.client_context,
                }

        request_id = sender.state.gen_client_context()
        self._reqid_dedup.add(request_id)
        self.log.debug(
            f"Handling Matrix message {event_id} from {sender.mxid}/{sender.igpk} "
            f"with request ID {request_id}"
        )

        if message.msgtype == MessageType.NOTICE and not self.config["bridge.bridge_notices"]:
            return

        if message.msgtype in (MessageType.EMOTE, MessageType.TEXT, MessageType.NOTICE):
            text = message.body
            if message.msgtype == MessageType.EMOTE:
                text = f"/me {text}"
            self.log.trace(f"Sending Matrix text from {event_id} with request ID {request_id}")
            urls = SIMPLE_URL_REGEX.findall(text) or None
            if not self.is_direct:
                # Instagram groups don't seem to support sending link previews,
                # and the client_context-based deduplication breaks when trying to send them.
                urls = None
            resp = await sender.mqtt.send_text(
                self.thread_id, text=text, urls=urls, client_context=request_id, **reply_to
            )
        elif message.msgtype.is_media and "fi.mau.instagram.giphy_id" in message:
            resp = await self._handle_matrix_giphy(
                sender, event_id, request_id, message["fi.mau.instagram.giphy_id"]
            )
        elif message.msgtype.is_media:
            if message.file and decrypt_attachment:
                data = await self.main_intent.download_media(message.file.url)
                data = decrypt_attachment(
                    data, message.file.key.key, message.file.hashes.get("sha256"), message.file.iv
                )
            else:
                data = await self.main_intent.download_media(message.url)
            mime_type = message.info.mimetype or magic.from_buffer(data, mime=True)
            if message.msgtype == MessageType.IMAGE:
                resp = await self._handle_matrix_image(
                    sender,
                    event_id,
                    request_id,
                    data,
                    mime_type,
                    width=message.info.width,
                    height=message.info.height,
                )
            elif message.msgtype == MessageType.AUDIO:
                waveform = message.get("org.matrix.msc1767.audio", {}).get("waveform", [0] * 30)
                resp = await self._handle_matrix_audio(
                    sender,
                    event_id,
                    request_id,
                    data,
                    mime_type,
                    waveform,
                    duration=message.info.duration,
                )
            elif message.msgtype == MessageType.VIDEO:
                resp = await self._handle_matrix_video(
                    sender,
                    event_id,
                    request_id,
                    data,
                    mime_type,
                    duration=message.info.duration,
                    width=message.info.width,
                    height=message.info.height,
                )
            else:
                raise UnsupportedAttachmentError(
                    "Non-image/video/audio files are currently not supported"
                )
        else:
            raise NotImplementedError(f"Unknown message type {message.msgtype}")

        self.log.trace(f"Got response to message send {request_id}: {resp}")
        if resp.status != "ok" or not resp.payload:
            self.log.warning(f"Failed to handle {event_id}: {resp}")
            raise Exception(f"Sending message failed: {resp.error_message}")
        else:
            self._msgid_dedup.appendleft(resp.payload.item_id)
            try:
                await DBMessage(
                    mxid=event_id,
                    mx_room=self.mxid,
                    item_id=resp.payload.item_id,
                    client_context=resp.payload.client_context,
                    receiver=self.receiver,
                    sender=sender.igpk,
                    ig_timestamp=int(resp.payload.timestamp),
                ).insert()
            except (asyncpg.UniqueViolationError, sqlite3.IntegrityError) as e:
                self.log.warning(
                    f"Error while persisting {event_id} ({resp.payload.client_context}) "
                    f"-> {resp.payload.item_id}: {e}"
                )
            self._reqid_dedup.remove(request_id)
            self.log.debug(
                f"Handled Matrix message {event_id} ({resp.payload.client_context}) "
                f"-> {resp.payload.item_id}"
            )

    async def handle_matrix_reaction(
        self, sender: u.User, event_id: EventID, reacting_to: EventID, emoji: str, timestamp: int
    ) -> None:
        try:
            await self._handle_matrix_reaction(sender, event_id, reacting_to, emoji, timestamp)
        except Exception as e:
            self.log.exception(f"Error handling Matrix reaction {event_id}")
            await self._send_bridge_error(
                sender,
                e,
                event_id,
                EventType.REACTION,
                confirmed=True,
            )
        else:
            await self._send_bridge_success(sender, event_id, EventType.REACTION)

    async def _handle_matrix_reaction(
        self, sender: u.User, event_id: EventID, reacting_to: EventID, emoji: str, timestamp: int
    ) -> None:
        if not await sender.is_logged_in():
            self.log.debug(f"Ignoring reaction by non-logged-in user {sender.mxid}")
            raise NotImplementedError("User is not logged in")

        message = await DBMessage.get_by_mxid(reacting_to, self.mxid)
        if not message or message.is_internal:
            self.log.debug(f"Ignoring reaction to unknown event {reacting_to}")
            await self.main_intent.redact(self.mxid, event_id, reason="Unknown target message")
            raise NotImplementedError("Unknown target message")

        existing = await DBReaction.get_by_item_id(message.item_id, message.receiver, sender.igpk)
        if existing and existing.reaction == emoji:
            return

        async with self._reaction_lock:
            resp = await sender.mqtt.send_reaction(
                self.thread_id, item_id=message.item_id, emoji=emoji
            )
            if resp.status != "ok":
                if resp.payload and resp.payload.message == "invalid unicode emoji":
                    # Instagram doesn't support this reaction. Notify the user, and redact it
                    # so that it doesn't get confusing.
                    await self.main_intent.redact(self.mxid, event_id, reason="Unsupported emoji")
                    raise NotImplementedError(f"Instagram does not support the {emoji} emoji.")
                raise Exception(f"Unknown response error: {resp}")

            self.log.trace(f"{sender.mxid} reacted to {message.item_id} with {emoji}")
            await self._upsert_reaction(
                existing, self.main_intent, event_id, message, sender, emoji, timestamp
            )

    async def handle_matrix_redaction(
        self, orig_sender: u.User, event_id: EventID, redaction_event_id: EventID
    ) -> None:
        sender = None
        try:
            sender, _ = await self.get_relay_sender(orig_sender, f"redaction {event_id}")
            if not sender:
                raise Exception("User is not logged in")

            await self._handle_matrix_redaction(sender, event_id)
        except Exception as e:
            self.log.exception(f"Error handling Matrix redaction {event_id}")
            await self._send_bridge_error(
                sender or orig_sender,
                e,
                redaction_event_id,
                EventType.ROOM_REDACTION,
                confirmed=True,
            )
        else:
            await self._send_bridge_success(sender, redaction_event_id, EventType.ROOM_REDACTION)

    async def _handle_matrix_redaction(self, sender: u.User, event_id: EventID) -> None:
        if not sender.is_connected:
            raise Exception("You're not connected to Instagram")

        reaction = await DBReaction.get_by_mxid(event_id, self.mxid)
        if reaction:
            try:
                await reaction.delete()
                await sender.mqtt.send_reaction(
                    self.thread_id,
                    item_id=reaction.ig_item_id,
                    reaction_status=ReactionStatus.DELETED,
                    emoji="",
                )
            except Exception as e:
                raise Exception(f"Removing reaction failed: {e}")
            else:
                self.log.trace(f"Removed reaction to {reaction.ig_item_id} after Matrix redaction")
            return

        message = await DBMessage.get_by_mxid(event_id, self.mxid)
        if message and not message.is_internal:
            try:
                await message.delete()
                await sender.client.delete_item(self.thread_id, message.item_id)
                self.log.trace(f"Removed {message} after Matrix redaction")
            except Exception as e:
                raise Exception(f"Removing message failed: {e}")
            else:
                self.log.trace(f"Removed message {message.item_id} after Matrix redaction")
            return

        raise NotImplementedError("No message or reaction found for redaction")

    async def handle_matrix_typing(self, users: set[UserID]) -> None:
        if users == self._typing:
            return
        old_typing = self._typing
        self._typing = users
        await self._handle_matrix_typing(old_typing - users, TypingStatus.OFF)
        await self._handle_matrix_typing(users - old_typing, TypingStatus.TEXT)

    async def _handle_matrix_typing(self, users: set[UserID], status: TypingStatus) -> None:
        for mxid in users:
            user = await u.User.get_by_mxid(mxid, create=False)
            if (
                not user
                or not await user.is_logged_in()
                or user.remote_typing_status == status
                or not user.is_connected
            ):
                continue
            user.remote_typing_status = None
            await user.mqtt.indicate_activity(self.thread_id, status)

    async def handle_matrix_leave(self, user: u.User) -> None:
        if not await user.is_logged_in():
            return
        if self.is_direct:
            self.log.info(f"{user.mxid} left private chat portal with {self.other_user_pk}")
            if user.igpk == self.receiver:
                self.log.info(
                    f"{user.mxid} was the recipient of this portal. Cleaning up and deleting..."
                )
                await self.cleanup_and_delete()
        else:
            self.log.debug(f"{user.mxid} left portal to {self.thread_id}")
            # TODO cleanup if empty

    # endregion
    # region Instagram event handling

    async def _reupload_instagram_media(
        self, source: u.User, media: RegularMediaItem, intent: IntentAPI
    ) -> MediaMessageEventContent:
        if media.media_type == MediaType.IMAGE:
            image = media.best_image
            if not image:
                raise ValueError("Attachment not available: didn't find photo URL")
            url = image.url
            msgtype = MessageType.IMAGE
            info = ImageInfo(height=image.height, width=image.width)
        elif media.media_type == MediaType.VIDEO:
            video = media.best_video
            if not video:
                raise ValueError("Attachment not available: didn't find video URL")
            url = video.url
            msgtype = MessageType.VIDEO
            info = VideoInfo(height=video.height, width=video.width)
        elif media.media_type == MediaType.CAROUSEL:
            raise ValueError(
                "Carousel media is not currently supported, "
                "please view the post on Instagram via the link below"
            )
        else:
            raise ValueError(
                f"Attachment not available: unsupported media type {media.media_type.human_name}"
            )
        return await self._reupload_instagram_file(source, url, msgtype, info, intent)

    async def _reupload_instagram_animated(
        self, source: u.User, media: AnimatedMediaItem, intent: IntentAPI
    ) -> MediaMessageEventContent:
        url = media.images.fixed_height.webp
        info = ImageInfo(
            height=int(media.images.fixed_height.height),
            width=int(media.images.fixed_height.width),
        )
        return await self._reupload_instagram_file(source, url, MessageType.IMAGE, info, intent)

    async def _reupload_instagram_xma(
        self, source: u.User, media: XMAMediaShareItem, intent: IntentAPI
    ) -> MediaMessageEventContent:
        url = media.preview_url
        info = ImageInfo(
            mimetype=media.preview_url_mime_type,
        )
        return await self._reupload_instagram_file(source, url, MessageType.IMAGE, info, intent)

    async def _reupload_instagram_voice(
        self, source: u.User, media: VoiceMediaItem, intent: IntentAPI
    ) -> MediaMessageEventContent:
        async def convert_to_ogg(data, mimetype):
            converted = await ffmpeg.convert_bytes(
                data, ".ogg", output_args=("-c:a", "libopus"), input_mime=mimetype
            )
            return converted, "audio/ogg"

        url = media.media.audio.audio_src
        info = AudioInfo(duration=media.media.audio.duration)
        waveform = [int(p * 1024) for p in media.media.audio.waveform_data]
        content = await self._reupload_instagram_file(
            source, url, MessageType.AUDIO, info, intent, convert_to_ogg
        )
        content["org.matrix.msc1767.audio"] = {
            "duration": media.media.audio.duration,
            "waveform": waveform,
        }
        content["org.matrix.msc3245.voice"] = {}
        return content

    async def _download_instagram_file(
        self, source: u.User, url: str
    ) -> tuple[Optional[bytes], str]:
        async with source.client.raw_http_get(url) as resp:
            try:
                length = int(resp.headers["Content-Length"])
            except KeyError:
                # TODO can the download be short-circuited if there's too much data?
                self.log.warning(
                    "Got file download response with no Content-Length header,"
                    "reading data dangerously"
                )
                length = 0
            if length > self.matrix.media_config.upload_size:
                self.log.debug(
                    f"{url} was too large ({length} > {self.matrix.media_config.upload_size})"
                )
                raise ValueError("Attachment not available: too large")
            data = await resp.read()
            if not data:
                return None, ""
            mimetype = resp.headers["Content-Type"] or magic.from_buffer(data, mime=True)
            return data, mimetype

    async def _reupload_instagram_file(
        self,
        source: u.User,
        url: str,
        msgtype: MessageType | None,
        info: ImageInfo | VideoInfo | AudioInfo,
        intent: IntentAPI,
        convert_fn: Callable[[bytes, str], Awaitable[tuple[bytes, str]]] | None = None,
        allow_encrypt: bool = True,
    ) -> MediaMessageEventContent:
        data, mimetype = await self._download_instagram_file(source, url)
        assert data is not None
        info.mimetype = mimetype

        # Run the conversion function on the data.
        if convert_fn is not None:
            data, info.mimetype = await convert_fn(data, info.mimetype)

        if info.mimetype.startswith("image/") and not info.width and not info.height:
            with BytesIO(data) as inp, Image.open(inp) as img:
                info.width, info.height = img.size
        info.size = len(data)
        extension = {
            "image/webp": ".webp",
            "image/jpeg": ".jpg",
            "video/mp4": ".mp4",
            "audio/mp4": ".m4a",
            "audio/ogg": ".ogg",
        }.get(info.mimetype)
        extension = extension or mimetypes.guess_extension(info.mimetype) or ""
        file_name = f"{msgtype.value[2:]}{extension}" if msgtype else None

        upload_mime_type = info.mimetype
        upload_file_name = file_name
        decryption_info = None
        if allow_encrypt and self.encrypted and encrypt_attachment:
            data, decryption_info = encrypt_attachment(data)
            upload_mime_type = "application/octet-stream"
            upload_file_name = None

        mxc = await intent.upload_media(
            data,
            mime_type=upload_mime_type,
            filename=upload_file_name,
            async_upload=self.config["homeserver.async_media"],
        )

        if decryption_info:
            decryption_info.url = mxc
            mxc = None

        return MediaMessageEventContent(
            body=file_name,
            external_url=url,
            url=mxc,
            file=decryption_info,
            info=info,
            msgtype=msgtype,
        )

    def _get_instagram_media_info(self, item: ThreadItem) -> tuple[MediaUploadFunc, MediaData]:
        # TODO maybe use a dict and item.item_type instead of a ton of ifs
        method = self._reupload_instagram_media
        if (
            item.xma_media_share
            or item.xma_story_share
            or item.xma_reel_share
            or item.xma_reel_mention
            or item.generic_xma
        ):
            media_data = (
                item.xma_media_share
                or item.xma_story_share
                or item.xma_reel_share
                or item.xma_reel_mention
                or item.generic_xma
            )[0]
            method = self._reupload_instagram_xma
        elif item.media:
            media_data = item.media
        elif item.visual_media:
            media_data = item.visual_media.media
        elif item.animated_media:
            media_data = item.animated_media
            method = self._reupload_instagram_animated
        elif item.voice_media:
            media_data = item.voice_media
            method = self._reupload_instagram_voice
        elif item.reel_share:
            media_data = item.reel_share.media
        elif item.story_share:
            media_data = item.story_share.media
        elif item.clip:
            media_data = item.clip.clip
        elif item.felix_share and item.felix_share.video:
            media_data = item.felix_share.video
        elif item.media_share:
            media_data = item.media_share
        elif item.direct_media_share:
            media_data = item.direct_media_share.media
        else:
            self.log.debug(f"Unknown media type in {item}")
            raise ValueError("Attachment not available: unsupported media type")
        if not media_data:
            self.log.debug(f"Didn't get media_data in {item}")
            raise ValueError("Attachment not available: unsupported media type")
        elif isinstance(media_data, ExpiredMediaItem):
            self.log.debug(f"Expired media in item {item}")
            raise ValueError("Attachment not available: media expired")
        return method, media_data

    async def _convert_instagram_media(
        self, source: u.User, intent: IntentAPI, item: ThreadItem
    ) -> ConvertedMessage:
        try:
            reupload_func, media_data = self._get_instagram_media_info(item)
            content = await reupload_func(source, media_data, intent)
        except ValueError as e:
            content = TextMessageEventContent(body=str(e), msgtype=MessageType.NOTICE)
        except Exception:
            self.log.warning("Failed to upload media", exc_info=True)
            content = TextMessageEventContent(
                body="Attachment not available: failed to copy file", msgtype=MessageType.NOTICE
            )

        await self._add_instagram_reply(content, item.replied_to_message)
        return EventType.ROOM_MESSAGE, content

    # TODO this might be unused
    async def _convert_instagram_media_share(
        self, source: u.User, intent: IntentAPI, item: ThreadItem
    ) -> list[ConvertedMessage]:
        item_type_name = None
        if item.media_share:
            share_item = item.media_share
        elif item.clip:
            share_item = item.clip.clip
            item_type_name = "clip"
        elif item.felix_share and item.felix_share.video:
            share_item = item.felix_share.video
        elif item.story_share:
            share_item = item.story_share.media
            item_type_name = "story"
        elif item.direct_media_share:
            share_item = item.direct_media_share.media
        else:
            self.log.debug("No media share to bridge")
            return []
        item_type_name = item_type_name or share_item.media_type.human_name
        user_text = f"@{share_item.user.username}"
        user_link = (
            f'<a href="https://www.instagram.com/{share_item.user.username}/">{user_text}</a>'
        )
        prefix = TextMessageEventContent(
            msgtype=MessageType.NOTICE,
            format=Format.HTML,
            body=f"Sent {user_text}'s {item_type_name}",
            formatted_body=f"Sent {user_link}'s {item_type_name}",
        )
        if item.direct_media_share and item.direct_media_share.media_share_type == "tag":
            tagged_user_id = item.direct_media_share.tagged_user_id
            if tagged_user_id == source.igpk and share_item.user.pk == self.other_user_pk:
                prefix.body = prefix.formatted_body = "Tagged you in their post"
            elif share_item.user.pk == source.igpk and tagged_user_id == self.other_user_pk:
                prefix.body = prefix.formatted_body = "Tagged them in your post"

        _, content = await self._convert_instagram_media(source, intent, item)

        external_url = f"https://www.instagram.com/p/{share_item.code}/"
        if share_item.caption:
            caption_body = (
                f"> {share_item.caption.user.username}: {share_item.caption.text}\n\n"
                f"{external_url}"
            )
            caption_formatted_body = (
                f"<blockquote><strong>{share_item.caption.user.username}</strong>"
                f" {html.escape(share_item.caption.text)}</blockquote>"
                f'<a href="{external_url}">instagram.com/p/{share_item.code}</a>'
            )
        else:
            caption_body = external_url
            caption_formatted_body = (
                f'<a href="{external_url}">instagram.com/p/{share_item.code}</a>'
            )
        caption = TextMessageEventContent(
            msgtype=MessageType.TEXT,
            body=caption_body,
            formatted_body=caption_formatted_body,
            format=Format.HTML,
            external_url=external_url,
        )

        if self.bridge.config["bridge.caption_in_message"]:
            if isinstance(content, TextMessageEventContent):
                content.ensure_has_html()
                prefix.ensure_has_html()
                caption.ensure_has_html()
                combined = TextMessageEventContent(
                    msgtype=MessageType.TEXT,
                    body="\n".join((content.body, prefix.body, caption.body)),
                    formatted_body=(
                        f"<p><b>{content.formatted_body}</b></p>"
                        f"<p><i>{prefix.formatted_body}</p>"
                        f"<p>{caption.formatted_body}</p>"
                    ),
                    format=Format.HTML,
                    external_url=external_url,
                )
            else:
                prefix.ensure_has_html()
                caption.ensure_has_html()
                combined_body = "\n".join((prefix.body, caption.body))
                combined_formatted_body = (
                    f"<p><i>{prefix.formatted_body}</i></p><p>{caption.formatted_body}</p>"
                )

                combined = content
                combined["filename"] = content.body
                combined.body = combined_body
                combined["format"] = str(Format.HTML)
                combined["org.matrix.msc1767.caption"] = {
                    "org.matrix.msc1767.text": combined_body,
                    "org.matrix.msc1767.html": combined_formatted_body,
                }
                combined["formatted_body"] = combined_formatted_body

            return [(EventType.ROOM_MESSAGE, combined)]
        else:
            return [
                (EventType.ROOM_MESSAGE, prefix),
                (EventType.ROOM_MESSAGE, content),
                (EventType.ROOM_MESSAGE, caption),
            ]

    async def _convert_instagram_xma_media_share(
        self, source: u.User, intent: IntentAPI, item: ThreadItem
    ) -> list[ConvertedMessage]:
        # N.B. _get_instagram_media_info also only supports downloading the first xma item
        xma_list = (
            item.xma_media_share
            or item.xma_story_share
            or item.xma_reel_share
            or item.xma_reel_mention
            or item.generic_xma
        )
        media = xma_list[0]
        if len(xma_list) != 1:
            self.log.warning(f"Item {item.item_id} has multiple xma media share parts")
        if media.xma_layout_type not in (0, 4):
            self.log.warning(f"Unrecognized xma layout type {media.xma_layout_type}")
        _, content = await self._convert_instagram_media(source, intent, item)

        # Post shares (layout type 0): media title text
        # Reel shares/replies/reactions (layout type 4): item text
        caption_text = media.title_text or item.text or ""
        if media.subtitle_text:
            caption_text = (
                f"{caption_text}\n{media.subtitle_text}" if caption_text else media.subtitle_text
            )
        if media.target_url:
            caption_body = (
                f"> {caption_text}\n\n{media.target_url}" if caption_text else media.target_url
            )
        else:
            caption_body = f"> {caption_text}"
        escaped_caption_text = html.escape(caption_text).replace("\n", "<br>")
        escaped_header_text = html.escape(media.header_title_text or "")
        # For post shares, the media title starts with the username, which is also the header.
        # That part should be bolded.
        if (
            escaped_header_text
            and escaped_caption_text
            and escaped_caption_text.startswith(escaped_header_text)
        ):
            escaped_caption_text = (
                f"<strong>{escaped_header_text}</strong>"
                f"{escaped_caption_text[len(escaped_header_text):]}"
            )
        if item.message_item_type == "animated_media":
            anim = await self._reupload_instagram_file(
                source,
                url=item.animated_media.images.fixed_height.webp,
                msgtype=MessageType.IMAGE,
                info=ImageInfo(
                    width=int(item.animated_media.images.fixed_height.width),
                    height=int(item.animated_media.images.fixed_height.height),
                ),
                intent=intent,
            )
            inline_img = (
                f'<img src="{anim.url}" width={anim.info.width} height={anim.info.height}/>'
            )
            escaped_caption_text = (
                f"{escaped_caption_text}<br/>{inline_img}" if escaped_caption_text else inline_img
            )
        caption_formatted_body = (
            f"<blockquote>{escaped_caption_text}</blockquote>" if escaped_caption_text else ""
        )
        if media.target_url:
            target_url_pretty = str(URL(media.target_url).with_query(None)).replace(
                "https://www.", ""
            )
            caption_formatted_body += (
                f'<p><a href="{media.target_url}">{target_url_pretty}</a></p>'
            )
        # Add auxiliary text as prefix for caption
        if item.auxiliary_text:
            caption_formatted_body = (
                f"<p>{html.escape(item.auxiliary_text)}</p>{caption_formatted_body}"
            )
            caption_body = f"{item.auxiliary_text}\n\n{caption_body}"
        caption = TextMessageEventContent(
            msgtype=MessageType.TEXT,
            body=caption_body,
            formatted_body=caption_formatted_body,
            format=Format.HTML,
        )
        if media.target_url:
            content.external_url = media.target_url
            caption.external_url = media.target_url

        if self.bridge.config["bridge.caption_in_message"]:
            if isinstance(content, TextMessageEventContent):
                content.ensure_has_html()
                caption.ensure_has_html()
                content.body += f"\n\n{caption.body}"
                content.formatted_body = (
                    f"<p><b>{content.formatted_body}</b></p>{caption.formatted_body}"
                )
            else:
                content["filename"] = content.body
                content.body = caption.body
                content["format"] = str(Format.HTML)
                content["formatted_body"] = caption.formatted_body
                content["org.matrix.msc1767.caption"] = {
                    "org.matrix.msc1767.text": content.body,
                    "org.matrix.msc1767.html": content["formatted_body"],
                }

            return [(EventType.ROOM_MESSAGE, content)]
        else:
            return [(EventType.ROOM_MESSAGE, content), (EventType.ROOM_MESSAGE, caption)]

    # TODO this is probably unused
    async def _convert_instagram_reel_share(
        self, source: u.User, intent: IntentAPI, item: ThreadItem
    ) -> list[ConvertedMessage]:
        assert item.reel_share
        media = item.reel_share.media
        prefix_html = None
        if item.reel_share.type == ReelShareType.REPLY:
            if item.reel_share.reel_owner_id == source.igpk:
                prefix = "Replied to your story"
            else:
                username = media.user.username
                prefix = f"Sent @{username}'s story"
                user_link = f'<a href="https://www.instagram.com/{username}/">@{username}</a>'
                prefix_html = f"Sent {user_link}'s story"
        elif item.reel_share.type == ReelShareType.REACTION:
            if item.reel_share.reel_owner_id == source.igpk:
                prefix = "Reacted to your story"
            elif item.user_id == source.igpk:
                prefix = "You reacted to their story"
            else:
                prefix = "Reacted to a story"
        elif item.reel_share.type == ReelShareType.MENTION:
            if item.reel_share.mentioned_user_id == source.igpk:
                prefix = "Mentioned you in their story"
            else:
                prefix = "You mentioned them in your story"
        else:
            self.log.debug(f"Unsupported reel share type {item.reel_share.type}")
            return []
        prefix_content = TextMessageEventContent(msgtype=MessageType.NOTICE, body=prefix)
        if prefix_html:
            prefix_content.format = Format.HTML
            prefix_content.formatted_body = prefix_html
        caption_content = TextMessageEventContent(
            msgtype=MessageType.TEXT, body=item.reel_share.text
        )
        if not caption_content.body and isinstance(media, MediaShareItem):
            caption_content.body = media.caption.text if media.caption else ""
        if not caption_content.body:
            caption_content.body = "<no caption>"

        media_content = None
        fake_item_id = f"fi.mau.instagram.reel_share.{item.user_id}.{media.pk}"
        if isinstance(media, ExpiredMediaItem):
            media_content = TextMessageEventContent(
                msgtype=MessageType.NOTICE, body="Story expired"
            )
        else:
            existing = await DBMessage.get_by_item_id(fake_item_id, self.receiver)
            if existing:
                # If the user already reacted or replied to the same reel share item,
                # use a Matrix reply instead of reposting the image.
                caption_content.set_reply(existing.mxid)
            else:
                _, media_content = await self._convert_instagram_media(source, intent, item)

        if self.bridge.config["bridge.caption_in_message"]:
            if media_content:
                if isinstance(media_content, TextMessageEventContent):
                    media_content.ensure_has_html()
                    prefix_content.ensure_has_html()
                    caption_content.ensure_has_html()
                    combined = TextMessageEventContent(
                        msgtype=MessageType.TEXT,
                        body="\n".join(
                            (media_content.body, prefix_content.body, caption_content.body)
                        ),
                        formatted_body=(
                            f"<p><b>{media_content.formatted_body}</b></p>"
                            f"<p><i>{prefix_content.formatted_body}</i></p>"
                            f"<p>{caption_content.formatted_body}</p>"
                        ),
                        format=Format.HTML,
                    )
                else:
                    prefix_content.ensure_has_html()
                    caption_content.ensure_has_html()
                    combined_body = "\n".join((prefix_content.body, caption_content.body))
                    combined_formatted_body = (
                        f"<p><i>{prefix_content.formatted_body}</i></p>"
                        f"<p>{caption_content.formatted_body}</p>"
                    )

                    combined = media_content
                    combined["filename"] = combined.body
                    combined.body = combined_body
                    combined["format"] = str(Format.HTML)
                    combined["org.matrix.msc1767.caption"] = {
                        "org.matrix.msc1767.text": combined_body,
                        "org.matrix.msc1767.html": combined_formatted_body,
                    }
                    combined["formatted_body"] = combined_formatted_body
            else:
                combined = caption_content

            return [(EventType.ROOM_MESSAGE, combined)]
        else:
            await self._send_message(intent, prefix_content, timestamp=item.timestamp_ms)
            converted: list[ConvertedMessage] = []
            if media_content:
                converted.append((EventType.ROOM_MESSAGE, media_content))
            converted.append((EventType.ROOM_MESSAGE, caption_content))
            return converted

    async def _convert_instagram_link(
        self,
        source: u.User,
        intent: IntentAPI,
        item: ThreadItem,
    ) -> ConvertedMessage:
        content = TextMessageEventContent(msgtype=MessageType.TEXT, body=item.link.text)
        link = item.link.link_context
        preview = {
            "og:url": link.link_url,
            "og:title": link.link_title,
            "og:description": link.link_summary,
        }
        if link.link_image_url:
            reuploaded = await self._reupload_instagram_file(
                source, link.link_image_url, msgtype=None, info=ImageInfo(), intent=intent
            )
            preview["og:image"] = reuploaded.url
            preview["og:image:type"] = reuploaded.info.mimetype
            preview["og:image:width"] = reuploaded.info.width
            preview["og:image:height"] = reuploaded.info.height
            preview["matrix:image:size"] = reuploaded.info.size
            if reuploaded.file:
                preview["beeper:image:encryption"] = reuploaded.file.serialize()
        preview = {k: v for k, v in preview.items() if v}
        content["com.beeper.linkpreviews"] = [preview] if "og:title" in preview else []
        await self._add_instagram_reply(content, item.replied_to_message)
        return EventType.ROOM_MESSAGE, content

    async def _convert_expired_placeholder(
        self, source: u.User, item: ThreadItem, action: str
    ) -> ConvertedMessage:
        if item.user_id == source.igpk:
            prefix = f"{action} your story"
        elif item.user_id == source.igpk:
            prefix = f"You {action.lower()} their story"
        else:
            prefix = f"{action} a story"
        body = f"{prefix}\n\nNo longer available"
        html = f"<p>{prefix}</p><p><i>No longer available</i></p>"
        content = TextMessageEventContent(
            msgtype=MessageType.NOTICE, body=body, format=Format.HTML, formatted_body=html
        )
        return EventType.ROOM_MESSAGE, content

    async def _convert_instagram_text(self, item: ThreadItem, text: str) -> ConvertedMessage:
        content = TextMessageEventContent(msgtype=MessageType.TEXT, body=text)
        content["com.beeper.linkpreviews"] = []
        await self._add_instagram_reply(content, item.replied_to_message)
        return EventType.ROOM_MESSAGE, content

    async def _convert_instagram_unhandled(self, item: ThreadItem) -> ConvertedMessage:
        content = TextMessageEventContent(
            msgtype=MessageType.NOTICE, body=f"Unsupported message type {item.item_type.value}"
        )
        await self._add_instagram_reply(content, item.replied_to_message)
        return EventType.ROOM_MESSAGE, content

    async def _convert_instagram_location(self, item: ThreadItem) -> ConvertedMessage | None:
        loc = item.location
        if not loc or not loc.lng or not loc.lat:
            # TODO handle somehow
            return None
        long_char = "E" if loc.lng > 0 else "W"
        lat_char = "N" if loc.lat > 0 else "S"

        body = (
            f"{loc.name} - {round(abs(loc.lat), 4)}° {lat_char}, "
            f"{round(abs(loc.lng), 4)}° {long_char}"
        )
        url = f"https://www.openstreetmap.org/#map=15/{loc.lat}/{loc.lng}"

        external_url = None
        if loc.external_source == "facebook_places":
            external_url = f"https://www.facebook.com/{loc.short_name}-{loc.facebook_places_id}"

        content = LocationMessageEventContent(
            msgtype=MessageType.LOCATION,
            geo_uri=f"geo:{loc.lat},{loc.lng}",
            body=f"Location: {body}\n{url}",
            external_url=external_url,
        )
        content["format"] = str(Format.HTML)
        content["formatted_body"] = f"Location: <a href='{url}'>{body}</a>"

        await self._add_instagram_reply(content, item.replied_to_message)
        return EventType.ROOM_MESSAGE, content

    async def _convert_instagram_profile(self, item: ThreadItem) -> ConvertedMessage:
        username = item.profile.username
        user_link = f'<a href="https://www.instagram.com/{username}/">@{username}</a>'
        text = f"Shared @{username}'s profile"
        html = f"Shared {user_link}'s profile"
        content = TextMessageEventContent(
            msgtype=MessageType.TEXT, format=Format.HTML, body=text, formatted_body=html
        )
        await self._add_instagram_reply(content, item.replied_to_message)
        return EventType.ROOM_MESSAGE, content

    async def _add_instagram_reply(
        self, content: MessageEventContent, reply_to: ThreadItem | None
    ) -> None:
        if not reply_to:
            return

        message = await DBMessage.get_by_item_id(reply_to.item_id, self.receiver)
        if not message:
            return

        content.set_reply(message.mxid)
        if not isinstance(content, TextMessageEventContent):
            return

        try:
            evt = await self.main_intent.get_event(message.mx_room, message.mxid)
        except (MNotFound, MForbidden):
            evt = None
        if not evt:
            return

        if evt.type == EventType.ROOM_ENCRYPTED:
            try:
                evt = await self.matrix.e2ee.decrypt(evt, wait_session_timeout=0)
            except SessionNotFound:
                return

        if isinstance(evt.content, TextMessageEventContent):
            evt.content.trim_reply_fallback()

        content.set_reply(evt)

    async def handle_instagram_item(
        self, source: u.User, sender: p.Puppet, item: MessageSyncMessage
    ):
        client_context = item.client_context
        link_client_context = item.link.client_context if item.link else None
        cc = client_context
        if link_client_context:
            if not client_context:
                cc = f"link:{link_client_context}"
            elif client_context != link_client_context:
                cc = f"{client_context}/link:{link_client_context}"
        if client_context and client_context in self._reqid_dedup:
            self.log.debug(
                f"Ignoring message {item.item_id} ({cc}) by {item.user_id}"
                " as it was sent by us (client_context in dedup queue)"
            )
            return []
        elif link_client_context and link_client_context in self._reqid_dedup:
            self.log.debug(
                f"Ignoring message {item.item_id} ({cc}) by {item.user_id}"
                " as it was sent by us (link.client_context in dedup queue)"
            )
            return []

        # Check in-memory queues for duplicates
        if item.item_id in self._msgid_dedup:
            self.log.debug(
                f"Ignoring message {item.item_id} ({item.client_context}) by {item.user_id}"
                " as it was already handled (message.id in dedup queue)"
            )
            return
        self._msgid_dedup.appendleft(item.item_id)

        # Check database for duplicates
        if await DBMessage.get_by_item_id(item.item_id, self.receiver) is not None:
            self.log.debug(
                f"Ignoring message {item.item_id} ({item.client_context}) by {item.user_id}"
                " as it was already handled (message.id in database)"
            )
            return

        self.log.debug(
            f"Handling Instagram message {item.item_id} ({item.client_context}) by {item.user_id}"
        )
        if not self.mxid:
            thread = await source.client.get_thread(item.thread_id)
            mxid = await self.create_matrix_room(source, thread.thread)
            if not mxid:
                # Failed to create
                return

            if self.config["bridge.backfill.enable"]:
                if self.config["bridge.backfill.msc2716"]:
                    await self.enqueue_immediate_backfill(source, 0)

        intent = sender.intent_for(self)
        asyncio.create_task(intent.set_typing(self.mxid, is_typing=False))
        event_ids = []
        for event_type, content in await self.convert_instagram_item(source, sender, item):
            event_ids.append(
                await self._send_message(
                    intent, content, event_type=event_type, timestamp=item.timestamp_ms
                )
            )
        event_ids = [event_id for event_id in event_ids if event_id]
        if not event_ids:
            self.log.warning(f"Unhandled Instagram message {item.item_id}")
            return
        self.log.debug(f"Handled Instagram message {item.item_id} -> {event_ids}")
        await DBMessage(
            mxid=event_ids[-1],
            mx_room=self.mxid,
            item_id=item.item_id,
            client_context=item.client_context,
            receiver=self.receiver,
            sender=sender.igpk,
            ig_timestamp=item.timestamp,
        ).insert()
        await self._send_delivery_receipt(event_ids[-1])

    async def convert_instagram_item(
        self, source: u.User, sender: p.Puppet, item: ThreadItem
    ) -> list[ConvertedMessage]:
        if not isinstance(item, ThreadItem):
            # Parsing these items failed, they should have been logged already
            return []

        try:
            return await self._convert_instagram_item(source, sender, item)
        except Exception:
            self.log.exception("Fatal error converting Instagram item")
            self.log.trace("Item content: %s", item.serialize())
            return []

    async def _convert_instagram_item(
        self, source: u.User, sender: p.Puppet, item: ThreadItem
    ) -> list[ConvertedMessage]:
        intent = sender.intent_for(self)
        if (
            item.xma_media_share
            or item.xma_reel_share
            or item.xma_reel_mention
            or item.xma_story_share
            or item.generic_xma
        ):
            return await self._convert_instagram_xma_media_share(source, intent, item)

        converted: list[ConvertedMessage] = []
        handle_text = True

        if item.media or item.animated_media or item.voice_media or item.visual_media:
            converted.append(await self._convert_instagram_media(source, intent, item))
        elif item.location:
            if loc_content := await self._convert_instagram_location(item):
                converted.append(loc_content)
        elif item.profile:
            converted.append(await self._convert_instagram_profile(item))
        elif item.reel_share:
            converted.extend(await self._convert_instagram_reel_share(source, intent, item))
        elif (
            item.media_share
            or item.direct_media_share
            or item.story_share
            or item.clip
            or item.felix_share
        ):
            converted.extend(await self._convert_instagram_media_share(source, intent, item))
        elif item.item_type == ThreadItemType.EXPIRED_PLACEHOLDER:
            if item.message_item_type == "reaction":
                action = "Reacted to"
            else:
                action = "Shared"
            msg_type, expired = await self._convert_expired_placeholder(source, item, action)
            if self.bridge.config["bridge.caption_in_message"] and item.text:
                _, text = await self._convert_instagram_text(item, item.text)
                expired.ensure_has_html()
                text.ensure_has_html()
                combined = TextMessageEventContent(
                    msgtype=MessageType.TEXT,
                    body="\n".join((expired.body, text.body)),
                    formatted_body=f"{expired.formatted_body}<p>{text.formatted_body}</p>",
                    format=Format.HTML,
                )
                handle_text = False
                converted.append((msg_type, combined))
            else:
                converted.append((msg_type, expired))
        elif item.action_log:
            # These probably don't need to be bridged
            self.log.debug(f"Ignoring action log message {item.item_id}")
            return []

        # TODO handle item.clip?
        # TODO should these be put into a caption?
        if handle_text and item.text:
            converted.append(await self._convert_instagram_text(item, item.text))
        elif item.like:
            # We handle likes as text because Matrix clients do big emoji on their own.
            converted.append(await self._convert_instagram_text(item, item.like))
        elif item.link:
            converted.append(await self._convert_instagram_link(source, intent, item))

        if len(converted) == 0:
            self.log.debug(f"Unhandled Instagram message {item.item_id}")
            converted.append(await self._convert_instagram_unhandled(item))

        return converted

    def _deterministic_event_id(
        self, sender: p.Puppet, item_id: str, part_name: int | None = None
    ) -> EventID:
        hash_content = f"{self.mxid}/instagram/{sender.igpk}/{item_id}"
        if part_name:
            hash_content += f"/{part_name}"
        hashed = hashlib.sha256(hash_content.encode("utf-8")).digest()
        b64hash = base64.urlsafe_b64encode(hashed).decode("utf-8").rstrip("=")
        return EventID(f"${b64hash}:telegram.org")

    async def handle_instagram_remove(self, item_id: str) -> None:
        message = await DBMessage.get_by_item_id(item_id, self.receiver)
        if message is None:
            return
        await message.delete()
        if message.mxid:
            sender = await p.Puppet.get_by_pk(message.sender)
            try:
                await sender.intent_for(self).redact(self.mxid, message.mxid)
            except MForbidden:
                await self.main_intent.redact(self.mxid, message.mxid)
            self.log.debug(f"Redacted {message.mxid} after Instagram unsend")

    async def handle_instagram_reaction(self, item: ThreadItem, remove: bool) -> None:
        sender = await p.Puppet.get_by_pk(item.new_reaction.sender_id)
        message = await DBMessage.get_by_item_id(item.item_id, self.receiver)
        if not message:
            self.log.debug(f"Dropping reaction by {sender.pk} to unknown message {item.item_id}")
            return
        emoji = item.new_reaction.emoji
        async with self._reaction_lock:
            existing = await DBReaction.get_by_item_id(item.item_id, self.receiver, sender.pk)
            if not existing and remove:
                self.log.debug(
                    f"Ignoring duplicate reaction removal by {sender.pk} to {item.item_id}"
                )
                return
            elif not remove and existing and existing.reaction == emoji:
                self.log.debug(f"Ignoring duplicate reaction by {sender.pk} to {item.item_id}")
                return
            intent = sender.intent_for(self)
            if remove:
                await existing.delete()
                await intent.redact(self.mxid, existing.mxid)
                self.log.debug(
                    f"Removed {sender.pk}'s reaction to {item.item_id} (redacted {existing.mxid})"
                )
            else:
                timestamp = item.new_reaction.timestamp_ms
                reaction_event_id = await intent.react(
                    self.mxid, message.mxid, key=emoji, timestamp=timestamp
                )
                await self._upsert_reaction(
                    existing, intent, reaction_event_id, message, sender, emoji, timestamp
                )
                self.log.debug(
                    f"Handled {sender.pk}'s reaction to {item.item_id} -> {reaction_event_id}"
                )

    async def _handle_instagram_reactions(
        self, message: DBMessage, reactions: list[Reaction]
    ) -> None:
        old_reactions: dict[int, DBReaction]
        old_reactions = {
            reaction.ig_sender: reaction
            for reaction in await DBReaction.get_all_by_item_id(message.item_id, self.receiver)
        }
        for new_reaction in reactions:
            old_reaction = old_reactions.pop(new_reaction.sender_id, None)
            if old_reaction and old_reaction.reaction == new_reaction.emoji:
                continue
            puppet = await p.Puppet.get_by_pk(new_reaction.sender_id)
            intent = puppet.intent_for(self)
            timestamp = int(time.time() * 1000)
            reaction_event_id = await intent.react(
                self.mxid, message.mxid, new_reaction.emoji, timestamp=timestamp
            )
            await self._upsert_reaction(
                old_reaction,
                intent,
                reaction_event_id,
                message,
                puppet,
                new_reaction.emoji,
                timestamp,
            )
        for old_reaction in old_reactions.values():
            await old_reaction.delete()
            puppet = await p.Puppet.get_by_pk(old_reaction.ig_sender)
            await puppet.intent_for(self).redact(self.mxid, old_reaction.mxid)

    async def handle_instagram_update(self, item: MessageSyncMessage) -> None:
        message = await DBMessage.get_by_item_id(item.item_id, self.receiver)
        if not message:
            return
        if item.has_seen:
            puppet = await p.Puppet.get_by_pk(item.has_seen, create=False)
            if puppet:
                await puppet.intent_for(self).mark_read(self.mxid, message.mxid)
        else:
            async with self._reaction_lock:
                await self._handle_instagram_reactions(
                    message, (item.reactions.emojis if item.reactions else [])
                )

    # endregion
    # region Updating portal info

    def _get_thread_name(self, thread: Thread) -> str:
        if self.is_direct:
            if self.other_user_pk == thread.viewer_id and len(thread.users) == 0:
                return "Instagram chat with yourself"
            elif len(thread.users) == 1:
                tpl = self.config["bridge.private_chat_name_template"]
                ui = thread.users[0]
                return tpl.format(
                    displayname=ui.full_name or ui.username, id=ui.pk, username=ui.username
                )
        elif thread.thread_title:
            return self.config["bridge.group_chat_name_template"].format(name=thread.thread_title)

        return ""

    async def _get_thread_avatar(self, source: u.User, thread: Thread) -> Optional[ContentURI]:
        if self.is_direct or not thread.thread_image:
            return None
        if self.thread_image_id == thread.thread_image.id:
            return self.avatar_url
        best: Optional[ThreadImageCandidate] = None
        for candidate in thread.thread_image.image_versions2.candidates:
            if best is None or candidate.width > best.width:
                best = candidate
        if not best:
            return None
        data, mimetype = await self._download_instagram_file(source, best.url)
        if not data:
            return None
        mxc = await self.main_intent.upload_media(
            data=data,
            mime_type=mimetype,
            filename=thread.thread_image.id,
            async_upload=self.config["homeserver.async_media"],
        )
        self.thread_image_id = thread.thread_image.id
        return mxc

    async def update_info(self, thread: Thread, source: u.User) -> None:
        changed = await self._update_name(self._get_thread_name(thread))
        if thread_avatar := await self._get_thread_avatar(source, thread):
            changed = await self._update_photo(thread_avatar)
        changed = await self._update_participants(thread.users, source) or changed
        if changed:
            await self.update_bridge_info()
            await self.update()
        # TODO update power levels with thread.admin_user_ids

    async def update_info_from_puppet(self, puppet: p.Puppet | None = None) -> None:
        if not self.is_direct:
            return
        if not puppet:
            puppet = await self.get_dm_puppet()
        await self._update_photo_from_puppet(puppet)
        if self.name and not self.name_set:
            await self._update_name(self.name)

    async def _update_name(self, name: str) -> bool:
        if name and (self.name != name or not self.name_set):
            self.name = name
            if self.mxid:
                try:
                    await self.main_intent.set_room_name(self.mxid, name)
                    self.name_set = True
                except Exception:
                    self.log.exception("Failed to update name")
                    self.name_set = False
            return True
        return False

    async def _update_photo_from_puppet(self, puppet: p.Puppet) -> bool:
        if not self.private_chat_portal_meta and not self.encrypted:
            return False
        return await self._update_photo(puppet.photo_mxc)

    async def _update_photo(self, photo_mxc: ContentURI) -> bool:
        if self.avatar_set and self.avatar_url == photo_mxc:
            return False
        self.avatar_url = photo_mxc
        if self.mxid:
            try:
                await self.main_intent.set_room_avatar(self.mxid, photo_mxc)
                self.avatar_set = True
            except Exception:
                self.log.exception("Failed to set room avatar")
                self.avatar_set = False
        return True

    async def _update_participants(self, users: list[ThreadUser], source: u.User) -> bool:
        meta_changed = False

        # Make sure puppets who should be here are here
        for user in users:
            puppet = await p.Puppet.get_by_pk(user.pk)
            await puppet.update_info(user, source)
            if self.mxid:
                await puppet.intent_for(self).ensure_joined(self.mxid)
            if puppet.pk == self.other_user_pk:
                meta_changed = await self._update_photo_from_puppet(puppet)

        if self.mxid:
            # Kick puppets who shouldn't be here
            current_members = {int(user.pk) for user in users}
            for user_id in await self.main_intent.get_room_members(self.mxid):
                pk = p.Puppet.get_id_from_mxid(user_id)
                if pk and pk not in current_members and pk != self.other_user_pk:
                    await self.main_intent.kick_user(
                        self.mxid,
                        p.Puppet.get_mxid_from_id(pk),
                        reason="User had left this Instagram DM",
                    )

        return meta_changed

    async def _update_read_receipts(self, receipts: dict[int | str, ThreadUserLastSeenAt]) -> None:
        for user_id, receipt in receipts.items():
            message: DBMessage | DBReaction
            message = await DBMessage.get_by_item_id(receipt.item_id, self.receiver)
            if not message:
                reaction: DBReaction
                message, reaction = await asyncio.gather(
                    DBMessage.get_closest(self.mxid, int(receipt.timestamp)),
                    DBReaction.get_closest(self.mxid, receipt.timestamp_ms),
                )
                if (not message or not message.mxid) and not reaction:
                    self.log.debug(
                        "Couldn't find message %s to mark as read by %s", receipt, user_id
                    )
                    continue
                elif not message or (reaction and reaction.mx_timestamp > message.ig_timestamp_ms):
                    message = reaction
            puppet = await p.Puppet.get_by_pk(int(user_id), create=False)
            if not puppet:
                continue
            try:
                await puppet.intent_for(self).mark_read(message.mx_room, message.mxid)
            except Exception:
                self.log.warning(
                    f"Failed to mark {message.mxid} in {message.mx_room} "
                    f"as read by {puppet.intent.mxid}",
                    exc_info=True,
                )

    async def get_dm_puppet(self) -> p.Puppet | None:
        if not self.is_direct:
            return None
        return await p.Puppet.get_by_pk(self.other_user_pk)

    # endregion
    # region Backfill

    async def enqueue_immediate_backfill(self, source: u.User, priority: int) -> None:
        assert self.config["bridge.backfill.msc2716"]
        if not await Backfill.get(source.mxid, self.thread_id, self.receiver):
            await Backfill.new(
                source.mxid,
                priority,
                self.thread_id,
                self.receiver,
                self.config["bridge.backfill.incremental.max_pages"],
                self.config["bridge.backfill.incremental.page_delay"],
                self.config["bridge.backfill.incremental.post_batch_delay"],
                self.config["bridge.backfill.incremental.max_total_pages"],
            ).insert()

    async def backfill(self, source: u.User, backfill_request: Backfill) -> None:
        try:
            last_message_ig_timestamp = await self._backfill(source, backfill_request)
            if last_message_ig_timestamp is not None:
                await self.send_post_backfill_dummy(last_message_ig_timestamp)
        finally:
            # Always sleep after the backfill request is finished processing, even if it errors.
            await asyncio.sleep(backfill_request.post_batch_delay)

    async def _backfill(self, source: u.User, backfill_request: Backfill) -> int | None:
        assert source.client
        self.log.debug("Backfill request: %s", backfill_request)

        num_pages = backfill_request.num_pages
        self.log.debug(
            "Backfilling up to %d pages of history in %s through %s",
            num_pages,
            self.mxid,
            source.mxid,
        )

        try:
            if self.cursor:
                self.log.debug(
                    f"There is a cursor for the chat, fetching messages before {self.cursor}"
                )
                resp = await source.client.get_thread(
                    self.thread_id, seq_id=source.seq_id, cursor=self.cursor
                )
            else:
                self.log.debug(
                    "There is no first message in the chat, starting with the most recent messages"
                )
                resp = await source.client.get_thread(self.thread_id, seq_id=source.seq_id)
        except IGRateLimitError as e:
            backoff = self.config.get("bridge.backfill.backoff.message_history", 300)
            self.log.warning(
                f"Backfilling failed due to rate limit. Waiting for {backoff} seconds before "
                f"resuming. Error: {e}"
            )
            await asyncio.sleep(backoff)
            raise

        async def dedup_messages(messages: list[ThreadItem]) -> list[ThreadItem]:
            deduped = []
            # Sometimes (seems like on Facebook chats) it fetches the first message in the chat over
            # and over again.
            for item in messages:
                # Check in-memory queues for duplicates
                if item.item_id in self._msgid_dedup:
                    self.log.debug(
                        f"Ignoring message {item.item_id} ({item.client_context}) by {item.user_id}"
                        " as it was already handled (message.id in dedup queue)"
                    )
                    continue
                self._msgid_dedup.appendleft(item.item_id)

                # Check database for duplicates
                if await DBMessage.get_by_item_id(item.item_id, self.receiver) is not None:
                    self.log.debug(
                        f"Ignoring message {item.item_id} ({item.client_context}) by {item.user_id}"
                        " as it was already handled (message.id in database)"
                    )
                    continue

                deduped.append(item)
            return deduped

        messages = await dedup_messages(resp.thread.items)
        cursor = resp.thread.oldest_cursor
        backfill_more = resp.thread.has_older
        if len(messages) == 0:
            self.log.debug("No messages to backfill.")
            return None

        last_message_timestamp = messages[-1].timestamp_ms

        pages_to_backfill = backfill_request.num_pages
        if backfill_request.max_total_pages > -1:
            pages_to_backfill = min(pages_to_backfill, backfill_request.max_total_pages)

        pages_backfilled = 0
        for i in range(pages_to_backfill):
            base_insertion_event_id = await self.backfill_message_page(
                source, list(reversed(messages))
            )
            self.cursor = cursor
            await self.save()
            pages_backfilled += 1

            if base_insertion_event_id:
                self.historical_base_insertion_event_id = base_insertion_event_id
                await self.save()

            if backfill_more and i < pages_to_backfill - 1:
                # Sleep before fetching another page of messages.
                await asyncio.sleep(backfill_request.page_delay)

                # Fetch more messages
                try:
                    resp = await source.client.get_thread(
                        self.thread_id, seq_id=source.seq_id, cursor=self.cursor
                    )
                    messages = await dedup_messages(resp.thread.items)
                    cursor = resp.thread.oldest_cursor
                    backfill_more &= resp.thread.has_older
                except IGRateLimitError as e:
                    backoff = self.config.get("bridge.backfill.backoff.message_history", 300)
                    self.log.warning(
                        f"Backfilling failed due to rate limit. Waiting for {backoff} seconds "
                        "before resuming."
                    )
                    await asyncio.sleep(backoff)

                    # If we hit the rate limit, then we will want to give up for now, but enqueue
                    # additional backfill to do later.
                    break

        if backfill_request.max_total_pages == -1:
            new_max_total_pages = -1
        else:
            new_max_total_pages = backfill_request.max_total_pages - pages_backfilled
            if new_max_total_pages <= 0:
                backfill_more = False

        if backfill_more:
            self.log.debug("Enqueueing more backfill")
            await Backfill.new(
                source.mxid,
                # Always enqueue subsequent backfills at the lowest priority
                2,
                self.thread_id,
                self.receiver,
                backfill_request.num_pages,
                backfill_request.page_delay,
                backfill_request.post_batch_delay,
                new_max_total_pages,
            ).insert()
        else:
            self.log.debug("No more messages to backfill")

        await self._update_read_receipts(resp.thread.last_seen_at)
        return last_message_timestamp

    async def backfill_message_page(
        self,
        source: u.User,
        message_page: list[ThreadItem],
        forward: bool = False,
        last_message: DBMessage | None = None,
        mark_read: bool = False,
    ) -> EventID | None:
        """
        Backfills a page of messages to Matrix. The messages should be in order from oldest to
        newest.

        Returns: a tuple containing the number of messages that were actually bridged, the
            timestamp of the oldest bridged message and the base insertion event ID if it exists.
        """
        assert source.client
        if len(message_page) == 0:
            return None

        if forward:
            assert (last_message and last_message.mxid) or self.first_event_id
            prev_event_id = last_message.mxid if last_message else self.first_event_id
        else:
            assert self.config["bridge.backfill.msc2716"]
            assert self.first_event_id
            prev_event_id = self.first_event_id

        assert self.mxid

        oldest_message_in_page = message_page[0]
        oldest_msg_timestamp = oldest_message_in_page.timestamp_ms

        batch_messages: list[BatchSendEvent] = []
        state_events_at_start: list[BatchSendStateEvent] = []

        added_members = set()
        current_members = await self.main_intent.state_store.get_members(
            self.mxid, memberships=(Membership.JOIN,)
        )

        def add_member(puppet: p.Puppet, mxid: UserID):
            assert self.mxid
            if mxid in added_members:
                return
            if (
                self.bridge.homeserver_software.is_hungry
                or not self.config["bridge.backfill.msc2716"]
            ):
                # Hungryserv doesn't expect or check state events at start.
                added_members.add(mxid)
                return

            content_args = {"avatar_url": puppet.photo_mxc, "displayname": puppet.name}
            state_events_at_start.extend(
                [
                    BatchSendStateEvent(
                        content=MemberStateEventContent(Membership.INVITE, **content_args),
                        type=EventType.ROOM_MEMBER,
                        sender=self.main_intent.mxid,
                        state_key=mxid,
                        timestamp=oldest_msg_timestamp,
                    ),
                    BatchSendStateEvent(
                        content=MemberStateEventContent(Membership.JOIN, **content_args),
                        type=EventType.ROOM_MEMBER,
                        sender=mxid,
                        state_key=mxid,
                        timestamp=oldest_msg_timestamp,
                    ),
                ]
            )
            added_members.add(mxid)

        async def intent_for(user_id: int) -> tuple[p.Puppet, IntentAPI]:
            puppet: p.Puppet = await p.Puppet.get_by_pk(user_id)
            if puppet:
                intent = puppet.intent_for(self)
            else:
                intent = self.main_intent
            if puppet.is_real_user and not self._can_double_puppet_backfill(intent.mxid):
                intent = puppet.default_mxid_intent
            return puppet, intent

        message_infos: list[tuple[ThreadItem | Reaction, int]] = []
        intents: list[IntentAPI] = []

        for message in message_page:
            puppet, intent = await intent_for(message.user_id)

            # Convert the message
            converted = await self.convert_instagram_item(source, puppet, message)
            if not converted:
                self.log.debug(f"Skipping unsupported message in backfill {message.item_id}")
                continue

            if intent.mxid not in current_members:
                add_member(puppet, intent.mxid)

            d_event_id = None
            for index, (event_type, content) in enumerate(converted):
                if self.encrypted and self.matrix.e2ee:
                    event_type, content = await self.matrix.e2ee.encrypt(
                        self.mxid, event_type, content
                    )
                if intent.api.is_real_user and intent.api.bridge_name is not None:
                    content[DOUBLE_PUPPET_SOURCE_KEY] = intent.api.bridge_name

                if self.bridge.homeserver_software.is_hungry:
                    d_event_id = self._deterministic_event_id(puppet, message.item_id, index)

                message_infos.append((message, index))
                batch_messages.append(
                    BatchSendEvent(
                        content=content,
                        type=event_type,
                        sender=intent.mxid,
                        timestamp=message.timestamp_ms,
                        event_id=d_event_id,
                    )
                )
                intents.append(intent)

            if self.bridge.homeserver_software.is_hungry and message.reactions:
                for reaction in message.reactions.emojis:
                    puppet, intent = await intent_for(reaction.sender_id)

                    reaction_event = ReactionEventContent()
                    reaction_event.relates_to = RelatesTo(
                        rel_type=RelationType.ANNOTATION, event_id=d_event_id, key=reaction.emoji
                    )
                    if intent.api.is_real_user and intent.api.bridge_name is not None:
                        reaction_event[DOUBLE_PUPPET_SOURCE_KEY] = intent.api.bridge_name

                    message_infos.append((reaction, 0))
                    batch_messages.append(
                        BatchSendEvent(
                            content=reaction_event,
                            type=EventType.REACTION,
                            sender=intent.mxid,
                            timestamp=reaction.timestamp_ms,
                        )
                    )

        if not batch_messages:
            return None

        if not self.bridge.homeserver_software.is_hungry and (
            forward or self.next_batch_id is None
        ):
            self.log.debug("Sending dummy event to avoid forward extremity errors")
            await self.az.intent.send_message_event(
                self.mxid, EventType("fi.mau.dummy.pre_backfill", EventType.Class.MESSAGE), {}
            )

        self.log.info(
            "Sending %d %s messages to %s with batch ID %s and previous event ID %s",
            len(batch_messages),
            "new" if forward else "historical",
            self.mxid,
            self.next_batch_id,
            prev_event_id,
        )
        if self.bridge.homeserver_software.is_hungry:
            self.log.debug("Batch message event IDs %s", [m.event_id for m in batch_messages])

        base_insertion_event_id = None
        if self.config["bridge.backfill.msc2716"]:
            batch_send_resp = await self.main_intent.batch_send(
                self.mxid,
                prev_event_id,
                batch_id=self.next_batch_id,
                events=batch_messages,
                state_events_at_start=state_events_at_start,
                beeper_new_messages=forward,
                beeper_mark_read_by=source.mxid if mark_read else None,
            )
            base_insertion_event_id = batch_send_resp.base_insertion_event_id
            event_ids = batch_send_resp.event_ids
        else:
            batch_send_resp = None
            event_ids = [
                await intent.send_message_event(
                    self.mxid, evt.type, evt.content, timestamp=evt.timestamp
                )
                for evt, intent in zip(reversed(batch_messages), reversed(intents))
            ]
        await self._finish_batch(event_ids, message_infos)
        if not forward:
            assert batch_send_resp
            self.log.debug("Got next batch ID %s for %s", batch_send_resp.next_batch_id, self.mxid)
            self.next_batch_id = batch_send_resp.next_batch_id
        await self.save()

        return base_insertion_event_id

    def _can_double_puppet_backfill(self, custom_mxid: UserID) -> bool:
        return self.config["bridge.backfill.double_puppet_backfill"] and (
            # Hungryserv can batch send any users
            self.bridge.homeserver_software.is_hungry
            # Non-MSC2716 backfill can use any double puppet
            or not self.config["bridge.backfill.msc2716"]
            # Local users can be double puppeted even with MSC2716
            or (custom_mxid[custom_mxid.index(":") + 1 :] == self.config["homeserver.domain"])
        )

    async def _finish_batch(
        self, event_ids: list[EventID], message_infos: list[tuple[ThreadItem | Reaction, int]]
    ):
        # We have to do this slightly annoying processing of the event IDs and message infos so
        # that we only map the last event ID to the message.
        # When inline captions are enabled, this will have no effect since index will always be 0
        # since there's only ever one event per message.
        current_message = None
        messages = []
        reactions = []
        message_id = None
        for event_id, (message_or_reaction, index) in zip(event_ids, message_infos):
            if isinstance(message_or_reaction, ThreadItem):
                message = message_or_reaction
                if index == 0 and current_message:
                    # This means that all of the events for the previous message have been processed,
                    # and the current_message is the most recent event for that message.
                    messages.append(current_message)

                current_message = DBMessage(
                    mxid=event_id,
                    mx_room=self.mxid,
                    item_id=message.item_id,
                    client_context=message.client_context,
                    receiver=self.receiver,
                    sender=message.user_id,
                    ig_timestamp=message.timestamp,
                )
                message_id = message.item_id
            else:
                assert message_id
                reaction = message_or_reaction
                reactions.append(
                    DBReaction(
                        mxid=event_id,
                        mx_room=self.mxid,
                        ig_item_id=message_id,
                        ig_receiver=self.receiver,
                        ig_sender=reaction.sender_id,
                        reaction=reaction.emoji,
                        mx_timestamp=reaction.timestamp_ms,
                    )
                )

        if current_message:
            messages.append(current_message)

        try:
            await DBMessage.bulk_insert(messages)
        except Exception:
            self.log.exception("Failed to store batch message IDs")

        try:
            for reaction in reactions:
                await reaction.insert()
        except Exception:
            self.log.exception("Failed to store backfilled reactions")

    async def send_post_backfill_dummy(
        self,
        last_message_ig_timestamp: int,
        base_insertion_event_id: EventID | None = None,
    ):
        assert self.mxid

        if not base_insertion_event_id:
            base_insertion_event_id = self.historical_base_insertion_event_id

        if not base_insertion_event_id:
            self.log.debug(
                "No base insertion event ID in database or from batch send response. Not sending"
                " dummy event."
            )
            return

        event_id = await self.main_intent.send_message_event(
            self.mxid,
            event_type=HistorySyncMarkerMessage,
            content={
                "org.matrix.msc2716.marker.insertion": base_insertion_event_id,
                "m.marker.insertion": base_insertion_event_id,
            },
        )
        await DBMessage(
            mxid=event_id,
            mx_room=self.mxid,
            item_id=f"fi.mau.instagram.post_backfill_dummy.{last_message_ig_timestamp}",
            client_context=None,
            receiver=self.receiver,
            sender=0,
            ig_timestamp=last_message_ig_timestamp,
        ).insert()

    # endregion
    # region Bridge info state event

    @property
    def bridge_info_state_key(self) -> str:
        return f"net.maunium.instagram://instagram/{self.thread_id}"

    @property
    def bridge_info(self) -> dict[str, Any]:
        return {
            "bridgebot": self.az.bot_mxid,
            "creator": self.main_intent.mxid,
            "protocol": {
                "id": "instagram",
                "displayname": "Instagram DM",
                "avatar_url": self.config["appservice.bot_avatar"],
            },
            "channel": {
                "id": self.thread_id,
                "displayname": self.name,
                "avatar_url": self.avatar_url,
            },
        }

    async def update_bridge_info(self) -> None:
        if not self.mxid:
            self.log.debug("Not updating bridge info: no Matrix room created")
            return
        try:
            self.log.debug("Updating bridge info...")
            await self.main_intent.send_state_event(
                self.mxid, StateBridge, self.bridge_info, self.bridge_info_state_key
            )
            # TODO remove this once https://github.com/matrix-org/matrix-doc/pull/2346 is in spec
            await self.main_intent.send_state_event(
                self.mxid, StateHalfShotBridge, self.bridge_info, self.bridge_info_state_key
            )
        except Exception:
            self.log.warning("Failed to update bridge info", exc_info=True)

    # endregion
    # region Creating Matrix rooms

    async def create_matrix_room(self, source: u.User, info: Thread) -> RoomID | None:
        if self.mxid:
            try:
                await self.update_matrix_room(source, info)
            except Exception:
                self.log.exception("Failed to update portal")
            return self.mxid
        async with self._create_room_lock:
            try:
                return await self._create_matrix_room(source, info)
            except Exception:
                self.log.exception("Failed to create portal")
                return None

    def _get_invite_content(self, double_puppet: p.Puppet | None) -> dict[str, bool]:
        invite_content = {}
        if double_puppet:
            invite_content["fi.mau.will_auto_accept"] = True
        if self.is_direct:
            invite_content["is_direct"] = True
        return invite_content

    async def update_matrix_room(self, source: u.User, info: Thread) -> None:
        puppet = await p.Puppet.get_by_custom_mxid(source.mxid)
        await self.main_intent.invite_user(
            self.mxid,
            source.mxid,
            check_cache=True,
            extra_content=self._get_invite_content(puppet),
        )
        if puppet:
            did_join = await puppet.intent.ensure_joined(self.mxid)
            if did_join and self.is_direct:
                await source.update_direct_chats({self.main_intent.mxid: [self.mxid]})

        await self.update_info(info, source)
        await self._update_read_receipts(info.last_seen_at)

    async def _create_matrix_room(self, source: u.User, info: Thread) -> RoomID | None:
        if self.mxid:
            await self.update_matrix_room(source, info)
            return self.mxid
        await self.update_info(info, source)
        self.log.debug("Creating Matrix room")
        name: str | None = None
        initial_state = [
            {
                "type": str(StateBridge),
                "state_key": self.bridge_info_state_key,
                "content": self.bridge_info,
            },
            # TODO remove this once https://github.com/matrix-org/matrix-doc/pull/2346 is in spec
            {
                "type": str(StateHalfShotBridge),
                "state_key": self.bridge_info_state_key,
                "content": self.bridge_info,
            },
        ]
        invites = []
        if self.config["bridge.encryption.default"] and self.matrix.e2ee:
            self.encrypted = True
            initial_state.append(
                {
                    "type": "m.room.encryption",
                    "content": self.get_encryption_state_event_json(),
                }
            )
            if self.is_direct:
                invites.append(self.az.bot_mxid)
        if self.encrypted or self.private_chat_portal_meta or not self.is_direct:
            name = self.name

        creation_content = {}
        if not self.config["bridge.federate_rooms"]:
            creation_content["m.federate"] = False
        self.mxid = await self.main_intent.create_room(
            name=name,
            is_direct=self.is_direct,
            initial_state=initial_state,
            invitees=invites,
            creation_content=creation_content,
        )
        if not self.mxid:
            raise Exception("Failed to create room: no mxid returned")

        if self.encrypted and self.matrix.e2ee and self.is_direct:
            try:
                await self.az.intent.ensure_joined(self.mxid)
            except Exception:
                self.log.warning(f"Failed to add bridge bot to new private chat {self.mxid}")

        await self.update()
        self.log.debug(f"Matrix room created: {self.mxid}")
        self.by_mxid[self.mxid] = self

        puppet = await p.Puppet.get_by_custom_mxid(source.mxid)
        await self.main_intent.invite_user(
            self.mxid, source.mxid, extra_content=self._get_invite_content(puppet)
        )
        if puppet:
            try:
                if self.is_direct:
                    await source.update_direct_chats({self.main_intent.mxid: [self.mxid]})
                await puppet.intent.join_room_by_id(self.mxid)
            except MatrixError:
                self.log.debug(
                    "Failed to join custom puppet into newly created portal", exc_info=True
                )

        await self._update_participants(info.users, source)

        self.log.trace("Sending portal post-create dummy event")
        self.first_event_id = await self.az.intent.send_message_event(
            self.mxid, PortalCreateDummy, {}
        )
        await self.update()
        return self.mxid

    # endregion
    # region Database getters

    async def postinit(self) -> None:
        self.by_thread_id[(self.thread_id, self.receiver)] = self
        if self.mxid:
            self.by_mxid[self.mxid] = self
        self._main_intent = (
            (await p.Puppet.get_by_pk(self.other_user_pk)).default_mxid_intent
            if self.other_user_pk
            else self.az.intent
        )

    async def delete(self) -> None:
        await DBMessage.delete_all(self.mxid)
        self.by_mxid.pop(self.mxid, None)
        self.mxid = None
        self.encrypted = False
        await self.update()

    async def save(self) -> None:
        await self.update()

    @classmethod
    def all_with_room(cls) -> AsyncGenerator[Portal, None]:
        return cls._db_to_portals(super().all_with_room())

    @classmethod
    def find_private_chats_with(cls, other_user: int) -> AsyncGenerator[Portal, None]:
        return cls._db_to_portals(super().find_private_chats_with(other_user))

    @classmethod
    async def find_private_chat(cls, receiver: int, other_user: int) -> Portal | None:
        thread_id = await super().find_private_chat_id(receiver, other_user)
        if not thread_id:
            return None
        return await cls.get_by_thread_id(thread_id, receiver=receiver, is_group=False)

    @classmethod
    async def _db_to_portals(cls, query: Awaitable[list[Portal]]) -> AsyncGenerator[Portal, None]:
        portals = await query
        for index, portal in enumerate(portals):
            try:
                yield cls.by_thread_id[(portal.thread_id, portal.receiver)]
            except KeyError:
                await portal.postinit()
                yield portal

    @classmethod
    @async_getter_lock
    async def get_by_mxid(cls, mxid: RoomID) -> Portal | None:
        try:
            return cls.by_mxid[mxid]
        except KeyError:
            pass

        portal = cast(cls, await super().get_by_mxid(mxid))
        if portal is not None:
            await portal.postinit()
            return portal

        return None

    @classmethod
    @async_getter_lock
    async def get_by_thread_id(
        cls,
        thread_id: str,
        *,
        receiver: int,
        is_group: bool | None = None,
        other_user_pk: int | None = None,
    ) -> Portal | None:
        if is_group and receiver != 0:
            receiver = 0
        try:
            return cls.by_thread_id[(thread_id, receiver)]
        except KeyError:
            pass
        if is_group is None and receiver != 0:
            try:
                return cls.by_thread_id[(thread_id, 0)]
            except KeyError:
                pass

        portal = cast(
            cls,
            await super().get_by_thread_id(
                thread_id, receiver=receiver, rec_must_match=is_group is not None
            ),
        )
        if portal is not None:
            await portal.postinit()
            return portal

        if is_group is not None:
            portal = cls(thread_id, receiver, other_user_pk=other_user_pk)
            await portal.insert()
            await portal.postinit()
            return portal

        return None

    @classmethod
    async def get_by_thread(cls, thread: Thread, receiver: int) -> Portal | None:
        if thread.is_group:
            receiver = 0
            other_user_pk = None
        else:
            if len(thread.users) == 0:
                other_user_pk = receiver
            else:
                other_user_pk = thread.users[0].pk
        return await cls.get_by_thread_id(
            thread.thread_id,
            receiver=receiver,
            is_group=thread.is_group,
            other_user_pk=other_user_pk,
        )

    # endregion
