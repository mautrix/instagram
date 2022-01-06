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

from typing import Any
from enum import Enum
from uuid import uuid4
import json


class SkywalkerSubscription:
    @staticmethod
    def direct_sub(user_id: str | int) -> str:
        return f"ig/u/v1/{user_id}"

    @staticmethod
    def live_sub(user_id: str | int) -> str:
        return f"ig/live_notification_subscribe/{user_id}"


class GraphQLQueryID(Enum):
    APP_PRESENCE = "17846944882223835"
    ASYNC_AD_SUB = "17911191835112000"
    CLIENT_CONFIG_UPDATE = "17849856529644700"
    DIRECT_STATUS = "17854499065530643"
    DIRECT_TYPING = "17867973967082385"
    LIVE_WAVE = "17882305414154951"
    INTERACTIVITY_ACTIVATE_QUESTION = "18005526940184517"
    INTERACTIVITY_REALTIME_QUESTION_SUBMISSION_STATUS = "18027779584026952"
    INTERACTIVITY_SUB = "17907616480241689"
    LIVE_REALTIME_COMMENTS = "17855344750227125"
    LIVE_TYPING_INDICATOR = "17926314067024917"
    MEDIA_FEEDBACK = "17877917527113814"
    REACT_NATIVE_OTA = "17861494672288167"
    VIDEO_CALL_CO_WATCH_CONTROL = "17878679623388956"
    VIDEO_CALL_IN_ALERT = "17878679623388956"
    VIDEO_CALL_PROTOTYPE_PUBLISH = "18031704190010162"
    VIDEO_CALL_PARTICIPANT_DELIVERY = "17977239895057311"
    ZERO_PROVISION = "17913953740109069"
    INAPP_NOTIFICATION = "17899377895239777"
    BUSINESS_DELIVERY = "17940467278199720"


everclear_subscriptions = {
    "async_ads_subscribe": GraphQLQueryID.ASYNC_AD_SUB.value,
    "inapp_notification_subscribe_default": GraphQLQueryID.INAPP_NOTIFICATION.value,
    "inapp_notification_subscribe_comment": GraphQLQueryID.INAPP_NOTIFICATION.value,
    "inapp_notification_subscribe_comment_mention_and_reply": GraphQLQueryID.INAPP_NOTIFICATION.value,
    "business_import_page_media_delivery_subscribe": GraphQLQueryID.BUSINESS_DELIVERY.value,
    "video_call_participant_state_delivery": GraphQLQueryID.VIDEO_CALL_PARTICIPANT_DELIVERY.value,
}


class GraphQLSubscription:
    @staticmethod
    def _fmt(
        query_id: GraphQLQueryID, input_params: Any, client_logged: bool | None = None
    ) -> str:
        params = {
            "input_data": input_params,
            **(
                {"%options": {"client_logged": client_logged}} if client_logged is not None else {}
            ),
        }
        return f"1/graphqlsubscriptions/{query_id.value}/{json.dumps(params)}"

    @classmethod
    def app_presence(
        cls, subscription_id: str | None = None, client_logged: bool | None = None
    ) -> str:
        return cls._fmt(
            GraphQLQueryID.APP_PRESENCE,
            input_params={"client_subscription_id": subscription_id or str(uuid4())},
            client_logged=client_logged,
        )

    @classmethod
    def async_ad(
        cls,
        user_id: str,
        subscription_id: str | None = None,
        client_logged: bool | None = None,
    ) -> str:
        return cls._fmt(
            GraphQLQueryID.ASYNC_AD_SUB,
            input_params={
                "client_subscription_id": subscription_id or str(uuid4()),
                "user_id": user_id,
            },
            client_logged=client_logged,
        )

    @classmethod
    def client_config_update(
        cls, subscription_id: str | None = None, client_logged: bool | None = None
    ) -> str:
        return cls._fmt(
            GraphQLQueryID.CLIENT_CONFIG_UPDATE,
            input_params={"client_subscription_id": subscription_id or str(uuid4())},
            client_logged=client_logged,
        )

    @classmethod
    def direct_status(
        cls, subscription_id: str | None = None, client_logged: bool | None = None
    ) -> str:
        return cls._fmt(
            GraphQLQueryID.DIRECT_STATUS,
            input_params={"client_subscription_id": subscription_id or str(uuid4())},
            client_logged=client_logged,
        )

    @classmethod
    def direct_typing(cls, user_id: str, client_logged: bool | None = None) -> str:
        return cls._fmt(
            GraphQLQueryID.DIRECT_TYPING,
            input_params={"user_id": user_id},
            client_logged=client_logged,
        )

    @classmethod
    def ig_live_wave(
        cls,
        broadcast_id: str,
        receiver_id: str,
        subscription_id: str | None = None,
        client_logged: bool | None = None,
    ) -> str:
        return cls._fmt(
            GraphQLQueryID.LIVE_WAVE,
            input_params={
                "client_subscription_id": subscription_id or str(uuid4()),
                "broadcast_id": broadcast_id,
                "receiver_id": receiver_id,
            },
            client_logged=client_logged,
        )

    @classmethod
    def interactivity_activate_question(
        cls,
        broadcast_id: str,
        subscription_id: str | None = None,
        client_logged: bool | None = None,
    ) -> str:
        return cls._fmt(
            GraphQLQueryID.INTERACTIVITY_ACTIVATE_QUESTION,
            input_params={
                "client_subscription_id": subscription_id or str(uuid4()),
                "broadcast_id": broadcast_id,
            },
            client_logged=client_logged,
        )

    @classmethod
    def interactivity_realtime_question_submissions_status(
        cls,
        broadcast_id: str,
        subscription_id: str | None = None,
        client_logged: bool | None = None,
    ) -> str:
        return cls._fmt(
            GraphQLQueryID.INTERACTIVITY_REALTIME_QUESTION_SUBMISSION_STATUS,
            input_params={
                "client_subscription_id": subscription_id or str(uuid4()),
                "broadcast_id": broadcast_id,
            },
            client_logged=client_logged,
        )

    @classmethod
    def interactivity(
        cls,
        broadcast_id: str,
        subscription_id: str | None = None,
        client_logged: bool | None = None,
    ) -> str:
        return cls._fmt(
            GraphQLQueryID.INTERACTIVITY_SUB,
            input_params={
                "client_subscription_id": subscription_id or str(uuid4()),
                "broadcast_id": broadcast_id,
            },
            client_logged=client_logged,
        )

    @classmethod
    def live_realtime_comments(
        cls,
        broadcast_id: str,
        subscription_id: str | None = None,
        client_logged: bool | None = None,
    ) -> str:
        return cls._fmt(
            GraphQLQueryID.LIVE_REALTIME_COMMENTS,
            input_params={
                "client_subscription_id": subscription_id or str(uuid4()),
                "broadcast_id": broadcast_id,
            },
            client_logged=client_logged,
        )

    @classmethod
    def live_realtime_typing_indicator(
        cls,
        broadcast_id: str,
        subscription_id: str | None = None,
        client_logged: bool | None = None,
    ) -> str:
        return cls._fmt(
            GraphQLQueryID.LIVE_TYPING_INDICATOR,
            input_params={
                "client_subscription_id": subscription_id or str(uuid4()),
                "broadcast_id": broadcast_id,
            },
            client_logged=client_logged,
        )

    @classmethod
    def media_feedback(
        cls,
        feedback_id: str,
        subscription_id: str | None = None,
        client_logged: bool | None = None,
    ) -> str:
        return cls._fmt(
            GraphQLQueryID.MEDIA_FEEDBACK,
            input_params={
                "client_subscription_id": subscription_id or str(uuid4()),
                "feedback_id": feedback_id,
            },
            client_logged=client_logged,
        )

    @classmethod
    def react_native_ota_update(
        cls,
        build_number: str,
        subscription_id: str | None = None,
        client_logged: bool | None = None,
    ) -> str:
        return cls._fmt(
            GraphQLQueryID.REACT_NATIVE_OTA,
            input_params={
                "client_subscription_id": subscription_id or str(uuid4()),
                "build_number": build_number,
            },
            client_logged=client_logged,
        )

    @classmethod
    def video_call_co_watch_control(
        cls,
        video_call_id: str,
        subscription_id: str | None = None,
        client_logged: bool | None = None,
    ) -> str:
        return cls._fmt(
            GraphQLQueryID.VIDEO_CALL_CO_WATCH_CONTROL,
            input_params={
                "client_subscription_id": subscription_id or str(uuid4()),
                "video_call_id": video_call_id,
            },
            client_logged=client_logged,
        )

    @classmethod
    def video_call_in_call_alert(
        cls,
        video_call_id: str,
        subscription_id: str | None = None,
        client_logged: bool | None = None,
    ) -> str:
        return cls._fmt(
            GraphQLQueryID.VIDEO_CALL_IN_ALERT,
            input_params={
                "client_subscription_id": subscription_id or str(uuid4()),
                "video_call_id": video_call_id,
            },
            client_logged=client_logged,
        )

    @classmethod
    def video_call_prototype_publish(
        cls,
        video_call_id: str,
        subscription_id: str | None = None,
        client_logged: bool | None = None,
    ) -> str:
        return cls._fmt(
            GraphQLQueryID.VIDEO_CALL_PROTOTYPE_PUBLISH,
            input_params={
                "client_subscription_id": subscription_id or str(uuid4()),
                "video_call_id": video_call_id,
            },
            client_logged=client_logged,
        )

    @classmethod
    def zero_provision(
        cls,
        device_id: str,
        subscription_id: str | None = None,
        client_logged: bool | None = None,
    ) -> str:
        return cls._fmt(
            GraphQLQueryID.ZERO_PROVISION,
            input_params={
                "client_subscription_id": subscription_id or str(uuid4()),
                "device_id": device_id,
            },
            client_logged=client_logged,
        )


_topic_map: dict[str, str] = {
    "/pp": "34",  # unknown
    "/ig_sub_iris": "134",
    "/ig_sub_iris_response": "135",
    "/ig_message_sync": "146",
    "/ig_send_message": "132",
    "/ig_send_message_response": "133",
    "/ig_realtime_sub": "149",
    "/pubsub": "88",
    "/t_fs": "102",  # Foreground state
    "/graphql": "9",
    "/t_region_hint": "150",
    "/mqtt_health_stats": "/mqtt_health_stats",
    "179": "179",  # also unknown
}

_reverse_topic_map: dict[str, str] = {value: key for key, value in _topic_map.items()}


class RealtimeTopic(Enum):
    SUB_IRIS = "/ig_sub_iris"
    SUB_IRIS_RESPONSE = "/ig_sub_iris_response"
    MESSAGE_SYNC = "/ig_message_sync"
    SEND_MESSAGE = "/ig_send_message"
    SEND_MESSAGE_RESPONSE = "/ig_send_message_response"
    REALTIME_SUB = "/ig_realtime_sub"
    PUBSUB = "/pubsub"
    FOREGROUND_STATE = "/t_fs"
    GRAPHQL = "/graphql"
    REGION_HINT = "/t_region_hint"
    MQTT_HEALTH_STATS = "/mqtt_health_stats"
    UNKNOWN_PP = "/pp"
    UNKNOWN_179 = "179"

    @property
    def encoded(self) -> str:
        return _topic_map[self.value]

    @staticmethod
    def decode(val: str) -> RealtimeTopic:
        return RealtimeTopic(_reverse_topic_map[val])
