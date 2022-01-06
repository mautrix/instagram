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
from __future__ import annotations

import io

from .type import TType


class ThriftReader(io.BytesIO):
    prev_field_id: int
    stack: list[int]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.prev_field_id = 0
        self.stack = []

    def _push_stack(self) -> None:
        self.stack.append(self.prev_field_id)
        self.prev_field_id = 0

    def _pop_stack(self) -> None:
        if self.stack:
            self.prev_field_id = self.stack.pop()

    def _read_byte(self, signed: bool = False) -> int:
        return int.from_bytes(self.read(1), "big", signed=signed)

    @staticmethod
    def _from_zigzag(val: int) -> int:
        return (val >> 1) ^ -(val & 1)

    def read_small_int(self) -> int:
        return self._from_zigzag(self.read_varint())

    def read_varint(self) -> int:
        shift = 0
        result = 0
        while True:
            byte = self._read_byte()
            result |= (byte & 0x7F) << shift
            if (byte & 0x80) == 0:
                break
            shift += 7
        return result

    def read_field(self) -> TType:
        byte = self._read_byte()
        if byte == 0:
            return TType.STOP
        delta = (byte & 0xF0) >> 4
        if delta == 0:
            self.prev_field_id = self._from_zigzag(self.read_varint())
        else:
            self.prev_field_id += delta
        return TType(byte & 0x0F)
