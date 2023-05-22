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

from typing import Any, NamedTuple
import os

from mautrix.bridge.config import BaseBridgeConfig
from mautrix.client import Client
from mautrix.types import UserID
from mautrix.util.config import ConfigUpdateHelper, ForbiddenDefault, ForbiddenKey

Permissions = NamedTuple("Permissions", relay=bool, user=bool, admin=bool, level=str)


class Config(BaseBridgeConfig):
    @property
    def forbidden_defaults(self) -> list[ForbiddenDefault]:
        return [
            *super().forbidden_defaults,
            ForbiddenDefault("appservice.database", "postgres://username:password@hostname/db"),
            ForbiddenDefault("bridge.permissions", ForbiddenKey("example.com")),
        ]

    def do_update(self, helper: ConfigUpdateHelper) -> None:
        super().do_update(helper)
        copy, copy_dict, base = helper

        copy("metrics.enabled")
        copy("metrics.listen_port")

        copy("instagram.device_seed")
        if base["instagram.device_seed"] == "generate":
            base["instagram.device_seed"] = self._new_token()

        copy("bridge.username_template")
        copy("bridge.displayname_template")
        copy("bridge.private_chat_name_template")
        copy("bridge.group_chat_name_template")

        copy("bridge.displayname_max_length")

        copy("bridge.max_startup_thread_sync_count")
        copy("bridge.sync_with_custom_puppets")
        copy("bridge.sync_direct_chat_list")
        copy("bridge.double_puppet_server_map")
        copy("bridge.double_puppet_allow_discovery")
        copy("bridge.login_shared_secret_map")
        copy("bridge.federate_rooms")
        copy("bridge.backfill.enable_initial")
        copy("bridge.backfill.enable")
        copy("bridge.backfill.msc2716")
        copy("bridge.backfill.double_puppet_backfill")
        if "bridge.initial_chat_sync" in self:
            initial_chat_sync = self["bridge.initial_chat_sync"]
            base["bridge.backfill.max_conversations"] = self.get(
                "bridge.backfill.max_conversations", initial_chat_sync
            )
        else:
            copy("bridge.backfill.max_conversations")
        copy("bridge.backfill.min_sync_thread_delay")
        copy("bridge.backfill.unread_hours_threshold")
        copy("bridge.backfill.backoff.thread_list")
        copy("bridge.backfill.backoff.message_history")
        copy("bridge.backfill.incremental.max_pages")
        copy("bridge.backfill.incremental.max_total_pages")
        copy("bridge.backfill.incremental.page_delay")
        copy("bridge.backfill.incremental.post_batch_delay")
        copy("bridge.periodic_reconnect.interval")
        copy("bridge.periodic_reconnect.resync")
        copy("bridge.periodic_reconnect.always")
        if isinstance(self.get("bridge.private_chat_portal_meta", "default"), bool):
            base["bridge.private_chat_portal_meta"] = (
                "always" if self["bridge.private_chat_portal_meta"] else "default"
            )
        else:
            copy("bridge.private_chat_portal_meta")
            if base["bridge.private_chat_portal_meta"] not in ("default", "always", "never"):
                base["bridge.private_chat_portal_meta"] = "default"
        copy("bridge.delivery_receipts")
        copy("bridge.delivery_error_reports")
        copy("bridge.message_status_events")
        copy("bridge.resend_bridge_info")
        copy("bridge.unimportant_bridge_notices")
        copy("bridge.disable_bridge_notices")
        copy("bridge.caption_in_message")
        copy("bridge.bridge_notices")
        copy("bridge.bridge_matrix_typing")

        copy("bridge.provisioning.enabled")
        copy("bridge.provisioning.prefix")
        copy("bridge.provisioning.shared_secret")
        if base["bridge.provisioning.shared_secret"] == "generate":
            base["bridge.provisioning.shared_secret"] = self._new_token()
        copy("bridge.provisioning.segment_key")
        copy("bridge.provisioning.segment_user_id")

        copy("bridge.command_prefix")

        copy("bridge.get_proxy_api_url")
        copy("bridge.use_proxy_for_media")

        copy_dict("bridge.permissions")

    def _get_permissions(self, key: str) -> Permissions:
        level = self["bridge.permissions"].get(key, "")
        admin = level == "admin"
        user = level == "user" or admin
        relay = level == "relay" or user
        return Permissions(relay, user, admin, level)

    def get_permissions(self, mxid: UserID) -> Permissions:
        permissions = self["bridge.permissions"]
        if mxid in permissions:
            return self._get_permissions(mxid)

        _, homeserver = Client.parse_user_id(mxid)
        if homeserver in permissions:
            return self._get_permissions(homeserver)

        return self._get_permissions("*")
