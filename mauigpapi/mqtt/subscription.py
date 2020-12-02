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
from typing import Any, Optional, Union
from enum import Enum
from uuid import uuid4
import json


class SkywalkerSubscription:
    @staticmethod
    def direct_sub(user_id: Union[str, int]) -> str:
        return f"ig/u/v1/{user_id}"

    @staticmethod
    def live_sub(user_id: Union[str, int]) -> str:
        return f"ig/live_notification_subscribe/{user_id}"


class GraphQLQueryID(Enum):
    appPresence = '17846944882223835'
    asyncAdSub = '17911191835112000'
    clientConfigUpdate = '17849856529644700'
    directStatus = '17854499065530643'
    directTyping = '17867973967082385'
    liveWave = '17882305414154951'
    interactivityActivateQuestion = '18005526940184517'
    interactivityRealtimeQuestionSubmissionsStatus = '18027779584026952'
    interactivitySub = '17907616480241689'
    liveRealtimeComments = '17855344750227125'
    liveTypingIndicator = '17926314067024917'
    mediaFeedback = '17877917527113814'
    reactNativeOTA = '17861494672288167'
    videoCallCoWatchControl = '17878679623388956'
    videoCallInAlert = '17878679623388956'
    videoCallPrototypePublish = '18031704190010162'
    videoCallParticipantDelivery = '17977239895057311'
    zeroProvision = '17913953740109069'
    inappNotification = '17899377895239777'
    businessDelivery = '17940467278199720'


everclear_subscriptions = {
    "async_ads_subscribe": GraphQLQueryID.asyncAdSub.value,
    "inapp_notification_subscribe_default": GraphQLQueryID.inappNotification.value,
    "inapp_notification_subscribe_comment": GraphQLQueryID.inappNotification.value,
    "inapp_notification_subscribe_comment_mention_and_reply": GraphQLQueryID.inappNotification.value,
    "business_import_page_media_delivery_subscribe": GraphQLQueryID.businessDelivery.value,
    "video_call_participant_state_delivery": GraphQLQueryID.videoCallParticipantDelivery.value,
}


class GraphQLSubscription:
    @staticmethod
    def _fmt(query_id: GraphQLQueryID, input_params: Any,
             client_logged: Optional[bool] = None) -> str:
        params = {
            "input_data": input_params,
            **({"%options": {"client_logged": client_logged}}
               if client_logged is not None else {}),
        }
        return f"1/graphqlsubscriptions/{query_id.value}/{json.dumps(params)}"

    @classmethod
    def app_presence(cls, subscription_id: Optional[str] = None,
                     client_logged: Optional[bool] = None) -> str:
        return cls._fmt(GraphQLQueryID.appPresence,
                        input_params={"client_subscription_id": subscription_id or str(uuid4())},
                        client_logged=client_logged)

    @classmethod
    def async_ad(cls, user_id: str, subscription_id: Optional[str] = None,
                 client_logged: Optional[bool] = None) -> str:
        return cls._fmt(GraphQLQueryID.asyncAdSub,
                        input_params={"client_subscription_id": subscription_id or str(uuid4()),
                                      "user_id": user_id},
                        client_logged=client_logged)

    @classmethod
    def client_config_update(cls, subscription_id: Optional[str] = None,
                             client_logged: Optional[bool] = None) -> str:
        return cls._fmt(GraphQLQueryID.clientConfigUpdate,
                        input_params={"client_subscription_id": subscription_id or str(uuid4())},
                        client_logged=client_logged)

    @classmethod
    def direct_status(cls, subscription_id: Optional[str] = None,
                      client_logged: Optional[bool] = None) -> str:
        return cls._fmt(GraphQLQueryID.directStatus,
                        input_params={"client_subscription_id": subscription_id or str(uuid4())},
                        client_logged=client_logged)

    @classmethod
    def direct_typing(cls, user_id: str, client_logged: Optional[bool] = None) -> str:
        return cls._fmt(GraphQLQueryID.directTyping,
                        input_params={"user_id": user_id},
                        client_logged=client_logged)

    @classmethod
    def ig_live_wave(cls, broadcast_id: str, receiver_id: str,
                     subscription_id: Optional[str] = None, client_logged: Optional[bool] = None
                     ) -> str:
        return cls._fmt(GraphQLQueryID.liveWave,
                        input_params={"client_subscription_id": subscription_id or str(uuid4()),
                                      "broadcast_id": broadcast_id, "receiver_id": receiver_id},
                        client_logged=client_logged)

    @classmethod
    def interactivity_activate_question(cls, broadcast_id: str,
                                        subscription_id: Optional[str] = None,
                                        client_logged: Optional[bool] = None) -> str:
        return cls._fmt(GraphQLQueryID.interactivityActivateQuestion,
                        input_params={"client_subscription_id": subscription_id or str(uuid4()),
                                      "broadcast_id": broadcast_id},
                        client_logged=client_logged)

    @classmethod
    def interactivity_realtime_question_submissions_status(
        cls, broadcast_id: str, subscription_id: Optional[str] = None,
        client_logged: Optional[bool] = None
    ) -> str:
        return cls._fmt(GraphQLQueryID.interactivityRealtimeQuestionSubmissionsStatus,
                        input_params={"client_subscription_id": subscription_id or str(uuid4()),
                                      "broadcast_id": broadcast_id},
                        client_logged=client_logged)

    @classmethod
    def interactivity(cls, broadcast_id: str, subscription_id: Optional[str] = None,
                      client_logged: Optional[bool] = None) -> str:
        return cls._fmt(GraphQLQueryID.interactivitySub,
                        input_params={"client_subscription_id": subscription_id or str(uuid4()),
                                      "broadcast_id": broadcast_id},
                        client_logged=client_logged)

    @classmethod
    def live_realtime_comments(cls, broadcast_id: str, subscription_id: Optional[str] = None,
                               client_logged: Optional[bool] = None) -> str:
        return cls._fmt(GraphQLQueryID.liveRealtimeComments,
                        input_params={"client_subscription_id": subscription_id or str(uuid4()),
                                      "broadcast_id": broadcast_id},
                        client_logged=client_logged)

    @classmethod
    def live_realtime_typing_indicator(cls, broadcast_id: str,
                                       subscription_id: Optional[str] = None,
                                       client_logged: Optional[bool] = None) -> str:
        return cls._fmt(GraphQLQueryID.liveTypingIndicator,
                        input_params={"client_subscription_id": subscription_id or str(uuid4()),
                                      "broadcast_id": broadcast_id},
                        client_logged=client_logged)

    @classmethod
    def media_feedback(cls, feedback_id: str, subscription_id: Optional[str] = None,
                       client_logged: Optional[bool] = None) -> str:
        return cls._fmt(GraphQLQueryID.mediaFeedback,
                        input_params={"client_subscription_id": subscription_id or str(uuid4()),
                                      "feedback_id": feedback_id},
                        client_logged=client_logged)

    @classmethod
    def react_native_ota_update(cls, build_number: str, subscription_id: Optional[str] = None,
                                client_logged: Optional[bool] = None) -> str:
        return cls._fmt(GraphQLQueryID.reactNativeOTA,
                        input_params={"client_subscription_id": subscription_id or str(uuid4()),
                                      "build_number": build_number},
                        client_logged=client_logged)

    @classmethod
    def video_call_co_watch_control(cls, video_call_id: str, subscription_id: Optional[str] = None,
                                    client_logged: Optional[bool] = None) -> str:
        return cls._fmt(GraphQLQueryID.videoCallCoWatchControl,
                        input_params={"client_subscription_id": subscription_id or str(uuid4()),
                                      "video_call_id": video_call_id},
                        client_logged=client_logged)

    @classmethod
    def video_call_in_call_alert(cls, video_call_id: str, subscription_id: Optional[str] = None,
                                 client_logged: Optional[bool] = None) -> str:
        return cls._fmt(GraphQLQueryID.videoCallInAlert,
                        input_params={"client_subscription_id": subscription_id or str(uuid4()),
                                      "video_call_id": video_call_id},
                        client_logged=client_logged)

    @classmethod
    def video_call_prototype_publish(cls, video_call_id: str,
                                     subscription_id: Optional[str] = None,
                                     client_logged: Optional[bool] = None) -> str:
        return cls._fmt(GraphQLQueryID.videoCallPrototypePublish,
                        input_params={"client_subscription_id": subscription_id or str(uuid4()),
                                      "video_call_id": video_call_id},
                        client_logged=client_logged)

    @classmethod
    def zero_provision(cls, device_id: str, subscription_id: Optional[str] = None,
                       client_logged: Optional[bool] = None) -> str:
        return cls._fmt(GraphQLQueryID.zeroProvision,
                        input_params={"client_subscription_id": subscription_id or str(uuid4()),
                                      "device_id": device_id},
                        client_logged=client_logged)
