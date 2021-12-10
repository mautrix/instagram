# mautrix-instagram - A Matrix-Instagram puppeting bridge.
# Copyright (C) 2021 Tulir Asokan
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
from typing import (Dict, Tuple, Optional, List, Deque, Set, Any, Union, AsyncGenerator,
                    Awaitable, NamedTuple, Callable, TYPE_CHECKING, cast)
from collections import deque
from io import BytesIO
import mimetypes
import asyncio

import asyncpg
import magic
from mautrix.util.message_send_checkpoint import MessageSendCheckpointStatus

# for relaybot
from html import escape as escape_html
from string import Template

from mauigpapi.types import (Thread, ThreadUser, ThreadItem, RegularMediaItem, MediaType,
                             ReactionStatus, Reaction, AnimatedMediaItem, ThreadItemType,
                             VoiceMediaItem, ExpiredMediaItem, MessageSyncMessage, ReelShareType,
                             TypingStatus, ThreadUserLastSeenAt, MediaShareItem)
from mautrix.appservice import AppService, IntentAPI
from mautrix.bridge import BasePortal, NotificationDisabler, async_getter_lock
from mautrix.types import (EventID, MessageEventContent, RoomID, EventType, MessageType, ImageInfo,
                           VideoInfo, MediaMessageEventContent, TextMessageEventContent, AudioInfo,
                           ContentURI, EncryptedFile, LocationMessageEventContent, Format, UserID)
from mautrix.errors import MatrixError, MForbidden, MNotFound, SessionNotFound
from mautrix.util.simple_lock import SimpleLock

from .db import Portal as DBPortal, Message as DBMessage, Reaction as DBReaction
from .config import Config
from . import user as u, puppet as p, matrix as m

if TYPE_CHECKING:
    from .__main__ import InstagramBridge

try:
    from mautrix.crypto.attachments import encrypt_attachment, decrypt_attachment
except ImportError:
    encrypt_attachment = decrypt_attachment = None

try:
    from PIL import Image
except ImportError:
    Image = None

StateBridge = EventType.find("m.bridge", EventType.Class.STATE)
StateHalfShotBridge = EventType.find("uk.half-shot.bridge", EventType.Class.STATE)
FileInfo = Union[AudioInfo, ImageInfo, VideoInfo]
ReuploadedMediaInfo = NamedTuple('ReuploadedMediaInfo', mxc=Optional[ContentURI], url=str,
                                 decryption_info=Optional[EncryptedFile], msgtype=MessageType,
                                 file_name=str, info=FileInfo)
MediaData = Union[RegularMediaItem, ExpiredMediaItem]
MediaUploadFunc = Callable[['u.User', MediaData, IntentAPI], Awaitable[ReuploadedMediaInfo]]


class Portal(DBPortal, BasePortal):
    by_mxid: Dict[RoomID, 'Portal'] = {}
    by_thread_id: Dict[Tuple[str, int], 'Portal'] = {}
    config: Config
    matrix: 'm.MatrixHandler'
    az: AppService
    private_chat_portal_meta: bool

    _main_intent: Optional[IntentAPI]
    _create_room_lock: asyncio.Lock
    backfill_lock: SimpleLock
    _msgid_dedup: Deque[str]
    _reqid_dedup: Set[str]
    _reaction_dedup: Deque[Tuple[str, int, str]]

    _main_intent: IntentAPI
    _last_participant_update: Set[int]
    _reaction_lock: asyncio.Lock
    _backfill_leave: Optional[Set[IntentAPI]]
    _typing: Set[UserID]
    _relay_user: Optional['u.User']

    def __init__(self, thread_id: str, receiver: int, other_user_pk: Optional[int],
                 mxid: Optional[RoomID] = None, name: Optional[str] = None,
                 avatar_url: Optional[ContentURI] = None, encrypted: bool = False,
                 relay_user_id: Optional[UserID] = None, name_set: bool = False,
                 avatar_set: bool = False) -> None:
        super().__init__(thread_id, receiver, other_user_pk, mxid, name, avatar_url, encrypted,
                         name_set, avatar_set, relay_user_id)
        self._create_room_lock = asyncio.Lock()
        self.log = self.log.getChild(thread_id)
        self._msgid_dedup = deque(maxlen=100)
        self._reaction_dedup = deque(maxlen=100)
        self._reqid_dedup = set()
        self._last_participant_update = set()

        self.backfill_lock = SimpleLock("Waiting for backfilling to finish before handling %s",
                                        log=self.log)
        self._backfill_leave = None
        self._main_intent = None
        self._reaction_lock = asyncio.Lock()
        self._typing = set()
        self._relay_user = None

    @property
    def has_relay(self) -> bool:
        return self.config["bridge.relay.enabled"] and bool(self.relay_user_id)

    async def get_relay_user(self) -> Optional['u.User']:
        if not self.has_relay:
            return None

        if self._relay_user is None:
            self._relay_user = await u.User.get_by_mxid(self.relay_user_id)
        return self._relay_user if await self._relay_user.is_logged_in() else None

    async def set_relay_user(self, user: Optional['u.User']) -> None:
        self._relay_user = user
        self.relay_user_id = user.mxid if user else None
        await self.save()

    @property
    def is_direct(self) -> bool:
        return self.other_user_pk is not None

    @property
    def main_intent(self) -> IntentAPI:
        if not self._main_intent:
            raise ValueError("Portal must be postinit()ed before main_intent can be used")
        return self._main_intent

    @classmethod
    def init_cls(cls, bridge: 'InstagramBridge') -> None:
        cls.config = bridge.config
        cls.matrix = bridge.matrix
        cls.az = bridge.az
        cls.loop = bridge.loop
        cls.bridge = bridge
        cls.private_chat_portal_meta = cls.config["bridge.private_chat_portal_meta"]
        NotificationDisabler.puppet_cls = p.Puppet
        NotificationDisabler.config_enabled = cls.config["bridge.backfill.disable_notifications"]

    # region Misc

    async def _send_delivery_receipt(self, event_id: EventID) -> None:
        if event_id and self.config["bridge.delivery_receipts"]:
            try:
                await self.az.intent.mark_read(self.mxid, event_id)
            except Exception:
                self.log.exception("Failed to send delivery receipt for %s", event_id)

    async def _send_bridge_error(self, sender: 'u.User', err: Union[Exception, str],
                                 event_id: EventID, event_type: EventType,
                                 message_type: Optional[MessageType] = None,
                                 msg: Optional[str] = None, confirmed: bool = False) -> None:
        sender.send_remote_checkpoint(
            MessageSendCheckpointStatus.PERM_FAILURE,
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
            await self._send_message(self.main_intent, TextMessageEventContent(
                msgtype=MessageType.NOTICE,
                body=f"\u26a0 Your {event_type_str} {error_type} bridged: {msg or str(err)}"))

    async def _upsert_reaction(self, existing: Optional[DBReaction], intent: IntentAPI,
                               mxid: EventID, message: DBMessage,
                               sender: Union['u.User', 'p.Puppet'], reaction: str) -> None:
        if existing:
            self.log.debug(f"_upsert_reaction redacting {existing.mxid} and inserting {mxid}"
                           f" (message: {message.mxid})")
            await intent.redact(existing.mx_room, existing.mxid)
            await existing.edit(reaction=reaction, mxid=mxid, mx_room=message.mx_room)
        else:
            self.log.debug(f"_upsert_reaction inserting {mxid} (message: {message.mxid})")
            await DBReaction(mxid=mxid, mx_room=message.mx_room, ig_item_id=message.item_id,
                             ig_receiver=self.receiver, ig_sender=sender.igpk, reaction=reaction
                             ).insert()

    # endregion
    # region Matrix event handling

    async def apply_msg_format(self, sender: 'u.User', content: MessageEventContent) -> None:

        tpl = (self.config[f"relay.message_formats.[{content.msgtype.value}]"]
                or "$sender_displayname: $message")
        displayname = await self.get_displayname(sender)
        username, _ = self.az.intent.parse_user_id(sender.mxid)
        tpl_args = dict(sender_mxid=sender.mxid,
                        sender_username=username,
                        sender_displayname=escape_html(displayname),
                        message=content.body,
                        body=content.body,
                        )
        content.formatted_body = Template(tpl).safe_substitute(tpl_args)
        content.body = Template(tpl).safe_substitute(tpl_args)
        if content.msgtype == MessageType.EMOTE:
            content.msgtype = MessageType.TEXT

    async def get_relay_sender(self, sender: 'u.User', evt_identifier: str
                                ) -> Tuple[Optional['u.User'], bool]:
        if await sender.is_logged_in():
            return sender, False

        if not self.has_relay:
            self.log.debug(f"Ignoring {evt_identifier} from non-logged-in user {sender.mxid}"
                           " in chat with no relay user")
            return None, True
        relay_sender = await self.get_relay_user()
        if not relay_sender:
            self.log.debug(f"Ignoring {evt_identifier} from non-logged-in user {sender.mxid}: "
                           f"relay user {self.relay_user_id} is not set up correctly")
            return None, True
        return relay_sender, True

    async def handle_matrix_message(self, sender: 'u.User', message: MessageEventContent,
                                    event_id: EventID) -> None:
        try:
            await self._handle_matrix_message(sender, message, event_id)
        except Exception as e:
            self.log.exception(f"Fatal error handling Matrix event {event_id}: {e}")
            await self._send_bridge_error(
                sender,
                e,
                event_id,
                EventType.ROOM_MESSAGE,
                message_type=message.msgtype,
                msg="Fatal error in message handling (see logs for more details)",
            )

    async def _handle_matrix_message(self, sender: 'u.User', message: MessageEventContent,
                                     event_id: EventID) -> None:
        if ((message.get(self.bridge.real_user_content_key, False)
             and await p.Puppet.get_by_custom_mxid(sender.mxid))):
            self.log.debug(f"Ignoring puppet-sent message by confirmed puppet user {sender.mxid}")
            return

        orig_sender = sender
        sender, is_relay = await self.get_relay_sender(sender, f"message {event_id}")

        if not sender.is_connected:
            await self._send_bridge_error(
                sender,
                "You're not connected to Instagram",
                event_id,
                EventType.ROOM_MESSAGE,
                message_type=message.msgtype,
                confirmed=True,
            )
            return

        if not sender:
            return
        elif is_relay:
            await self.apply_msg_format(orig_sender, message)


        if not await sender.is_logged_in() and self.config['bridge.relaybot.enabled']:
            self.log.trace(f"Message sent by non instagram-user {sender.mxid}")
            async for user in u.User.all_logged_in():
                await self.apply_msg_format(sender, message)
                if await user.is_in_portal(self) and user.is_relay:
                    await self._handle_matrix_message(user, message, event_id, True)
                    return

        request_id = sender.state.gen_client_context()
        self._reqid_dedup.add(request_id)
        self.log.debug(f"Handling Matrix message {event_id} from {sender.mxid}/{sender.igpk} "
                       f"with request ID {request_id}")
        if message.msgtype in (MessageType.EMOTE, MessageType.TEXT):
            text = message.body
            if message.msgtype == MessageType.EMOTE:
                text = f"/me {text}"
            self.log.trace(f"Sending Matrix text from {event_id} with request ID {request_id}")
            resp = await sender.mqtt.send_text(self.thread_id, text=text,
                                               client_context=request_id)
        elif message.msgtype.is_media:
            text = message.body if is_relay else None
            if message.file and decrypt_attachment:
                data = await self.main_intent.download_media(message.file.url)
                data = decrypt_attachment(data, message.file.key.key,
                                          message.file.hashes.get("sha256"), message.file.iv)
            else:
                data = await self.main_intent.download_media(message.url)
            mime_type = message.info.mimetype or magic.from_buffer(data, mime=True)
            if mime_type != "image/jpeg" and mime_type.startswith("image/"):
                with BytesIO(data) as inp:
                    img = Image.open(inp)
                    with BytesIO() as out:
                        img.convert("RGB").save(out, format="JPEG", quality=80)
                        data = out.getvalue()
                mime_type = "image/jpeg"
            if mime_type == "image/jpeg":
                self.log.trace(f"Uploading photo from {event_id}")
                upload_resp = await sender.client.upload_jpeg_photo(data)
                self.log.trace(f"Broadcasting uploaded photo with request ID {request_id}")
                # TODO is it possible to do this with MQTT?
                resp = await sender.client.broadcast(self.thread_id,
                                                     ThreadItemType.CONFIGURE_PHOTO,
                                                     client_context=request_id,
                                                     upload_id=upload_resp.upload_id,
                                                     allow_full_aspect_ratio="1")
            else:
                await self._send_bridge_error(
                    sender,
                    "Non-image files are currently not supported",
                    event_id,
                    EventType.ROOM_MESSAGE,
                    message_type=message.msgtype,
                    confirmed=True,
                )
                return
        else:
            self.log.debug(f"Unhandled Matrix message {event_id}: "
                           f"unknown msgtype {message.msgtype}")
            return
        self.log.trace(f"Got response to message send {request_id}: {resp}")
        if resp.status != "ok":
            self.log.warning(f"Failed to handle {event_id}: {resp}")
            await self._send_bridge_error(
                sender,
                resp.payload.message,
                event_id,
                EventType.ROOM_MESSAGE,
                message_type=message.msgtype,
                confirmed=True,
            )
        else:
            sender.send_remote_checkpoint(
                status=MessageSendCheckpointStatus.SUCCESS,
                event_id=event_id,
                room_id=self.mxid,
                event_type=EventType.ROOM_MESSAGE,
                message_type=message.msgtype,
            )
            await self._send_delivery_receipt(event_id)
            self._msgid_dedup.appendleft(resp.payload.item_id)
            try:
                await DBMessage(mxid=event_id, mx_room=self.mxid, item_id=resp.payload.item_id,
                                receiver=self.receiver, sender=sender.igpk).insert()
            except asyncpg.UniqueViolationError as e:
                self.log.warning(f"Error while persisting {event_id} "
                                 f"({resp.payload.client_context}) -> {resp.payload.item_id}: {e}")
            self._reqid_dedup.remove(request_id)
            self.log.debug(f"Handled Matrix message {event_id} ({resp.payload.client_context}) "
                           f"-> {resp.payload.item_id}")

    async def handle_matrix_reaction(self, sender: 'u.User', event_id: EventID,
                                     reacting_to: EventID, emoji: str) -> None:
        message = await DBMessage.get_by_mxid(reacting_to, self.mxid)
        if not message or message.is_internal:
            self.log.debug(f"Ignoring reaction to unknown event {reacting_to}")
            return

        sender, _ = await self.get_relay_sender(sender, f"message {event_id}")

        if not await sender.is_logged_in():
            self.log.trace(f"Ignoring reaction by non-logged-in user {sender.mxid}")
            return

        existing = await DBReaction.get_by_item_id(message.item_id, message.receiver, sender.igpk)
        if existing and existing.reaction == emoji:
            return

        dedup_id = (message.item_id, sender.igpk, emoji)
        self._reaction_dedup.appendleft(dedup_id)
        async with self._reaction_lock:
            try:
                resp = await sender.mqtt.send_reaction(self.thread_id, item_id=message.item_id,
                                                       emoji=emoji)
                if resp.status != "ok":
                    raise Exception(f"Failed to react to {event_id}: {resp}")
            except Exception as e:
                self.log.exception(f"Failed to handle {event_id}: {e}")
                await self._send_bridge_error(
                    sender,
                    e,
                    event_id,
                    EventType.REACTION,
                    confirmed=True,
                )
            else:
                sender.send_remote_checkpoint(
                    status=MessageSendCheckpointStatus.SUCCESS,
                    event_id=event_id,
                    room_id=self.mxid,
                    event_type=EventType.REACTION,
                )
                await self._send_delivery_receipt(event_id)
                self.log.trace(f"{sender.mxid} reacted to {message.item_id} with {emoji}")
                await self._upsert_reaction(existing, self.main_intent, event_id, message, sender,
                                            emoji)

    async def handle_matrix_redaction(self, sender: 'u.User', event_id: EventID,
                                      redaction_event_id: EventID) -> None:
        sender, _ = await self.get_relay_sender(sender, f"message {event_id}")
        if not self.mxid or not await sender.is_logged_in():
            return

        if not sender.is_connected:
            await self._send_bridge_error(
                sender,
                "You're not connected to Instagram",
                redaction_event_id,
                EventType.ROOM_REDACTION,
                confirmed=True,
            )
            return

        reaction = await DBReaction.get_by_mxid(event_id, self.mxid)
        if reaction:
            try:
                await reaction.delete()
                await sender.mqtt.send_reaction(self.thread_id, item_id=reaction.ig_item_id,
                                                reaction_status=ReactionStatus.DELETED, emoji="")
            except Exception as e:
                self.log.exception("Removing reaction failed")
                await self._send_bridge_error(
                    sender,
                    e,
                    redaction_event_id,
                    EventType.ROOM_REDACTION,
                    confirmed=True,
                    msg=f"Removing reaction {reaction.reaction} from {event_id} failed.",
                )
            else:
                sender.send_remote_checkpoint(
                    status=MessageSendCheckpointStatus.SUCCESS,
                    event_id=redaction_event_id,
                    room_id=self.mxid,
                    event_type=EventType.ROOM_REDACTION,
                )
                await self._send_delivery_receipt(redaction_event_id)
                self.log.trace(f"Removed {reaction} after Matrix redaction")
            return

        message = await DBMessage.get_by_mxid(event_id, self.mxid)
        if message and not message.is_internal:
            try:
                await message.delete()
                await sender.client.delete_item(self.thread_id, message.item_id)
                self.log.trace(f"Removed {message} after Matrix redaction")
            except Exception as e:
                self.log.exception("Removing message failed")
                await self._send_bridge_error(
                    sender,
                    e,
                    redaction_event_id,
                    EventType.ROOM_REDACTION,
                    confirmed=True,
                    msg=f"Removing message {event_id} failed.",
                )
            else:
                sender.send_remote_checkpoint(
                    status=MessageSendCheckpointStatus.SUCCESS,
                    event_id=redaction_event_id,
                    room_id=self.mxid,
                    event_type=EventType.ROOM_REDACTION,
                )
                await self._send_delivery_receipt(redaction_event_id)
                self.log.trace(f"Removed {reaction} after Matrix redaction")
            return

        sender.send_remote_checkpoint(
            MessageSendCheckpointStatus.PERM_FAILURE,
            redaction_event_id,
            self.mxid,
            EventType.ROOM_REDACTION,
            error=Exception("No message or reaction found for redaction"),
        )

    async def handle_matrix_typing(self, users: Set[UserID]) -> None:
        if users == self._typing:
            return
        old_typing = self._typing
        self._typing = users
        await self._handle_matrix_typing(old_typing - users, TypingStatus.OFF)
        await self._handle_matrix_typing(users - old_typing, TypingStatus.TEXT)

    async def _handle_matrix_typing(self, users: Set[UserID], status: TypingStatus) -> None:
        for mxid in users:
            user = await u.User.get_by_mxid(mxid, create=False)
            if ((not user or not await user.is_logged_in() or user.remote_typing_status == status
                 or not user.is_connected)):
                continue
            user.remote_typing_status = None
            await user.mqtt.indicate_activity(self.thread_id, status)


    async def handle_matrix_leave(self, user: 'u.User') -> None:
        if not await user.is_logged_in():
            return
        if self.is_direct:
            self.log.info(f"{user.mxid} left private chat portal with {self.other_user_pk}")
            if user.igpk == self.receiver:
                self.log.info(f"{user.mxid} was the recipient of this portal. "
                              "Cleaning up and deleting...")
                await self.cleanup_and_delete()
        else:
            self.log.debug(f"{user.mxid} left portal to {self.thread_id}")
            # TODO cleanup if empty

    # endregion
    # region Instagram event handling

    async def _reupload_instagram_media(self, source: 'u.User', media: RegularMediaItem,
                                        intent: IntentAPI) -> ReuploadedMediaInfo:
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
        else:
            raise ValueError("Attachment not available: unsupported media type")
        return await self._reupload_instagram_file(source, url, msgtype, info, intent)

    async def _reupload_instagram_animated(self, source: 'u.User', media: AnimatedMediaItem,
                                           intent: IntentAPI) -> ReuploadedMediaInfo:
        url = media.images.fixed_height.webp
        info = ImageInfo(height=int(media.images.fixed_height.height),
                         width=int(media.images.fixed_height.width))
        return await self._reupload_instagram_file(source, url, MessageType.IMAGE, info, intent)

    async def _reupload_instagram_voice(self, source: 'u.User', media: VoiceMediaItem,
                                        intent: IntentAPI) -> ReuploadedMediaInfo:
        url = media.media.audio.audio_src
        info = AudioInfo(duration=media.media.audio.duration)
        return await self._reupload_instagram_file(source, url, MessageType.AUDIO, info, intent)

    async def _reupload_instagram_file(self, source: 'u.User', url: str, msgtype: MessageType,
                                       info: FileInfo, intent: IntentAPI
                                       ) -> ReuploadedMediaInfo:
        async with await source.client.raw_http_get(url) as resp:
            try:
                length = int(resp.headers["Content-Length"])
            except KeyError:
                # TODO can the download be short-circuited if there's too much data?
                self.log.warning("Got file download response with no Content-Length header,"
                                 "reading data dangerously")
                length = 0
            if length > self.matrix.media_config.upload_size:
                self.log.debug(f"{url} was too large ({length} "
                               f"> {self.matrix.media_config.upload_size})")
                raise ValueError("Attachment not available: too large")
            data = await resp.read()
            info.mimetype = resp.headers["Content-Type"] or magic.from_buffer(data, mime=True)
        info.size = len(data)
        extension = {
            "image/webp": ".webp",
            "image/jpeg": ".jpg",
            "video/mp4": ".mp4",
            "audio/mp4": ".m4a",
        }.get(info.mimetype)
        extension = extension or mimetypes.guess_extension(info.mimetype) or ""
        file_name = f"{msgtype.value[2:]}{extension}"

        upload_mime_type = info.mimetype
        upload_file_name = file_name
        decryption_info = None
        if self.encrypted and encrypt_attachment:
            data, decryption_info = encrypt_attachment(data)
            upload_mime_type = "application/octet-stream"
            upload_file_name = None

        mxc = await intent.upload_media(data, mime_type=upload_mime_type,
                                        filename=upload_file_name)

        if decryption_info:
            decryption_info.url = mxc
            mxc = None

        return ReuploadedMediaInfo(mxc=mxc, url=url, decryption_info=decryption_info,
                                   file_name=file_name, msgtype=msgtype, info=info)

    def _get_instagram_media_info(self, item: ThreadItem) -> Tuple[MediaUploadFunc, MediaData]:
        # TODO maybe use a dict and item.item_type instead of a ton of ifs
        method = self._reupload_instagram_media
        if item.media:
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
        elif item.media_share:
            media_data = item.media_share
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

    async def _handle_instagram_media(self, source: 'u.User', intent: IntentAPI, item: ThreadItem
                                      ) -> Optional[EventID]:
        try:
            reupload_func, media_data = self._get_instagram_media_info(item)
            reuploaded = await reupload_func(source, media_data, intent)
        except ValueError as e:
            content = TextMessageEventContent(body=str(e), msgtype=MessageType.NOTICE)
        except Exception:
            self.log.warning("Failed to upload media", exc_info=True)
            content = TextMessageEventContent(body="Attachment not available: failed to copy file",
                                              msgtype=MessageType.NOTICE)
        else:
            content = MediaMessageEventContent(
                body=reuploaded.file_name, external_url=reuploaded.url, url=reuploaded.mxc,
                file=reuploaded.decryption_info, info=reuploaded.info, msgtype=reuploaded.msgtype)
        await self._add_instagram_reply(content, item.replied_to_message)
        return await self._send_message(intent, content, timestamp=item.timestamp // 1000)

    async def _handle_instagram_media_share(self, source: 'u.User', intent: IntentAPI,
                                            item: ThreadItem) -> Optional[EventID]:
        share_item = item.media_share or item.story_share.media
        user_text = f"@{share_item.user.username}"
        user_link = (f'<a href="https://www.instagram.com/{share_item.user.username}/">'
                     f'{user_text}</a>')
        item_type_name = item.media_share.media_type.human_name if item.media_share else "story"
        prefix = TextMessageEventContent(msgtype=MessageType.NOTICE, format=Format.HTML,
                                         body=f"Sent {user_text}'s {item_type_name}",
                                         formatted_body=f"Sent {user_link}'s {item_type_name}")
        await self._send_message(intent, prefix, timestamp=item.timestamp // 1000)
        event_id = await self._handle_instagram_media(source, intent, item)
        if share_item.caption:
            external_url = f"https://www.instagram.com/p/{share_item.code}/"
            body = (f"> {share_item.caption.user.username}: {share_item.caption.text}\n\n"
                    f"{external_url}")
            formatted_body = (f"<blockquote><strong>{share_item.caption.user.username}</strong>"
                              f" {share_item.caption.text}</blockquote>"
                              f'<a href="{external_url}">instagram.com/p/{share_item.code}</a>')
            caption = TextMessageEventContent(msgtype=MessageType.TEXT, body=body,
                                              formatted_body=formatted_body, format=Format.HTML,
                                              external_url=external_url)
            await self._send_message(intent, caption, timestamp=item.timestamp // 1000)
        return event_id

    async def _handle_instagram_reel_share(self, source: 'u.User', intent: IntentAPI,
                                           item: ThreadItem) -> Optional[EventID]:
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
            prefix = "Reacted to your story"
        elif item.reel_share.type == ReelShareType.MENTION:
            if item.reel_share.mentioned_user_id == source.igpk:
                prefix = "Mentioned you in their story"
            else:
                prefix = "You mentioned them in your story"
        else:
            self.log.debug(f"Unsupported reel share type {item.reel_share.type}")
            return None
        prefix_content = TextMessageEventContent(msgtype=MessageType.NOTICE, body=prefix)
        if prefix_html:
            prefix_content.format = Format.HTML
            prefix_content.formatted_body = prefix_html
        content = TextMessageEventContent(msgtype=MessageType.TEXT, body=item.reel_share.text)
        if not content.body and isinstance(media, MediaShareItem):
            content.body = media.caption.text if media.caption else ""
        if not content.body:
            content.body = "<no caption>"
        await self._send_message(intent, prefix_content, timestamp=item.timestamp // 1000)
        if isinstance(media, ExpiredMediaItem):
            # TODO send message about expired story
            pass
        else:
            fake_item_id = f"fi.mau.instagram.reel_share.{item.user_id}.{media.pk}"
            existing = await DBMessage.get_by_item_id(fake_item_id, self.receiver)
            if existing:
                # If the user already reacted or replied to the same reel share item,
                # use a Matrix reply instead of reposting the image.
                content.set_reply(existing.mxid)
            else:
                media_event_id = await self._handle_instagram_media(source, intent, item)
                await DBMessage(mxid=media_event_id, mx_room=self.mxid, item_id=fake_item_id,
                                receiver=self.receiver, sender=media.user.pk).insert()
        return await self._send_message(intent, content, timestamp=item.timestamp // 1000)

    async def _handle_instagram_text(self, intent: IntentAPI, item: ThreadItem, text: str,
                                     ) -> EventID:
        content = TextMessageEventContent(msgtype=MessageType.TEXT, body=text)
        await self._add_instagram_reply(content, item.replied_to_message)
        return await self._send_message(intent, content, timestamp=item.timestamp // 1000)

    async def _send_instagram_unhandled(self, intent: IntentAPI, item: ThreadItem) -> EventID:
        content = TextMessageEventContent(msgtype=MessageType.NOTICE,
                                          body="Unsupported message type")
        await self._add_instagram_reply(content, item.replied_to_message)
        return await self._send_message(intent, content, timestamp=item.timestamp // 1000)

    async def _handle_instagram_location(self, intent: IntentAPI, item: ThreadItem
                                         ) -> Optional[EventID]:
        loc = item.location
        if not loc.lng or not loc.lat:
            # TODO handle somehow
            return None
        long_char = "E" if loc.lng > 0 else "W"
        lat_char = "N" if loc.lat > 0 else "S"

        body = (f"{loc.name} - {round(abs(loc.lat), 4)}° {lat_char}, "
                f"{round(abs(loc.lng), 4)}° {long_char}")
        url = f"https://www.openstreetmap.org/#map=15/{loc.lat}/{loc.lng}"

        external_url = None
        if loc.external_source == "facebook_places":
            external_url = f"https://www.facebook.com/{loc.short_name}-{loc.facebook_places_id}"

        content = LocationMessageEventContent(
            msgtype=MessageType.LOCATION, geo_uri=f"geo:{loc.lat},{loc.lng}",
            body=f"Location: {body}\n{url}", external_url=external_url)
        content["format"] = str(Format.HTML)
        content["formatted_body"] = f"Location: <a href='{url}'>{body}</a>"

        await self._add_instagram_reply(content, item.replied_to_message)

        return await self._send_message(intent, content, timestamp=item.timestamp // 1000)

    async def handle_instagram_item(self, source: 'u.User', sender: 'p.Puppet', item: ThreadItem,
                                    is_backfill: bool = False) -> None:
        try:
            await self._handle_instagram_item(source, sender, item, is_backfill)
        except Exception:
            self.log.exception("Fatal error handling Instagram item")
            self.log.trace("Item content: %s", item.serialize())

    async def _add_instagram_reply(self, content: MessageEventContent,
                                   reply_to: Optional[ThreadItem]) -> None:
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

    async def _handle_instagram_item(self, source: 'u.User', sender: 'p.Puppet', item: ThreadItem,
                                     is_backfill: bool = False) -> None:
        if not isinstance(item, ThreadItem):
            # Parsing these items failed, they should have been logged already
            return
        elif item.client_context in self._reqid_dedup:
            self.log.debug(f"Ignoring message {item.item_id} ({item.client_context}) by "
                           f"{item.user_id} as it was sent by us (client_context in dedup queue)")
        elif item.item_id in self._msgid_dedup:
            self.log.debug(f"Ignoring message {item.item_id} ({item.client_context}) by "
                           f"{item.user_id} as it was already handled (message.id in dedup queue)")
        elif await DBMessage.get_by_item_id(item.item_id, self.receiver) is not None:
            self.log.debug(f"Ignoring message {item.item_id} ({item.client_context}) by "
                           f"{item.user_id} as it was already handled (message.id in database)")
        else:
            self.log.debug(f"Starting handling of message {item.item_id} ({item.client_context}) "
                           f"by {item.user_id}")
            self._msgid_dedup.appendleft(item.item_id)
            if self.backfill_lock.locked and sender.need_backfill_invite(self):
                self.log.debug("Adding %s's default puppet to room for backfilling", sender.mxid)
                if self.is_direct:
                    await self.main_intent.invite_user(self.mxid, sender.default_mxid)
                intent = sender.default_mxid_intent
                await intent.ensure_joined(self.mxid)
                self._backfill_leave.add(intent)
            else:
                intent = sender.intent_for(self)
            event_id = None
            if item.media or item.animated_media or item.voice_media or item.visual_media:
                event_id = await self._handle_instagram_media(source, intent, item)
            elif item.location:
                event_id = await self._handle_instagram_location(intent, item)
            elif item.reel_share:
                event_id = await self._handle_instagram_reel_share(source, intent, item)
            elif item.media_share or item.story_share:
                event_id = await self._handle_instagram_media_share(source, intent, item)
            elif item.action_log:
                # These probably don't need to be bridged
                self.log.debug(f"Ignoring action log message {item.item_id}")
                return
            # TODO handle item.clip?
            if item.text:
                event_id = await self._handle_instagram_text(intent, item, item.text)
            elif item.like:
                # We handle likes as text because Matrix clients do big emoji on their own.
                event_id = await self._handle_instagram_text(intent, item, item.like)
            elif item.link:
                event_id = await self._handle_instagram_text(intent, item, item.link.text)
            handled = bool(event_id)
            if not event_id:
                self.log.debug(f"Unhandled Instagram message {item.item_id}")
                event_id = await self._send_instagram_unhandled(intent, item)

            msg = DBMessage(mxid=event_id, mx_room=self.mxid, item_id=item.item_id,
                            receiver=self.receiver, sender=sender.pk)
            await msg.insert()
            await self._send_delivery_receipt(event_id)
            if handled:
                self.log.debug(f"Handled Instagram message {item.item_id} -> {event_id}")
            else:
                self.log.debug(f"Unhandled Instagram message {item.item_id} "
                               f"(type {item.item_type} -> fallback error {event_id})")
            if is_backfill and item.reactions:
                await self._handle_instagram_reactions(msg, item.reactions.emojis)

    async def handle_instagram_remove(self, item_id: str) -> None:
        message = await DBMessage.get_by_item_id(item_id, self.receiver)
        if message is None:
            return
        await message.delete()
        sender = await p.Puppet.get_by_pk(message.sender)
        try:
            await sender.intent_for(self).redact(self.mxid, message.mxid)
        except MForbidden:
            await self.main_intent.redact(self.mxid, message.mxid)
        self.log.debug(f"Redacted {message.mxid} after Instagram unsend")

    async def _handle_instagram_reactions(self, message: DBMessage, reactions: List[Reaction]
                                          ) -> None:
        old_reactions: Dict[int, DBReaction]
        old_reactions = {reaction.ig_sender: reaction for reaction
                         in await DBReaction.get_all_by_item_id(message.item_id, self.receiver)}
        for new_reaction in reactions:
            old_reaction = old_reactions.pop(new_reaction.sender_id, None)
            if old_reaction and old_reaction.reaction == new_reaction.emoji:
                continue
            puppet = await p.Puppet.get_by_pk(new_reaction.sender_id)
            intent = puppet.intent_for(self)
            reaction_event_id = await intent.react(self.mxid, message.mxid, new_reaction.emoji)
            await self._upsert_reaction(old_reaction, intent, reaction_event_id, message,
                                        puppet, new_reaction.emoji)
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
                await self._handle_instagram_reactions(message, (item.reactions.emojis
                                                                 if item.reactions else []))

    # endregion
    # region Updating portal info

    def _get_thread_name(self, thread: Thread) -> str:
        if self.is_direct:
            if self.other_user_pk == thread.viewer_id and len(thread.users) == 0:
                return "Instagram chat with yourself"
            elif len(thread.users) == 1:
                tpl = self.config["bridge.private_chat_name_template"]
                ui = thread.users[0]
                return tpl.format(displayname=ui.full_name, id=ui.pk, username=ui.username)
            pass
        elif thread.thread_title:
            return self.config["bridge.group_chat_name_template"].format(name=thread.thread_title)
        else:
            return ""

    async def update_info(self, thread: Thread, source: 'u.User') -> None:
        changed = await self._update_name(self._get_thread_name(thread))
        changed = await self._update_participants(thread.users, source) or changed
        if changed:
            await self.update_bridge_info()
            await self.update()
        # TODO update power levels with thread.admin_user_ids

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

    async def _update_photo_from_puppet(self, puppet: 'p.Puppet') -> bool:
        if not self.private_chat_portal_meta and not self.encrypted:
            return False
        if self.avatar_set and self.avatar_url == puppet.photo_mxc:
            return False
        self.avatar_url = puppet.photo_mxc
        if self.mxid:
            try:
                await self.main_intent.set_room_avatar(self.mxid, puppet.photo_mxc)
                self.avatar_set = True
            except Exception:
                self.log.exception("Failed to set room avatar")
                self.avatar_set = False
        return True

    async def _update_participants(self, users: List[ThreadUser], source: 'u.User') -> bool:
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
                    await self.main_intent.kick_user(self.mxid, p.Puppet.get_mxid_from_id(pk),
                                                     reason="User had left this Instagram DM")

        return meta_changed

    async def _update_read_receipts(self, receipts: Dict[Union[int, str], ThreadUserLastSeenAt]
                                    ) -> None:
        for user_id, receipt in receipts.items():
            message = await DBMessage.get_by_item_id(receipt.item_id, self.receiver)
            if not message:
                continue
            puppet = await p.Puppet.get_by_pk(int(user_id), create=False)
            if not puppet:
                continue
            try:
                await puppet.intent_for(self).mark_read(message.mx_room, message.mxid)
            except Exception:
                self.log.warning(f"Failed to mark {message.mxid} in {message.mx_room} "
                                 f"as read by {puppet.intent.mxid}", exc_info=True)

    # endregion
    # region Backfilling

    async def backfill(self, source: 'u.User', is_initial: bool = False) -> None:
        limit = (self.config["bridge.backfill.initial_limit"] if is_initial
                 else self.config["bridge.backfill.missed_limit"])
        if limit == 0:
            return
        elif limit < 0:
            limit = None
        with self.backfill_lock:
            await self._backfill(source, is_initial, limit)

    async def _backfill(self, source: 'u.User', is_initial: bool, limit: int) -> None:
        self.log.debug("Backfilling history through %s", source.mxid)

        entries = await self._fetch_backfill_items(source, is_initial, limit)
        if not entries:
            self.log.debug("Didn't get any items to backfill from server")
            return

        self.log.debug("Got %d entries from server", len(entries))

        self._backfill_leave = set()
        async with NotificationDisabler(self.mxid, source):
            for entry in reversed(entries):
                sender = await p.Puppet.get_by_pk(int(entry.user_id))
                await self.handle_instagram_item(source, sender, entry, is_backfill=True)
        for intent in self._backfill_leave:
            self.log.trace("Leaving room with %s post-backfill", intent.mxid)
            await intent.leave_room(self.mxid)
        self._backfill_leave = None
        self.log.info("Backfilled %d messages through %s", len(entries), source.mxid)

    async def _fetch_backfill_items(self, source: 'u.User', is_initial: bool, limit: int
                                    ) -> List[ThreadItem]:
        items = []
        self.log.debug("Fetching up to %d messages through %s", limit, source.igpk)
        async for item in source.client.iter_thread(self.thread_id):
            if len(items) >= limit:
                self.log.debug(f"Fetched {len(items)} messages (the limit)")
                break
            elif not is_initial:
                msg = await DBMessage.get_by_item_id(item.item_id, receiver=self.receiver)
                if msg is not None:
                    self.log.debug(f"Fetched {len(items)} messages and hit a message"
                                   " that's already in the database.")
                    break
            items.append(item)
        return items

    # endregion
    # region Bridge info state event

    @property
    def bridge_info_state_key(self) -> str:
        return f"net.maunium.instagram://instagram/{self.thread_id}"

    @property
    def bridge_info(self) -> Dict[str, Any]:
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
            }
        }

    async def update_bridge_info(self) -> None:
        if not self.mxid:
            self.log.debug("Not updating bridge info: no Matrix room created")
            return
        try:
            self.log.debug("Updating bridge info...")
            await self.main_intent.send_state_event(self.mxid, StateBridge,
                                                    self.bridge_info, self.bridge_info_state_key)
            # TODO remove this once https://github.com/matrix-org/matrix-doc/pull/2346 is in spec
            await self.main_intent.send_state_event(self.mxid, StateHalfShotBridge,
                                                    self.bridge_info, self.bridge_info_state_key)
        except Exception:
            self.log.warning("Failed to update bridge info", exc_info=True)

    # endregion
    # region Creating Matrix rooms

    async def create_matrix_room(self, source: 'u.User', info: Thread) -> Optional[RoomID]:
        if self.mxid:
            try:
                await self.update_matrix_room(source, info)
            except Exception:
                self.log.exception("Failed to update portal")
            return self.mxid
        async with self._create_room_lock:
            return await self._create_matrix_room(source, info)

    def _get_invite_content(self, double_puppet: Optional['p.Puppet']) -> Dict[str, Any]:
        invite_content = {}
        if double_puppet:
            invite_content["fi.mau.will_auto_accept"] = True
        if self.is_direct:
            invite_content["is_direct"] = True
        return invite_content

    async def update_matrix_room(self, source: 'u.User', info: Thread, backfill: bool = False
                                 ) -> None:
        puppet = await p.Puppet.get_by_custom_mxid(source.mxid)
        await self.main_intent.invite_user(self.mxid, source.mxid, check_cache=True,
                                           extra_content=self._get_invite_content(puppet))
        if puppet:
            did_join = await puppet.intent.ensure_joined(self.mxid)
            if did_join and self.is_direct:
                await source.update_direct_chats({self.main_intent.mxid: [self.mxid]})

        await self.update_info(info, source)

        if backfill:
            last_msg = await DBMessage.get_by_item_id(info.last_permanent_item.item_id,
                                                      receiver=self.receiver)
            if last_msg is None:
                self.log.debug(f"Last permanent item ({info.last_permanent_item.item_id})"
                               " not found in database, starting backfilling")
                await self.backfill(source, is_initial=False)
        await self._update_read_receipts(info.last_seen_at)

        # TODO
        # up = DBUserPortal.get(source.fbid, self.fbid, self.fb_receiver)
        # if not up:
        #     in_community = await source._community_helper.add_room(source._community_id, self.mxid)
        #     DBUserPortal(user=source.fbid, portal=self.fbid, portal_receiver=self.fb_receiver,
        #                  in_community=in_community).insert()
        # elif not up.in_community:
        #     in_community = await source._community_helper.add_room(source._community_id, self.mxid)
        #     up.edit(in_community=in_community)

    async def _create_matrix_room(self, source: 'u.User', info: Thread) -> Optional[RoomID]:
        if self.mxid:
            await self.update_matrix_room(source, info)
            return self.mxid
        await self.update_info(info, source)
        self.log.debug("Creating Matrix room")
        name: Optional[str] = None
        initial_state = [{
            "type": str(StateBridge),
            "state_key": self.bridge_info_state_key,
            "content": self.bridge_info,
        }, {
            # TODO remove this once https://github.com/matrix-org/matrix-doc/pull/2346 is in spec
            "type": str(StateHalfShotBridge),
            "state_key": self.bridge_info_state_key,
            "content": self.bridge_info,
        }]
        invites = []
        if self.config["bridge.encryption.default"] and self.matrix.e2ee:
            self.encrypted = True
            initial_state.append({
                "type": "m.room.encryption",
                "content": {"algorithm": "m.megolm.v1.aes-sha2"},
            })
            if self.is_direct:
                invites.append(self.az.bot_mxid)
        if self.encrypted or self.private_chat_portal_meta or not self.is_direct:
            name = self.name
        if self.config["appservice.community_id"]:
            initial_state.append({
                "type": "m.room.related_groups",
                "content": {"groups": [self.config["appservice.community_id"]]},
            })

        # We lock backfill lock here so any messages that come between the room being created
        # and the initial backfill finishing wouldn't be bridged before the backfill messages.
        with self.backfill_lock:
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
                    self.log.warning("Failed to add bridge bot "
                                     f"to new private chat {self.mxid}")

            await self.update()
            self.log.debug(f"Matrix room created: {self.mxid}")
            self.by_mxid[self.mxid] = self

            puppet = await p.Puppet.get_by_custom_mxid(source.mxid)
            await self.main_intent.invite_user(self.mxid, source.mxid,
                                               extra_content=self._get_invite_content(puppet))
            if puppet:
                try:
                    if self.is_direct:
                        await source.update_direct_chats({self.main_intent.mxid: [self.mxid]})
                    await puppet.intent.join_room_by_id(self.mxid)
                except MatrixError:
                    self.log.debug("Failed to join custom puppet into newly created portal",
                                   exc_info=True)

            await self._update_participants(info.users, source)

            # TODO
            # in_community = await source._community_helper.add_room(source._community_id, self.mxid)
            # DBUserPortal(user=source.fbid, portal=self.fbid, portal_receiver=self.fb_receiver,
            #              in_community=in_community).upsert()

            try:
                await self.backfill(source, is_initial=True)
            except Exception:
                self.log.exception("Failed to backfill new portal")
            await self._update_read_receipts(info.last_seen_at)

        return self.mxid

    # endregion
    # region Database getters

    async def postinit(self) -> None:
        self.by_thread_id[(self.thread_id, self.receiver)] = self
        if self.mxid:
            self.by_mxid[self.mxid] = self
        self._main_intent = ((await p.Puppet.get_by_pk(self.other_user_pk)).default_mxid_intent
                             if self.other_user_pk else self.az.intent)

    async def delete(self) -> None:
        await DBMessage.delete_all(self.mxid)
        self.by_mxid.pop(self.mxid, None)
        self.mxid = None
        self.encrypted = False
        await self.update()

    async def save(self) -> None:
        await self.update()

    @classmethod
    def all_with_room(cls) -> AsyncGenerator['Portal', None]:
        return cls._db_to_portals(super().all_with_room())

    @classmethod
    def find_private_chats_with(cls, other_user: int) -> AsyncGenerator['Portal', None]:
        return cls._db_to_portals(super().find_private_chats_with(other_user))

    @classmethod
    async def _db_to_portals(cls, query: Awaitable[List['Portal']]
                             ) -> AsyncGenerator['Portal', None]:
        portals = await query
        for index, portal in enumerate(portals):
            try:
                yield cls.by_thread_id[(portal.thread_id, portal.receiver)]
            except KeyError:
                await portal.postinit()
                yield portal

    @classmethod
    @async_getter_lock
    async def get_by_mxid(cls, mxid: RoomID) -> Optional['Portal']:
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
    async def get_by_thread_id(cls, thread_id: str, *, receiver: int,
                               is_group: Optional[bool] = None,
                               other_user_pk: Optional[int] = None) -> Optional['Portal']:
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

        portal = cast(cls, await super().get_by_thread_id(thread_id, receiver=receiver,
                                                          rec_must_match=is_group is not None))
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
    async def get_by_thread(cls, thread: Thread, receiver: int) -> Optional['Portal']:
        if thread.is_group:
            receiver = 0
            other_user_pk = None
        else:
            if len(thread.users) == 0:
                other_user_pk = receiver
            else:
                other_user_pk = thread.users[0].pk
        return await cls.get_by_thread_id(thread.thread_id, receiver=receiver,
                                          is_group=thread.is_group, other_user_pk=other_user_pk)
    # endregion
