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
import struct

import paho.mqtt.client


class MQTToTClient(paho.mqtt.client.Client):
    # This is equivalent to the original _send_connect, except:
    # * the protocol ID is MQTToT.
    # * the client ID is sent without a length.
    # * all extra stuff like wills, usernames, passwords and MQTTv5 is removed.
    def _send_connect(self, keepalive):
        proto_ver = self._protocol
        protocol = b"MQTToT"

        remaining_length = 2 + len(protocol) + 1 + 1 + 2 + len(self._client_id)

        # Username, password, clean session
        connect_flags = 0x80 + 0x40 + 0x02

        command = paho.mqtt.client.CONNECT
        packet = bytearray()
        packet.append(command)

        self._pack_remaining_length(packet, remaining_length)
        packet.extend(
            struct.pack(
                f"!H{len(protocol)}sBBH",
                len(protocol),
                protocol,
                proto_ver,
                connect_flags,
                keepalive,
            )
        )
        packet.extend(self._client_id)

        self._keepalive = keepalive
        self._easy_log(
            paho.mqtt.client.MQTT_LOG_DEBUG,
            "Sending CONNECT",
        )
        return self._packet_queue(command, packet, 0, 0)
