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

from typing import TYPE_CHECKING

from mautrix.bridge import BaseMatrixHandler
from mautrix.types import (
    Event,
    EventID,
    EventType,
    PresenceEvent,
    ReactionEvent,
    ReactionEventContent,
    ReceiptEvent,
    RedactionEvent,
    RelationType,
    RoomID,
    SingleReceiptEventContent,
    TypingEvent,
    UserID,
)
from mautrix.util.message_send_checkpoint import MessageSendCheckpointStatus

from . import portal as po, user as u
from .db import Message as DBMessage

if TYPE_CHECKING:
    from .__main__ import InstagramBridge


class MatrixHandler(BaseMatrixHandler):
    def __init__(self, bridge: "InstagramBridge") -> None:
        prefix, suffix = bridge.config["bridge.username_template"].format(userid=":").split(":")
        homeserver = bridge.config["homeserver.domain"]
        self.user_id_prefix = f"@{prefix}"
        self.user_id_suffix = f"{suffix}:{homeserver}"

        super().__init__(bridge=bridge)

    async def send_welcome_message(self, room_id: RoomID, inviter: u.User) -> None:
        await super().send_welcome_message(room_id, inviter)
        if not inviter.notice_room:
            inviter.notice_room = room_id
            await inviter.update()
            await self.az.intent.send_notice(
                room_id, "This room has been marked as your Instagram bridge notice room."
            )

    async def handle_leave(self, room_id: RoomID, user_id: UserID, event_id: EventID) -> None:
        portal = await po.Portal.get_by_mxid(room_id)
        if not portal:
            return

        user = await u.User.get_by_mxid(user_id, create=False)
        if not user:
            return

        await portal.handle_matrix_leave(user)

    @staticmethod
    async def handle_redaction(
        room_id: RoomID, user_id: UserID, event_id: EventID, redaction_event_id: EventID
    ) -> None:
        user = await u.User.get_by_mxid(user_id)
        if not user:
            return

        portal = await po.Portal.get_by_mxid(room_id)
        if not portal:
            user.send_remote_checkpoint(
                MessageSendCheckpointStatus.PERM_FAILURE,
                event_id,
                room_id,
                EventType.ROOM_REDACTION,
                error=Exception("Ignoring redaction event in non-portal room"),
            )
            return

        await portal.handle_matrix_redaction(user, event_id, redaction_event_id)

    @classmethod
    async def handle_reaction(
        cls, room_id: RoomID, user_id: UserID, event_id: EventID, content: ReactionEventContent
    ) -> None:
        if content.relates_to.rel_type != RelationType.ANNOTATION:
            cls.log.debug(
                f"Ignoring m.reaction event in {room_id} from {user_id} with unexpected "
                f"relation type {content.relates_to.rel_type}"
            )
            return
        user = await u.User.get_by_mxid(user_id)
        if not user:
            return

        portal = await po.Portal.get_by_mxid(room_id)
        if not portal:
            return

        await portal.handle_matrix_reaction(
            user, event_id, content.relates_to.event_id, content.relates_to.key
        )

    async def handle_read_receipt(
        self,
        user: u.User,
        portal: po.Portal,
        event_id: EventID,
        data: SingleReceiptEventContent,
    ) -> None:
        message = await DBMessage.get_by_mxid(event_id, portal.mxid)
        if not message or message.is_internal:
            # Message might actually be reaction - mark all as read
            message = await DBMessage.get_last(portal.mxid)
        if not message:
            return
        user.log.debug(f"Marking {message.item_id} in {portal.thread_id} as read")
        await user.mqtt.mark_seen(portal.thread_id, message.item_id)

    @staticmethod
    async def handle_typing(room_id: RoomID, typing: list[UserID]) -> None:
        portal = await po.Portal.get_by_mxid(room_id)
        if not portal:
            return
        await portal.handle_matrix_typing(set(typing))

    async def handle_event(self, evt: Event) -> None:
        if evt.type == EventType.ROOM_REDACTION:
            evt: RedactionEvent
            await self.handle_redaction(evt.room_id, evt.sender, evt.redacts, evt.event_id)
        elif evt.type == EventType.REACTION:
            evt: ReactionEvent
            await self.handle_reaction(evt.room_id, evt.sender, evt.event_id, evt.content)

    async def handle_ephemeral_event(
        self, evt: ReceiptEvent | PresenceEvent | TypingEvent
    ) -> None:
        if evt.type == EventType.TYPING:
            await self.handle_typing(evt.room_id, evt.content.user_ids)
        else:
            await super().handle_ephemeral_event(evt)
