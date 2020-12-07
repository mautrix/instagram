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
from typing import (Dict, Tuple, Optional, List, Deque, Set, Any, Union, AsyncGenerator,
                    Awaitable, NamedTuple, TYPE_CHECKING, cast)
from collections import deque
from uuid import uuid4
import mimetypes
import asyncio

import magic
from yarl import URL

from mauigpapi.types import (Thread, ThreadUser, ThreadItem, RegularMediaItem, MediaType,
                             ReactionStatus)
from mautrix.appservice import AppService, IntentAPI
from mautrix.bridge import BasePortal, NotificationDisabler
from mautrix.types import (EventID, MessageEventContent, RoomID, EventType, MessageType, ImageInfo,
                           VideoInfo, MediaMessageEventContent, TextMessageEventContent,
                           ContentURI, EncryptedFile)
from mautrix.errors import MatrixError, MForbidden
from mautrix.util.simple_lock import SimpleLock
from mautrix.util.network_retry import call_with_net_retry

from .db import Portal as DBPortal, Message as DBMessage, Reaction as DBReaction
from .config import Config
from . import user as u, puppet as p, matrix as m

if TYPE_CHECKING:
    from .__main__ import InstagramBridge

try:
    from mautrix.crypto.attachments import encrypt_attachment, decrypt_attachment
except ImportError:
    encrypt_attachment = decrypt_attachment = None

StateBridge = EventType.find("m.bridge", EventType.Class.STATE)
StateHalfShotBridge = EventType.find("uk.half-shot.bridge", EventType.Class.STATE)
ReuploadedMediaInfo = NamedTuple('ReuploadedMediaInfo', mxc=Optional[ContentURI], url=str,
                                 decryption_info=Optional[EncryptedFile], msgtype=MessageType,
                                 file_name=str, info=Union[ImageInfo, VideoInfo])


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

    def __init__(self, thread_id: str, receiver: int, other_user_pk: Optional[int],
                 mxid: Optional[RoomID] = None, name: Optional[str] = None, encrypted: bool = False
                 ) -> None:
        super().__init__(thread_id, receiver, other_user_pk, mxid, name, encrypted)
        self._create_room_lock = asyncio.Lock()
        self.log = self.log.getChild(thread_id)
        self._msgid_dedup = deque(maxlen=100)
        self._reaction_dedup = deque(maxlen=100)
        self._reqid_dedup = set()
        self._last_participant_update = set()

        self.backfill_lock = SimpleLock("Waiting for backfilling to finish before handling %s",
                                        log=self.log)
        self._main_intent = None
        self._reaction_lock = asyncio.Lock()

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

    async def _upsert_reaction(self, existing: DBReaction, intent: IntentAPI, mxid: EventID,
                               message: DBMessage, sender: Union['u.User', 'p.Puppet'],
                               reaction: str) -> None:
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

    async def handle_matrix_message(self, sender: 'u.User', message: MessageEventContent,
                                    event_id: EventID) -> None:
        if not sender.client:
            self.log.debug(f"Ignoring message {event_id} as user is not connected")
            return
        elif ((message.get(self.bridge.real_user_content_key,
                           False) and await p.Puppet.get_by_custom_mxid(sender.mxid))):
            self.log.debug(f"Ignoring puppet-sent message by confirmed puppet user {sender.mxid}")
            return
        request_id = str(uuid4())
        self._reqid_dedup.add(request_id)
        if message.msgtype in (MessageType.EMOTE, MessageType.TEXT):
            text = message.body
            if message.msgtype == MessageType.EMOTE:
                text = f"/me {text}"
            resp = await sender.mqtt.send_text(self.thread_id, text=text,
                                               client_context=request_id)
        elif message.msgtype.is_media:
            if message.file and decrypt_attachment:
                data = await self.main_intent.download_media(message.file.url)
                data = decrypt_attachment(data, message.file.key.key,
                                          message.file.hashes.get("sha256"), message.file.iv)
            else:
                data = await self.main_intent.download_media(message.url)
            mime_type = message.info.mimetype or magic.from_buffer(data, mime=True)
            if mime_type == "image/jpeg":
                upload_resp = await sender.client.upload_jpeg_photo(data)
                # TODO I don't think this works
                resp = await sender.mqtt.send_media(self.thread_id, upload_resp.upload_id,
                                                    client_context=request_id)
            else:
                # TODO add link to media for unsupported file types
                return
        else:
            return
        if resp.status != "ok":
            self.log.warning(f"Failed to handle {event_id}: {resp}")
        else:
            self._msgid_dedup.appendleft(resp.payload.item_id)
            await DBMessage(mxid=event_id, mx_room=self.mxid, item_id=resp.payload.item_id,
                            receiver=self.receiver, sender=sender.igpk).insert()
            self._reqid_dedup.remove(request_id)
            await self._send_delivery_receipt(event_id)
            self.log.debug(f"Handled Matrix message {event_id} -> {resp.payload.item_id}")

    async def handle_matrix_reaction(self, sender: 'u.User', event_id: EventID,
                                     reacting_to: EventID, emoji: str) -> None:
        message = await DBMessage.get_by_mxid(reacting_to, self.mxid)
        if not message:
            self.log.debug(f"Ignoring reaction to unknown event {reacting_to}")
            return

        existing = await DBReaction.get_by_item_id(message.item_id, message.receiver, sender.igpk)
        if existing and existing.reaction == emoji:
            return

        dedup_id = (message.item_id, sender.igpk, emoji)
        self._reaction_dedup.appendleft(dedup_id)
        async with self._reaction_lock:
            # TODO check response?
            await sender.mqtt.send_reaction(self.thread_id, item_id=message.item_id, emoji=emoji)
            await self._upsert_reaction(existing, self.main_intent, event_id, message, sender,
                                        emoji)
            self.log.trace(f"{sender.mxid} reacted to {message.item_id} with {emoji}")
        await self._send_delivery_receipt(event_id)

    async def handle_matrix_redaction(self, sender: 'u.User', event_id: EventID,
                                      redaction_event_id: EventID) -> None:
        if not self.mxid:
            return

        # TODO implement
        reaction = await DBReaction.get_by_mxid(event_id, self.mxid)
        if reaction:
            try:
                await reaction.delete()
                await sender.mqtt.send_reaction(self.thread_id, item_id=reaction.ig_item_id,
                                                reaction_status=ReactionStatus.DELETED, emoji="")
                await self._send_delivery_receipt(redaction_event_id)
                self.log.trace(f"Removed {reaction} after Matrix redaction")
            except Exception:
                self.log.exception("Removing reaction failed")
            return

        message = await DBMessage.get_by_mxid(event_id, self.mxid)
        if message:
            try:
                await message.delete()
                await sender.client.delete_item(self.thread_id, message.item_id)
                self.log.trace(f"Removed {message} after Matrix redaction")
            except Exception:
                self.log.exception("Removing message failed")

    async def handle_matrix_leave(self, user: 'u.User') -> None:
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
                                        intent: IntentAPI) -> Optional[ReuploadedMediaInfo]:
        if media.media_type == MediaType.IMAGE:
            image = media.best_image
            url = image.url
            msgtype = MessageType.IMAGE
            info = ImageInfo(height=image.height, width=image.width)
        elif media.media_type == MediaType.VIDEO:
            video = media.best_video
            url = video.url
            msgtype = MessageType.VIDEO
            info = VideoInfo(height=video.height, width=video.width)
        else:
            return None
        resp = await source.client.raw_http_get(URL(url))
        data = await resp.read()
        info.mime_type = resp.headers["Content-Type"] or magic.from_buffer(data, mime=True)
        info.size = len(data)
        file_name = f"{msgtype.value[2:]}{mimetypes.guess_extension(info.mime_type)}"

        upload_mime_type = info.mime_type
        upload_file_name = file_name
        decryption_info = None
        if self.encrypted and encrypt_attachment:
            data, decryption_info = encrypt_attachment(data)
            upload_mime_type = "application/octet-stream"
            upload_file_name = None

        mxc = await call_with_net_retry(intent.upload_media, data, mime_type=upload_mime_type,
                                        filename=upload_file_name, _action="upload media")

        if decryption_info:
            decryption_info.url = mxc
            mxc = None

        return ReuploadedMediaInfo(mxc=mxc, url=url, decryption_info=decryption_info,
                                   file_name=file_name, msgtype=msgtype, info=info)

    async def _handle_instagram_media(self, source: 'u.User', intent: IntentAPI, item: ThreadItem
                                      ) -> Optional[EventID]:
        reuploaded = await self._reupload_instagram_media(source, item.media, intent)
        if not reuploaded:
            self.log.debug(f"Unsupported media type: {item.media}")
            return None
        content = MediaMessageEventContent(body=reuploaded.file_name, external_url=reuploaded.url,
                                           url=reuploaded.mxc, file=reuploaded.decryption_info,
                                           info=reuploaded.info, msgtype=reuploaded.msgtype)
        return await self._send_message(intent, content, timestamp=item.timestamp // 1000)

    async def _handle_instagram_text(self, intent: IntentAPI, item: ThreadItem) -> EventID:
        content = TextMessageEventContent(msgtype=MessageType.TEXT, body=item.text)
        return await self._send_message(intent, content, timestamp=item.timestamp // 1000)

    async def handle_instagram_item(self, source: 'u.User', sender: 'p.Puppet', item: ThreadItem
                                    ) -> None:
        if item.client_context in self._reqid_dedup:
            self.log.debug(f"Ignoring message {item.item_id} by {item.user_id}"
                           " as it was sent by us (client_context in dedup queue)")
        elif item.item_id in self._msgid_dedup:
            self.log.debug(f"Ignoring message {item.item_id} by {item.user_id}"
                           " as it was already handled (message.id in dedup queue)")
        elif await DBMessage.get_by_item_id(item.item_id, self.receiver) is not None:
            self.log.debug(f"Ignoring message {item.item_id} by {item.user_id}"
                           " as it was already handled (message.id found in database)")
        else:
            self._msgid_dedup.appendleft(item.item_id)
            intent = sender.intent_for(self)
            event_id = None
            if item.media:
                event_id = await self._handle_instagram_media(source, intent, item)
            elif item.text:
                event_id = await self._handle_instagram_text(intent, item)
            # TODO handle attachments and reactions
            if event_id:
                await DBMessage(mxid=event_id, mx_room=self.mxid, item_id=item.item_id,
                                receiver=self.receiver, sender=sender.pk).insert()
                await self._send_delivery_receipt(event_id)
                self.log.debug(f"Handled Instagram message {item.item_id} -> {event_id}")
            else:
                self.log.debug(f"Unhandled Instagram message {item.item_id}")

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

    # endregion
    # region Updating portal info

    async def update_info(self, thread: Thread) -> None:
        changed = await self._update_name(thread.thread_title)
        if changed:
            await self.update_bridge_info()
            await self.update()
        await self._update_participants(thread.users)
        # TODO update power levels with thread.admin_user_ids

    async def _update_name(self, name: str) -> bool:
        if self.name != name:
            self.name = name
            if self.mxid:
                await self.main_intent.set_room_name(self.mxid, name)
            return True
        return False

    async def _update_participants(self, users: List[ThreadUser]) -> None:
        if not self.mxid:
            return

        # Make sure puppets who should be here are here
        for user in users:
            puppet = await p.Puppet.get_by_pk(user.pk)
            await puppet.update_info(user)
            await puppet.intent_for(self).ensure_joined(self.mxid)

        # Kick puppets who shouldn't be here
        current_members = {int(user.pk) for user in users}
        for user_id in await self.main_intent.get_room_members(self.mxid):
            pk = p.Puppet.get_id_from_mxid(user_id)
            if pk and pk not in current_members:
                await self.main_intent.kick_user(self.mxid, p.Puppet.get_mxid_from_id(pk),
                                                 reason="User had left this Instagram DM")

    # endregion
    # region Backfilling

    async def backfill(self, source: 'u.User', is_initial: bool = False) -> None:
        if not is_initial:
            raise RuntimeError("Non-initial backfilling is not supported")
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

        backfill_leave = await self._invite_own_puppet_backfill(source)
        async with NotificationDisabler(self.mxid, source):
            for entry in reversed(entries):
                sender = await p.Puppet.get_by_pk(int(entry.user_id))
                await self.handle_instagram_item(source, sender, entry)
        for intent in backfill_leave:
            self.log.trace("Leaving room with %s post-backfill", intent.mxid)
            await intent.leave_room(self.mxid)
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

    async def _invite_own_puppet_backfill(self, source: 'u.User') -> Set[IntentAPI]:
        backfill_leave = set()
        # TODO we should probably only invite the puppet when needed
        if self.config["bridge.backfill.invite_own_puppet"]:
            self.log.debug("Adding %s's default puppet to room for backfilling", source.mxid)
            sender = await p.Puppet.get_by_pk(source.igpk)
            await self.main_intent.invite_user(self.mxid, sender.default_mxid)
            await sender.default_mxid_intent.join_room_by_id(self.mxid)
            backfill_leave.add(sender.default_mxid_intent)
        return backfill_leave

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
                await self._update_matrix_room(source, info)
            except Exception:
                self.log.exception("Failed to update portal")
            return self.mxid
        async with self._create_room_lock:
            return await self._create_matrix_room(source, info)

    async def _update_matrix_room(self, source: 'u.User', info: Thread) -> None:
        await self.main_intent.invite_user(self.mxid, source.mxid, check_cache=True)
        puppet = await p.Puppet.get_by_custom_mxid(source.mxid)
        if puppet:
            did_join = await puppet.intent.ensure_joined(self.mxid)
            if did_join and self.is_direct:
                await source.update_direct_chats({self.main_intent.mxid: [self.mxid]})

        await self.update_info(info)

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
            await self._update_matrix_room(source, info)
            return self.mxid
        await self.update_info(info)
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
        invites = [source.mxid]
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
            self.mxid = await self.main_intent.create_room(name=name, is_direct=self.is_direct,
                                                           initial_state=initial_state,
                                                           invitees=invites)
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
            if not self.is_direct:
                await self._update_participants(info.users)

            puppet = await p.Puppet.get_by_custom_mxid(source.mxid)
            if puppet:
                try:
                    await puppet.intent.join_room_by_id(self.mxid)
                    if self.is_direct:
                        await source.update_direct_chats({self.main_intent.mxid: [self.mxid]})
                except MatrixError:
                    self.log.debug("Failed to join custom puppet into newly created portal",
                                   exc_info=True)

            # TODO
            # in_community = await source._community_helper.add_room(source._community_id, self.mxid)
            # DBUserPortal(user=source.fbid, portal=self.fbid, portal_receiver=self.fb_receiver,
            #              in_community=in_community).upsert()

            try:
                await self.backfill(source, is_initial=True)
            except Exception:
                self.log.exception("Failed to backfill new portal")

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
    async def get_by_thread_id(cls, thread_id: str, receiver: int,
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

        portal = cast(cls, await super().get_by_thread_id(thread_id, receiver,
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
            other_user_pk = thread.users[0].pk
        return await cls.get_by_thread_id(thread.thread_id, receiver, is_group=thread.is_group,
                                          other_user_pk=other_user_pk)
    # endregion
