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
from typing import List, Optional

from attr import dataclass

from mautrix.types import SerializableAttrs


@dataclass
class SpamResponse(SerializableAttrs):
    feedback_title: str
    feedback_message: str
    feedback_url: str
    feedback_appeal_label: str
    feedback_ignore_label: str
    feedback_action: str
    message: str = "feedback_required"
    spam: bool = True
    status: str = "fail"
    error_type: Optional[str] = None


@dataclass
class CheckpointChallenge(SerializableAttrs):
    url: str
    api_path: str
    hide_webview_header: bool
    lock: bool
    logout: bool
    native_flow: bool


@dataclass
class CheckpointResponse(SerializableAttrs):
    message: str  # challenge_required
    status: str  # fail
    challenge: CheckpointChallenge
    error_type: Optional[str] = None


@dataclass
class ConsentData(SerializableAttrs):
    headline: str
    content: str
    button_text: str


@dataclass
class ConsentRequiredResponse(SerializableAttrs):
    message: str  # consent_required
    status: str  # fail
    consent_data: ConsentData


@dataclass
class LoginRequiredResponse(SerializableAttrs):
    # TODO enum?
    logout_reason: int
    message: str  # login_required or user_has_logged_out
    status: str  # fail
    error_title: Optional[str] = None
    error_body: Optional[str] = None


@dataclass
class LoginErrorResponseButton(SerializableAttrs):
    title: str
    action: str


@dataclass
class LoginPhoneVerificationSettings(SerializableAttrs):
    max_sms_count: int
    resend_sms_delay_sec: int
    robocall_count_down_time_sec: int
    robocall_after_max_sms: bool


@dataclass
class LoginTwoFactorInfo(SerializableAttrs):
    username: str
    sms_two_factor_on: bool
    totp_two_factor_on: bool
    obfuscated_phone_number: str
    two_factor_identifier: str
    show_messenger_code_option: bool
    show_new_login_screen: bool
    show_trusted_device_option: bool
    should_opt_in_trusted_device_option: bool
    pending_trusted_notification: bool
    # TODO type
    # sms_not_allowed_reason: Any
    phone_verification_settings: Optional[LoginPhoneVerificationSettings] = None


@dataclass
class LoginErrorResponse(SerializableAttrs):
    message: str
    status: str
    error_type: str
    error_title: Optional[str] = None
    buttons: Optional[List[LoginErrorResponseButton]] = None
    invalid_credentials: Optional[bool] = None
    two_factor_required: Optional[bool] = None
    two_factor_info: Optional[LoginTwoFactorInfo] = None
    phone_verification_settings: Optional[LoginPhoneVerificationSettings] = None

    # FB login error fields
    account_created: Optional[bool] = None
    dryrun_passed: Optional[bool] = None
