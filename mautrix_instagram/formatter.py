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

from typing import NamedTuple

from mautrix.types import MessageEventContent, UserID
from mautrix.util.formatter import (
    EntityString,
    EntityType,
    MarkdownString,
    MatrixParser as BaseMatrixParser,
    SimpleEntity,
)

from . import puppet as pu, user as u


class SendParams(NamedTuple):
    text: str
    mentions: list[int]


class FacebookFormatString(EntityString[SimpleEntity, EntityType], MarkdownString):
    def format(self, entity_type: EntityType, **kwargs) -> FacebookFormatString:
        prefix = suffix = ""
        if entity_type == EntityType.USER_MENTION:
            self.entities.append(
                SimpleEntity(
                    type=entity_type,
                    offset=0,
                    length=len(self.text),
                    extra_info={"igpk": kwargs["igpk"]},
                )
            )
            return self
        elif entity_type == EntityType.BOLD:
            prefix = suffix = "*"
        elif entity_type == EntityType.ITALIC:
            prefix = suffix = "_"
        elif entity_type == EntityType.STRIKETHROUGH:
            prefix = suffix = "~"
        elif entity_type == EntityType.URL:
            if kwargs["url"] != self.text:
                suffix = f" ({kwargs['url']})"
        elif entity_type == EntityType.PREFORMATTED:
            prefix = f"```{kwargs['language']}\n"
            suffix = "\n```"
        elif entity_type == EntityType.INLINE_CODE:
            prefix = suffix = "`"
        elif entity_type == EntityType.BLOCKQUOTE:
            children = self.trim().split("\n")
            children = [child.prepend("> ") for child in children]
            return self.join(children, "\n")
        elif entity_type == EntityType.HEADER:
            prefix = "#" * kwargs["size"] + " "
        else:
            return self

        self._offset_entities(len(prefix))
        self.text = f"{prefix}{self.text}{suffix}"
        return self


class MatrixParser(BaseMatrixParser[FacebookFormatString]):
    fs = FacebookFormatString

    async def user_pill_to_fstring(
        self, msg: FacebookFormatString, user_id: UserID
    ) -> FacebookFormatString | None:
        entity = await u.User.get_by_mxid(user_id, create=False)
        if not entity:
            entity = await pu.Puppet.get_by_mxid(user_id, create=False)
        if entity and entity.igpk and entity.username:
            return FacebookFormatString(f"@{entity.username}").format(
                EntityType.USER_MENTION, igpk=entity.igpk
            )
        return msg


async def matrix_to_instagram(content: MessageEventContent) -> SendParams:
    parsed = await MatrixParser().parse(content["formatted_body"])
    return SendParams(
        text=parsed.text,
        mentions=[mention.extra_info["igpk"] for mention in parsed.entities],
    )
